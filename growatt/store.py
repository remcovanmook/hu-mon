import collections
import json
import logging
import sqlite3
import threading
import time
from typing import Dict, List, Optional

from growatt.reading import GrowattReading

logger = logging.getLogger(__name__)

# Constants for bucket sizing
MS_5S = 5000
MS_1M = 60000
MS_1H = 3600000

SCHEMA = """
-- Rollup tables
CREATE TABLE IF NOT EXISTS readings_5s (
    ts                 INTEGER NOT NULL,
    serial             TEXT    NOT NULL,
    n                  INTEGER NOT NULL,
    pv_total_w_mean    REAL    NOT NULL,
    pv1_v_mean REAL NOT NULL, pv1_a_mean REAL NOT NULL, pv1_w_mean REAL NOT NULL,
    pv2_v_mean REAL NOT NULL, pv2_a_mean REAL NOT NULL, pv2_w_mean REAL NOT NULL,
    pv3_v_mean REAL NOT NULL, pv3_a_mean REAL NOT NULL, pv3_w_mean REAL NOT NULL,
    pv4_v_mean REAL NOT NULL, pv4_a_mean REAL NOT NULL, pv4_w_mean REAL NOT NULL,
    grid_l1_v_mean REAL NOT NULL, grid_l1_a_mean REAL NOT NULL,
    grid_l2_v_mean REAL NOT NULL, grid_l2_a_mean REAL NOT NULL,
    grid_l3_v_mean REAL NOT NULL, grid_l3_a_mean REAL NOT NULL,
    grid_freq_mean     REAL    NOT NULL,
    meter_total_w_mean REAL    NOT NULL,
    bat_soc_mean       REAL    NOT NULL,
    bat_v_mean REAL NOT NULL, bat_i_mean REAL NOT NULL, bat_p_mean REAL NOT NULL,
    load_p_mean        REAL    NOT NULL,
    eps_p_mean         REAL    NOT NULL,
    status_code        INTEGER NOT NULL,
    UNIQUE (ts, serial)
);

CREATE TABLE IF NOT EXISTS readings_1m AS SELECT * FROM readings_5s WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_1m_ts ON readings_1m(ts, serial);

CREATE TABLE IF NOT EXISTS readings_1h AS SELECT * FROM readings_5s WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_1h_ts ON readings_1h(ts, serial);

CREATE TABLE IF NOT EXISTS latest_registers (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    ts          INTEGER NOT NULL,
    raw_payload BLOB    NOT NULL
);
"""

UPSERT_SQL = """
INSERT INTO {table} (
    ts, serial, n, pv_total_w_mean,
    pv1_v_mean, pv1_a_mean, pv1_w_mean,
    pv2_v_mean, pv2_a_mean, pv2_w_mean,
    pv3_v_mean, pv3_a_mean, pv3_w_mean,
    pv4_v_mean, pv4_a_mean, pv4_w_mean,
    grid_l1_v_mean, grid_l1_a_mean,
    grid_l2_v_mean, grid_l2_a_mean,
    grid_l3_v_mean, grid_l3_a_mean,
    grid_freq_mean, meter_total_w_mean,
    bat_soc_mean, bat_v_mean, bat_i_mean, bat_p_mean,
    load_p_mean, eps_p_mean, eps_l1_v_mean, eps_l1_a_mean, eps_l2_v_mean, eps_l2_a_mean, eps_l3_v_mean, eps_l3_a_mean, status_code
) VALUES (
    ?, ?, 1, ?, 
    ?, ?, ?, 
    ?, ?, ?, 
    ?, ?, ?, 
    ?, ?, ?, 
    ?, ?, 
    ?, ?, 
    ?, ?, 
    ?, ?, 
    ?, ?, ?, ?, 
    ?, ?, ?, ?, ?, ?, ?, ?, ?
) ON CONFLICT(ts, serial) DO UPDATE SET
    n = n + 1,
    pv_total_w_mean = (pv_total_w_mean * n + excluded.pv_total_w_mean) / (n + 1),
    pv1_v_mean = (pv1_v_mean * n + excluded.pv1_v_mean) / (n + 1),
    pv1_a_mean = (pv1_a_mean * n + excluded.pv1_a_mean) / (n + 1),
    pv1_w_mean = (pv1_w_mean * n + excluded.pv1_w_mean) / (n + 1),
    pv2_v_mean = (pv2_v_mean * n + excluded.pv2_v_mean) / (n + 1),
    pv2_a_mean = (pv2_a_mean * n + excluded.pv2_a_mean) / (n + 1),
    pv2_w_mean = (pv2_w_mean * n + excluded.pv2_w_mean) / (n + 1),
    pv3_v_mean = (pv3_v_mean * n + excluded.pv3_v_mean) / (n + 1),
    pv3_a_mean = (pv3_a_mean * n + excluded.pv3_a_mean) / (n + 1),
    pv3_w_mean = (pv3_w_mean * n + excluded.pv3_w_mean) / (n + 1),
    pv4_v_mean = (pv4_v_mean * n + excluded.pv4_v_mean) / (n + 1),
    pv4_a_mean = (pv4_a_mean * n + excluded.pv4_a_mean) / (n + 1),
    pv4_w_mean = (pv4_w_mean * n + excluded.pv4_w_mean) / (n + 1),
    grid_l1_v_mean = (grid_l1_v_mean * n + excluded.grid_l1_v_mean) / (n + 1),
    grid_l1_a_mean = (grid_l1_a_mean * n + excluded.grid_l1_a_mean) / (n + 1),
    grid_l2_v_mean = (grid_l2_v_mean * n + excluded.grid_l2_v_mean) / (n + 1),
    grid_l2_a_mean = (grid_l2_a_mean * n + excluded.grid_l2_a_mean) / (n + 1),
    grid_l3_v_mean = (grid_l3_v_mean * n + excluded.grid_l3_v_mean) / (n + 1),
    grid_l3_a_mean = (grid_l3_a_mean * n + excluded.grid_l3_a_mean) / (n + 1),
    grid_freq_mean = (grid_freq_mean * n + excluded.grid_freq_mean) / (n + 1),
    meter_total_w_mean = (meter_total_w_mean * n + excluded.meter_total_w_mean) / (n + 1),
    bat_soc_mean = (bat_soc_mean * n + excluded.bat_soc_mean) / (n + 1),
    bat_v_mean = (bat_v_mean * n + excluded.bat_v_mean) / (n + 1),
    bat_i_mean = (bat_i_mean * n + excluded.bat_i_mean) / (n + 1),
    bat_p_mean = (bat_p_mean * n + excluded.bat_p_mean) / (n + 1),
    load_p_mean = (load_p_mean * n + excluded.load_p_mean) / (n + 1),
    eps_p_mean = (eps_p_mean * n + excluded.eps_p_mean) / (n + 1),
    eps_l1_v_mean = (eps_l1_v_mean * n + excluded.eps_l1_v_mean) / (n + 1),
    eps_l1_a_mean = (eps_l1_a_mean * n + excluded.eps_l1_a_mean) / (n + 1),
    eps_l2_v_mean = (eps_l2_v_mean * n + excluded.eps_l2_v_mean) / (n + 1),
    eps_l2_a_mean = (eps_l2_a_mean * n + excluded.eps_l2_a_mean) / (n + 1),
    eps_l3_v_mean = (eps_l3_v_mean * n + excluded.eps_l3_v_mean) / (n + 1),
    eps_l3_a_mean = (eps_l3_a_mean * n + excluded.eps_l3_a_mean) / (n + 1),
    status_code = excluded.status_code;
"""

class GrowattStore:
    def __init__(self, db_path: str = "growatt.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        
        # 1-hour live buffer for SSE (720 items at 5s polling)
        self.ring = collections.deque(maxlen=720)
        
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            conn.executescript(SCHEMA)
            conn.commit()

    def _get_row_tuple(self, ts_bucket: int, r: GrowattReading) -> tuple:
        return (
            ts_bucket, r.serial, r.pv_total_w,
            r.pv1_v, r.pv1_a, r.pv1_w,
            r.pv2_v, r.pv2_a, r.pv2_w,
            r.pv3_v, r.pv3_a, r.pv3_w,
            r.pv4_v, r.pv4_a, r.pv4_w,
            r.grid_l1_v, r.grid_l1_a,
            r.grid_l2_v, r.grid_l2_a,
            r.grid_l3_v, r.grid_l3_a,
            r.grid_freq, r.meter_total_w,
            r.bat_soc, r.bat_v, r.bat_i, r.bat_p,
            r.load_p, r.eps_p, 
            r.eps_l1_v, r.eps_l1_a, 
            r.eps_l2_v, r.eps_l2_a, 
            r.eps_l3_v, r.eps_l3_a, 
            r.status_code
        )

    def insert(self, r: GrowattReading):
        """Insert a 5s reading into the RAM buffer and SQLite DB."""
        with self._lock:
            self.ring.append(r)
            
            conn = self._get_conn()
            
            # Atomic update of proxy registers
            if r.raw_payload:
                conn.execute(
                    "INSERT OR REPLACE INTO latest_registers (id, ts, raw_payload) VALUES (1, ?, ?)",
                    (r.ts, r.raw_payload)
                )

            ts_5s = (r.ts // MS_5S) * MS_5S
            ts_1m = (r.ts // MS_1M) * MS_1M

            # Insert into 5s bucket
            conn.execute(UPSERT_SQL.format(table="readings_5s"), self._get_row_tuple(ts_5s, r))
            # Insert into 1m bucket
            conn.execute(UPSERT_SQL.format(table="readings_1m"), self._get_row_tuple(ts_1m, r))
            
            conn.commit()

    def latest_reading(self) -> Optional[GrowattReading]:
        with self._lock:
            return self.ring[-1] if self.ring else None

    def get_latest_registers(self) -> bytes:
        """Returns the raw serialized Modbus payload for the TCP Proxy Server."""
        conn = self._get_conn()
        row = conn.execute("SELECT raw_payload FROM latest_registers WHERE id = 1").fetchone()
        return row[0] if row else b''

    def prune(self):
        """Called periodically (e.g. by dashboard thread) to roll up 1h data."""
        # TODO: Implement 1h rollup (SUM(mean*n)/SUM(n)) and DELETE retention logic.
        pass

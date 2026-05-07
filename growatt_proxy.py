import time
import sqlite3
import threading
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymodbus.client import ModbusTcpClient

# --- CONFIGURATION ---
INVERTER_IP = "192.168.1.100"  # Change to your Inverter IP
MODBUS_PORT = 5020
HTTP_PORT = 8080               # Prometheus Scrape Port
MQTT_TOPIC = "solar/12ktl3/state"

# --- DATABASE MANAGER (THE HEGG-EMON PATTERN) ---
class InverterDB:
    def __init__(self, db_path="solar_monitor.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_raw (
                    ts TIMESTAMP DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                    status INT, pv_total_w REAL,
                    pv1_v REAL, pv1_a REAL, pv2_v REAL, pv2_a REAL,
                    pv3_v REAL, pv3_a REAL, pv4_v REAL, pv4_a REAL,
                    bat_soc INT, bat_w REAL, grid_w REAL, load_w REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_hourly (
                    hour_ts TIMESTAMP PRIMARY KEY,
                    avg_pv_w REAL, yield_wh REAL,
                    export_wh REAL, import_wh REAL,
                    avg_bat_soc REAL, avg_load_w REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_daily (
                    day_date DATE PRIMARY KEY,
                    total_yield_kwh REAL, total_export_kwh REAL, total_import_kwh REAL,
                    max_pv_w REAL, min_soc INT, max_soc INT
                )
            """)
            conn.commit()

    def log_raw(self, d):
        with self.lock, self._get_conn() as conn:
            conn.execute("""
                INSERT INTO telemetry_raw (
                    status, pv_total_w, pv1_v, pv1_a, pv2_v, pv2_a, 
                    pv3_v, pv3_a, pv4_v, pv4_a, bat_soc, bat_w, grid_w, load_w
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                d['status'], d['pv_total_w'], d['pv1_v'], d['pv1_a'], 
                d['pv2_v'], d['pv2_a'], d['pv3_v'], d['pv3_a'], 
                d['pv4_v'], d['pv4_a'], d['bat_soc'], d['bat_w'], 
                d['grid_w'], d['load_w']
            ))

    def aggregate_hourly(self):
        with self.lock, self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO telemetry_hourly (hour_ts, avg_pv_w, yield_wh, export_wh, import_wh, avg_bat_soc, avg_load_w)
                SELECT strftime('%Y-%m-%d %H:00:00', ts), AVG(pv_total_w), AVG(pv_total_w),
                       SUM(CASE WHEN grid_w > 0 THEN grid_w ELSE 0 END) / 720,
                       ABS(SUM(CASE WHEN grid_w < 0 THEN grid_w ELSE 0 END)) / 720,
                       AVG(bat_soc), AVG(load_w)
                FROM telemetry_raw WHERE ts >= datetime('now', '-1 hour', 'localtime') GROUP BY 1
            """)
            conn.execute("DELETE FROM telemetry_raw WHERE ts < datetime('now', '-48 hours', 'localtime')")
            conn.commit()

    def aggregate_daily(self):
        with self.lock, self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO telemetry_daily (day_date, total_yield_kwh, total_export_kwh, total_import_kwh, max_pv_w, min_soc, max_soc)
                SELECT date(hour_ts), SUM(yield_wh)/1000, SUM(export_wh)/1000, SUM(import_wh)/1000, MAX(avg_pv_w), MIN(avg_bat_soc), MAX(avg_bat_soc)
                FROM telemetry_hourly WHERE hour_ts >= date('now', '-1 day', 'localtime') GROUP BY 1
            """)
            conn.commit()

    def get_latest(self):
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM telemetry_raw ORDER BY ts DESC LIMIT 1").fetchone()
            return dict(row) if row else None

# --- UTILS & MODBUS ---
def parse_s32(high, low):
    val = (high << 16) | low
    return val - 0x100000000 if val > 0x7FFFFFFF else val

def fetch_data(client):
    # Segment 1: Status & 4 PV Inputs (3000-3020)
    r1 = client.read_input_registers(3000, 20, slave=1).registers
    # Segment 2: Load, Meter, Battery (3048, 3118-3175)
    # Note: Using offsets from 3000 for simplicity or distinct reads
    r_load = client.read_input_registers(3048, 2, slave=1).registers
    r_meter = client.read_input_registers(3118, 10, slave=1).registers
    r_bat = client.read_input_registers(3170, 10, slave=1).registers

    return {
        "status": r1[0],
        "pv_total_w": ((r1[1] << 16) | r1[2]) / 10.0,
        "pv1_v": r1[3]/10.0, "pv1_a": r1[4]/10.0, "pv1_w": ((r1[5] << 16) | r1[6]) / 10.0,
        "pv2_v": r1[7]/10.0, "pv2_a": r1[8]/10.0, "pv2_w": ((r1[9] << 16) | r1[10]) / 10.0,
        "pv3_v": r1[11]/10.0, "pv3_a": r1[12]/10.0, "pv3_w": ((r1[13] << 16) | r1[14]) / 10.0,
        "pv4_v": r1[15]/10.0 if r1[15] < 2000 else 0, 
        "pv4_a": r1[16]/10.0 if r1[15] < 2000 else 0,
        "pv4_w": (((r1[17] << 16) | r1[18]) / 10.0) if r1[15] < 2000 else 0,
        "load_w": ((r_load[0] << 16) | r_load[1]) / 10.0,
        "grid_w": parse_s32(r_meter[3], r_meter[4]) / 10.0,
        "bat_soc": r_bat[0],
        "bat_w": parse_s32(r_bat[3], r_bat[4]) / 10.0
    }

# --- THREADED WORKERS ---
db = InverterDB()

def poller():
    client = ModbusTcpClient(INVERTER_IP, port=MODBUS_PORT)
    while True:
        try:
            if not client.is_socket_open(): client.connect()
            data = fetch_data(client)
            db.log_raw(data)
            # Maintenance: Aggregate hourly/daily
            if time.localtime().tm_min % 15 == 0: db.aggregate_hourly()
            if time.localtime().tm_hour == 0 and time.localtime().tm_min == 1: db.aggregate_daily()
        except Exception as e:
            print(f"Poller Error: {e}")
        time.sleep(5)

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        latest = db.get_latest()
        if latest:
            res = "\n".join([f"solar_{k} {v}" for k, v in latest.items() if isinstance(v, (int, float))])
            self.wfile.write(res.encode())

# --- ENTRY POINT ---
if __name__ == "__main__":
    threading.Thread(target=poller, daemon=True).start()
    server = HTTPServer(('0.0.0.0', HTTP_PORT), MetricsHandler)
    print(f"Proxy active. Prometheus metrics at :{HTTP_PORT}")
    server.serve_forever()
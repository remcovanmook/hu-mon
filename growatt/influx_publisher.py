"""
growatt/influx_publisher.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Publishes GrowattReading telemetry to InfluxDB using the line protocol.

Supports both InfluxDB v1 (database, no auth token) and v2 (org, bucket,
API token).  The measurement name is ``growatt``; serial number and model
string are indexed as tags so per-device queries work correctly with
multiple inverters.
"""

import logging
import time
import urllib.request
import urllib.error
from urllib.parse import urlencode

from growatt.store import GrowattStore

logger = logging.getLogger("growatt_influx")

# Reading dict keys to skip (strings, or handled separately as typed ints).
_SKIP_FIELDS = {
    "ts", "serial", "inverter_model", "inverter_serial", "inverter_firmware",
    "status_code", "fault_code", "rated_power_w",
}

# Integer-typed fields that get the ``i`` suffix in line protocol.
_INT_FIELDS = {"status_code", "fault_code", "rated_power_w"}


class InfluxPublisher:
    """
    Writes GrowattReading data to InfluxDB using the line protocol.

    Supports both InfluxDB v1 (username/password, ``/write``) and v2
    (token auth, ``/api/v2/write``).
    """

    def __init__(self, url: str, token: str, org: str, bucket: str, db: str):
        """
        :param url:    Base URL of the InfluxDB instance (e.g. http://localhost:8086).
        :param token:  InfluxDB v2 API token; leave empty for v1 auth.
        :param org:    InfluxDB v2 organisation name.
        :param bucket: InfluxDB v2 bucket name.
        :param db:     InfluxDB v1 database name.
        """
        self.url = url.rstrip('/')
        self.token = token
        self.org = org
        self.bucket = bucket
        self.db = db

    def write_line(self, line: str) -> bool:
        """
        Write a single line-protocol record to InfluxDB.

        :param line: Fully formed InfluxDB line protocol string.
        :returns:    True on HTTP 200/204, False on any error.
        """
        headers = {'Content-Type': 'text/plain; charset=utf-8'}
        if self.token:
            # InfluxDB v2
            headers['Authorization'] = f'Token {self.token}'
            query = urlencode({'org': self.org, 'bucket': self.bucket, 'precision': 's'})
            endpoint = f"{self.url}/api/v2/write?{query}"
        else:
            # InfluxDB v1
            query = urlencode({'db': self.db, 'precision': 's'})
            endpoint = f"{self.url}/write?{query}"

        req = urllib.request.Request(
            endpoint, data=line.encode('utf-8'), headers=headers, method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status not in (200, 204):
                    logger.warning("Influx HTTP %d: %s", resp.status, resp.read())
                    return False
                return True
        except urllib.error.URLError as exc:
            logger.warning("Influx write failed: %s", exc)
            return False

    def build_line(self, r) -> str:
        """
        Convert a GrowattReading to an InfluxDB line protocol string.

        Tags (indexed, low-cardinality): ``serial``, ``model``.
        Fields: all numeric GrowattReading values.
        Timestamp is seconds since epoch (precision=s).

        :param r: GrowattReading instance.
        :returns: Line protocol string ready for ``write_line``.
        """
        # Escape spaces/commas in tag values per line protocol spec.
        def _tag(v: str) -> str:
            return v.replace(' ', r'\ ').replace(',', r'\,') or 'unknown'

        tags = f"serial={_tag(r.inverter_serial)},model={_tag(r.inverter_model)}"

        fields = []
        for k, v in r.to_dict().items():
            if k in _SKIP_FIELDS:
                continue
            if isinstance(v, float):
                fields.append(f"{k}={v}")
            elif isinstance(v, int):
                fields.append(f"{k}={v}i")

        # Explicitly typed integer fields excluded from to_dict float path.
        for k in _INT_FIELDS:
            v = getattr(r, k, None)
            if isinstance(v, int):
                fields.append(f"{k}={v}i")

        ts_s = r.ts // 1000
        return f"growatt,{tags} {','.join(fields)} {ts_s}"


def run_influx_loop(
    store: GrowattStore,
    url: str,
    token: str = "",
    org: str = "",
    bucket: str = "",
    db: str = "growatt",
) -> None:
    """
    Blocking loop: publish new readings to InfluxDB as they arrive.

    Polls the store every 2 seconds and writes only when a reading newer
    than the last published one is available.  All errors are logged and
    the loop continues; the thread does not exit on transient failures.

    :param store:  GrowattStore providing latest readings.
    :param url:    InfluxDB base URL.
    :param token:  v2 API token (empty for v1).
    :param org:    v2 organisation.
    :param bucket: v2 bucket.
    :param db:     v1 database name.
    """
    publisher = InfluxPublisher(url, token, org, bucket, db)
    logger.info("InfluxDB exporter started -> %s", url)
    last_ts = 0
    while True:
        time.sleep(2.0)
        try:
            r = store.latest_reading()
            if r and r.ts > last_ts:
                last_ts = r.ts
                line = publisher.build_line(r)
                publisher.write_line(line)
        except Exception as exc:
            logger.error("InfluxDB loop error: %s", exc)

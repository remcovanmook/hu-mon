import json
import logging
import time
import urllib.request
import urllib.error
from urllib.parse import urlencode

from growatt.store import GrowattStore

logger = logging.getLogger("growatt_influx")

class InfluxPublisher:
    def __init__(self, url: str, token: str, org: str, bucket: str, db: str):
        self.url = url.rstrip('/')
        self.token = token
        self.org = org
        self.bucket = bucket
        self.db = db

    def write_line(self, line: str):
        headers = {'Content-Type': 'text/plain; charset=utf-8'}
        if self.token:
            # Influx V2
            headers['Authorization'] = f'Token {self.token}'
            query = urlencode({'org': self.org, 'bucket': self.bucket, 'precision': 's'})
            endpoint = f"{self.url}/api/v2/write?{query}"
        else:
            # Influx V1
            query = urlencode({'db': self.db, 'precision': 's'})
            endpoint = f"{self.url}/write?{query}"
            
        req = urllib.request.Request(endpoint, data=line.encode('utf-8'), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status not in (200, 204):
                    logger.warning("Influx HTTP %d: %s", resp.status, resp.read())
        except urllib.error.URLError as e:
            logger.warning("Influx HTTP Error: %s", e)

def run_influx_loop(store: GrowattStore, url: str, token: str = "", org: str = "", bucket: str = "", db: str = "growatt"):
    publisher = InfluxPublisher(url, token, org, bucket, db)
    last_ts = 0
    while True:
        time.sleep(2.0)
        r = store.latest_reading()
        if r and r.ts > last_ts:
            last_ts = r.ts
            # Format to Line Protocol
            fields = []
            for k, v in r.to_dict().items():
                if isinstance(v, (int, float)):
                    fields.append(f"{k}={v}")
            if fields:
                line = f"growatt,device=MOD_12KTL3 {','.join(fields)} {r.ts // 1000}"
                publisher.write_line(line)

import os
import unittest
import time
from growatt.reading import GrowattReading
from growatt.store import GrowattStore

class TestGrowattStore(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_store.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.store = GrowattStore(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_insert_and_latest(self):
        r = GrowattReading(pv_total_w=123.4, bat_soc=85.0, raw_payload=b'{"3000": 1}')
        self.store.insert(r)
        
        latest = self.store.latest_reading()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.pv_total_w, 123.4)
        self.assertEqual(latest.bat_soc, 85.0)

        # Check proxy cache
        raw = self.store.get_latest_registers()
        self.assertEqual(raw, b'{"3000": 1}')

    def test_moving_average_aggregation(self):
        base_ts = 1600000000000
        # Insert 1st reading (5s boundary)
        r1 = GrowattReading(ts=base_ts, pv_total_w=100.0)
        self.store.insert(r1)
        
        # Insert 2nd reading in the exact same 5s bucket
        r2 = GrowattReading(ts=base_ts + 1000, pv_total_w=200.0)
        self.store.insert(r2)

        # Read back the 5s bucket to verify the moving average (should be 150.0)
        conn = self.store._get_conn()
        row = conn.execute("SELECT n, pv_total_w_mean FROM readings_5s WHERE ts = ?", (base_ts,)).fetchone()
        
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 2)  # n = 2
        self.assertEqual(row[1], 150.0)  # average of 100 and 200

if __name__ == '__main__':
    unittest.main()

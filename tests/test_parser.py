"""
tests.test_parser
~~~~~~~~~~~~~~~~~
Legacy parser tests, migrated to use the sentinel-aware wrappers in
growatt.drivers.growatt_base now that the parse_* functions have been
removed from growatt_collector.

Tests verify the Growatt-specific 0xFFFF sentinel behaviour (returns 0)
which is intentionally separate from the generic growatt.drivers.codec.
"""

import unittest

from growatt.drivers.growatt_base import _u16, _s16, _u32, _s32


class TestModbusParser(unittest.TestCase):
    def test_parse_u16(self):
        self.assertEqual(_u16(0), 0)
        self.assertEqual(_u16(100), 100)
        self.assertEqual(_u16(0xFFFF), 0)  # Night mode sentinel

    def test_parse_s16(self):
        self.assertEqual(_s16(100), 100)
        self.assertEqual(_s16(0xFFFF), 0)  # Sentinel
        self.assertEqual(_s16(0xFFFE), -2)

    def test_parse_u32(self):
        self.assertEqual(_u32(0, 100), 100)
        self.assertEqual(_u32(1, 0), 65536)
        self.assertEqual(_u32(0xFFFF, 0xFFFF), 0)  # Night mode sentinel

    def test_parse_s32(self):
        self.assertEqual(_s32(0, 100), 100)
        self.assertEqual(_s32(0xFFFF, 0xFFFF), 0)  # Sentinel (ambiguous with -1, sentinel wins)
        self.assertEqual(_s32(0xFFFF, 0xFFFE), -2)


if __name__ == '__main__':
    unittest.main()

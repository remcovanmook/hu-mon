import unittest
from growatt_collector import parse_u16, parse_s16, parse_u32, parse_s32

class TestModbusParser(unittest.TestCase):
    def test_parse_u16(self):
        self.assertEqual(parse_u16(0), 0)
        self.assertEqual(parse_u16(100), 100)
        self.assertEqual(parse_u16(0xFFFF), 0)  # Night mode coercion

    def test_parse_s16(self):
        self.assertEqual(parse_s16(100), 100)
        self.assertEqual(parse_s16(0xFFFF), 0)
        self.assertEqual(parse_s16(0xFFFE), -2)  # Negative representation

    def test_parse_u32(self):
        self.assertEqual(parse_u32(0, 100), 100)
        self.assertEqual(parse_u32(1, 0), 65536)
        self.assertEqual(parse_u32(0xFFFF, 0xFFFF), 0)  # Night mode coercion

    def test_parse_s32(self):
        self.assertEqual(parse_s32(0, 100), 100)
        self.assertEqual(parse_s32(0xFFFF, 0xFFFF), 0)
        self.assertEqual(parse_s32(0xFFFF, 0xFFFE), -2)

if __name__ == '__main__':
    unittest.main()

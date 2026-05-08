"""
tests.test_codec
~~~~~~~~~~~~~~~~
Unit tests for growatt.drivers.codec.

Covers every public function: boundary values, sign boundaries, byte-swap
correctness, IEEE 754 round-trips, and ASCII decoding edge cases.
"""

import math
import struct
import unittest

from growatt.drivers.codec import (
    ascii_regs,
    float32_be,
    float32_le,
    s16_be,
    s16_le,
    s32_be,
    s32_le,
    u16_be,
    u16_le,
    u32_be,
    u32_le,
)


class TestU16Be(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(u16_be(0), 0)

    def test_max(self):
        self.assertEqual(u16_be(0xFFFF), 65535)

    def test_midpoint(self):
        self.assertEqual(u16_be(0x8000), 32768)

    def test_masks_overflow(self):
        # Only the lower 16 bits should be used.
        self.assertEqual(u16_be(0x1ABCD), 0xABCD)


class TestS16Be(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(s16_be(0), 0)

    def test_positive_max(self):
        self.assertEqual(s16_be(0x7FFF), 32767)

    def test_negative_one(self):
        # 0xFFFF is -1 in two's complement 16-bit.
        self.assertEqual(s16_be(0xFFFF), -1)

    def test_min_value(self):
        # 0x8000 is -32768.
        self.assertEqual(s16_be(0x8000), -32768)


class TestU16Le(unittest.TestCase):
    def test_byte_swap(self):
        # 0x0102 → bytes [01, 02] → swapped → [02, 01] → 0x0201 = 513
        self.assertEqual(u16_le(0x0102), 0x0201)

    def test_zero(self):
        self.assertEqual(u16_le(0), 0)

    def test_symmetric(self):
        self.assertEqual(u16_le(0xABCD), 0xCDAB)


class TestS16Le(unittest.TestCase):
    def test_positive(self):
        # 0x0001 swapped → 0x0100 = 256
        self.assertEqual(s16_le(0x0001), 256)

    def test_negative(self):
        # 0x00FF swapped → 0xFF00 = -256
        self.assertEqual(s16_le(0x00FF), -256)


class TestU32Be(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(u32_be(0, 0), 0)

    def test_max(self):
        self.assertEqual(u32_be(0xFFFF, 0xFFFF), 0xFFFFFFFF)

    def test_known_value(self):
        # high=1, low=0 → 0x00010000 = 65536
        self.assertEqual(u32_be(1, 0), 65536)

    def test_scaling_example(self):
        # Growatt raw value 12000 W delivered as high=0, low=12000
        self.assertEqual(u32_be(0, 12000), 12000)


class TestS32Be(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(s32_be(0, 0), 0)

    def test_positive(self):
        self.assertEqual(s32_be(0, 500), 500)

    def test_negative(self):
        # 0xFFFF FFFF = -1 in 32-bit two's complement
        self.assertEqual(s32_be(0xFFFF, 0xFFFF), -1)

    def test_min(self):
        # 0x80000000 = -2147483648
        self.assertEqual(s32_be(0x8000, 0x0000), -2147483648)


class TestU32Le(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(u32_le(0, 0), 0)

    def test_swapped_vs_be(self):
        # u32_le(low, high) should equal u32_be(high, low)
        self.assertEqual(u32_le(0x0034, 0x0012), u32_be(0x0012, 0x0034))


class TestS32Le(unittest.TestCase):
    def test_negative(self):
        self.assertEqual(s32_le(0xFFFF, 0xFFFF), -1)


class TestFloat32Be(unittest.TestCase):
    def test_one(self):
        # 1.0 in IEEE 754 BE: 0x3F80 0x0000
        self.assertAlmostEqual(float32_be(0x3F80, 0x0000), 1.0)

    def test_negative(self):
        # -1.0: 0xBF80 0x0000
        self.assertAlmostEqual(float32_be(0xBF80, 0x0000), -1.0)

    def test_round_trip(self):
        value = 123.456
        raw = struct.pack('>f', value)
        high, low = struct.unpack('>HH', raw)
        self.assertAlmostEqual(float32_be(high, low), value, places=3)

    def test_nan(self):
        # NaN propagates correctly.
        result = float32_be(0x7FC0, 0x0000)
        self.assertTrue(math.isnan(result))


class TestFloat32Le(unittest.TestCase):
    def test_round_trip(self):
        value = 99.9
        raw = struct.pack('>f', value)
        high, low = struct.unpack('>HH', raw)
        # float32_le takes (low, high) — same internal packing, different arg order.
        self.assertAlmostEqual(float32_le(low, high), value, places=3)


class TestAsciiRegs(unittest.TestCase):
    def test_basic(self):
        # 'AB' packed into one register: 0x4142
        self.assertEqual(ascii_regs([0x4142]), 'AB')

    def test_null_stripped(self):
        # Trailing nulls are common in Growatt serial fields.
        self.assertEqual(ascii_regs([0x4100]), 'A')

    def test_multi_register(self):
        # 'Hi' across two registers: [0x4869, 0x0000]
        self.assertEqual(ascii_regs([0x4869, 0x0000]), 'Hi')

    def test_empty(self):
        self.assertEqual(ascii_regs([]), '')

    def test_all_null(self):
        self.assertEqual(ascii_regs([0x0000, 0x0000]), '')

    def test_non_printable_stripped(self):
        # Control characters should not survive.
        result = ascii_regs([0x0141])  # SOH + 'A'
        self.assertNotIn('\x01', result)
        self.assertIn('A', result)


if __name__ == '__main__':
    unittest.main()

"""
tests.test_growatt_base
~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for GrowattBaseDriver._is_growatt() and the sentinel-aware
register wrappers defined in growatt.drivers.growatt_base.

These tests exercise the vendor-level probe logic in isolation using a
minimal concrete subclass that stubs out the abstract methods.
"""

import unittest

from growatt.drivers.base import ProbeContext
from growatt.drivers.growatt_base import (
    GrowattBaseDriver,
    _s16,
    _s32,
    _u16,
    _u32,
    GROWATT_SERIES,
)
from growatt.drivers.codec import u32_be


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing the abstract class
# ---------------------------------------------------------------------------

class _StubDriver(GrowattBaseDriver):
    """Concrete stub that exposes _probe_series result as a fixed value."""

    def __init__(self, series_result: bool = True):
        self._series_result = series_result

    @property
    def driver_id(self) -> str:
        return "stub"

    def _probe_series(self, ctx):
        return self._series_result

    def read_device_info(self, client, slave_id):
        raise NotImplementedError

    def read_registers(self, client, slave_id):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_block(fw_regs=None, series_code=0x0B, power=12000, length=125):
    """
    Build a minimal holding register block (list of ints) for probe testing.

    :param fw_regs:      6 register values for positions 9-14 (firmware string).
                         Defaults to 'MOD 7.6' packed into 3 registers.
    :param series_code:  Upper 16 bits of module_id (default: 0x0B = MOD).
    :param power:        Lower 16 bits of module_id (rated power).
    :param length:       Total block length (default: 125).
    """
    block = [0] * length

    # Firmware string at regs 9-14: encode '7.6.1.8' as ASCII pairs.
    if fw_regs is None:
        fw = '7.6.1.8\x00\x00\x00\x00\x00'  # 12 bytes = 6 registers
        for i, pair in enumerate(zip(fw[::2], fw[1::2])):
            block[9 + i] = (ord(pair[0]) << 8) | ord(pair[1])
    else:
        block[9:9 + len(fw_regs)] = fw_regs

    # Module ID at regs 28-29.
    module_id = (series_code << 16) | power
    block[28] = (module_id >> 16) & 0xFFFF
    block[29] = module_id & 0xFFFF

    return block


def _make_ctx(block, fcs=None):
    return ProbeContext(
        slave_id=1,
        supported_fcs=fcs if fcs is not None else {3, 4},
        holding_block=block,
        max_block_size=125,
    )


# ---------------------------------------------------------------------------
# Tests: _is_growatt
# ---------------------------------------------------------------------------

class TestIsGrowatt(unittest.TestCase):

    def _driver(self):
        return _StubDriver(series_result=True)

    def test_valid_firmware_and_known_series(self):
        block = _make_block(series_code=0x0B)
        ctx = _make_ctx(block)
        self.assertTrue(self._driver()._is_growatt(ctx))

    def test_all_known_series_codes_accepted(self):
        driver = self._driver()
        for code in GROWATT_SERIES:
            block = _make_block(series_code=code)
            ctx = _make_ctx(block)
            self.assertTrue(driver._is_growatt(ctx), f"series_code={code:#x} should be accepted")

    def test_unknown_series_code_rejected(self):
        block = _make_block(series_code=0xFF)
        ctx = _make_ctx(block)
        self.assertFalse(self._driver()._is_growatt(ctx))

    def test_zero_module_id_rejected(self):
        # module_id == 0 means the proxy zeroed it out; cannot confirm vendor.
        block = _make_block(series_code=0x00, power=0)
        ctx = _make_ctx(block)
        self.assertFalse(self._driver()._is_growatt(ctx))

    def test_bad_firmware_string_rejected(self):
        # Replace firmware registers with gibberish (non-version pattern).
        bad_regs = [0xDEAD, 0xBEEF, 0x0000, 0x0000, 0x0000, 0x0000]
        block = _make_block(fw_regs=bad_regs, series_code=0x0B)
        ctx = _make_ctx(block)
        self.assertFalse(self._driver()._is_growatt(ctx))

    def test_empty_firmware_string_rejected(self):
        empty_regs = [0x0000] * 6
        block = _make_block(fw_regs=empty_regs, series_code=0x0B)
        ctx = _make_ctx(block)
        self.assertFalse(self._driver()._is_growatt(ctx))

    def test_none_holding_block_rejected(self):
        ctx = ProbeContext(slave_id=1, supported_fcs={3, 4}, holding_block=None, max_block_size=0)
        self.assertFalse(self._driver()._is_growatt(ctx))

    def test_short_holding_block_rejected(self):
        ctx = _make_ctx([0] * 10)
        self.assertFalse(self._driver()._is_growatt(ctx))


# ---------------------------------------------------------------------------
# Tests: two-tier probe() integration
# ---------------------------------------------------------------------------

class TestProbe(unittest.TestCase):

    def test_probe_true_when_both_tiers_pass(self):
        block = _make_block(series_code=0x0B)
        ctx = _make_ctx(block)
        self.assertTrue(_StubDriver(series_result=True).probe(ctx))

    def test_probe_false_when_series_fails(self):
        block = _make_block(series_code=0x0B)
        ctx = _make_ctx(block)
        self.assertFalse(_StubDriver(series_result=False).probe(ctx))

    def test_probe_false_when_vendor_fails(self):
        ctx = _make_ctx(None)
        self.assertFalse(_StubDriver(series_result=True).probe(ctx))

    def test_probe_never_raises_on_exception(self):
        """Probe must swallow exceptions from _probe_series."""
        class _Raiser(GrowattBaseDriver):
            @property
            def driver_id(self): return "raiser"
            def _probe_series(self, ctx): raise RuntimeError("boom")
            def read_device_info(self, c, s): raise NotImplementedError
            def read_registers(self, c, s): raise NotImplementedError

        block = _make_block(series_code=0x0B)
        ctx = _make_ctx(block)
        self.assertFalse(_Raiser().probe(ctx))


# ---------------------------------------------------------------------------
# Tests: sentinel-aware wrappers
# ---------------------------------------------------------------------------

class TestSentinelWrappers(unittest.TestCase):

    def test_u16_normal(self):
        self.assertEqual(_u16(0x0A00), 0x0A00)

    def test_u16_sentinel(self):
        self.assertEqual(_u16(0xFFFF), 0)

    def test_u16_zero(self):
        self.assertEqual(_u16(0), 0)

    def test_s16_positive(self):
        self.assertEqual(_s16(100), 100)

    def test_s16_negative(self):
        # 0xFF9C = -100 in two's complement 16-bit
        self.assertEqual(_s16(0xFF9C), -100)

    def test_s16_sentinel(self):
        self.assertEqual(_s16(0xFFFF), 0)

    def test_u32_normal(self):
        self.assertEqual(_u32(0, 12000), 12000)

    def test_u32_sentinel_both(self):
        self.assertEqual(_u32(0xFFFF, 0xFFFF), 0)

    def test_u32_sentinel_only_high(self):
        # Only one register is sentinel — should NOT be treated as zero.
        self.assertNotEqual(_u32(0xFFFF, 0), 0)

    def test_s32_negative(self):
        # 0xFFFF_FF9C = -100 in 32-bit two's complement.
        # Use high=0xFFFF, low=0xFF9C — low is not 0xFFFF, so sentinel does not fire.
        self.assertEqual(_s32(0xFFFF, 0xFF9C), -100)

    def test_s32_sentinel_both(self):
        # When both high and low are 0xFFFF, we treat it as the sleep sentinel.
        # This conflicts with s32 = -1, so we document and test the convention:
        # sentinel (both 0xFFFF) → 0.
        self.assertEqual(_s32(0xFFFF, 0xFFFF), 0)

    def test_s32_positive(self):
        self.assertEqual(_s32(0, 500), 500)


if __name__ == '__main__':
    unittest.main()

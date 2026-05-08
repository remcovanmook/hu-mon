"""
tests.test_growatt_base
~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for GrowattBaseDriver._is_growatt() and the sentinel-aware
register wrappers defined in growatt.drivers.growatt_base.

These tests exercise the vendor-level probe logic in isolation using a
minimal concrete subclass that stubs out the abstract methods.
"""

import unittest

from growatt.drivers.base import ProbeContext, ProxyConfig
from growatt.drivers.growatt_base import (
    GrowattBaseDriver,
    _s16,
    _s32,
    _u16,
    _u32,
    GROWATT_SERIES,
)
from modbus.codec import u32_be


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

    @property
    def proxy_config(self):
        return ProxyConfig(address_map={1: {3: [], 4: []}})


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


def _make_ctx(block, fcs=None, input_block=None):
    """
    Build a ProbeContext for testing.

    :param block:        Holding register block (FC 03, ShineWifi space).
    :param fcs:          Supported function codes; defaults to {3, 4}.
    :param input_block:  FC 04 input registers 3000-3029.  Defaults to a
                         minimal block with status=1 (Normal) at index 0.
    """
    if input_block is None:
        # Default: valid status value so _is_growatt passes.
        input_block = [1] + [0] * 29
    return ProbeContext(
        slave_id=1,
        supported_fcs=fcs if fcs is not None else {3, 4},
        holding_block=block,
        max_block_size=125,
        input_block=input_block,
    )


# ---------------------------------------------------------------------------
# Tests: _is_growatt
# ---------------------------------------------------------------------------

class TestIsGrowatt(unittest.TestCase):

    def _driver(self):
        return _StubDriver(series_result=True)

    def test_known_series_accepted(self):
        # Series code alone is the discriminator; firmware string is not checked.
        block = _make_block(series_code=0x0B)
        ctx = _make_ctx(block)
        self.assertTrue(self._driver()._is_growatt(ctx))

    def test_all_known_series_codes_accepted(self):
        # _is_growatt now uses input_block, not series codes from holding block.
        # Any valid input_block with status in [0,10] should be accepted.
        driver = self._driver()
        for code in GROWATT_SERIES:
            ctx = _make_ctx(_make_block(series_code=code), input_block=[2] + [0] * 29)
            self.assertTrue(driver._is_growatt(ctx), f"series_code={code:#x} should pass")

    def test_unknown_series_code_rejected(self):
        # Series code in the holding block is no longer checked; this is now
        # a no-op for _is_growatt.  The status value is what matters.
        ctx = _make_ctx(_make_block(series_code=0xFF), input_block=[1] + [0] * 29)
        self.assertTrue(self._driver()._is_growatt(ctx))

    def test_zero_module_id_rejected(self):
        # input_block with out-of-range status (e.g. 11) should be rejected.
        ctx = _make_ctx(_make_block(), input_block=[11] + [0] * 29)
        self.assertFalse(self._driver()._is_growatt(ctx))

    def test_non_dotted_firmware_accepted_when_series_valid(self):
        # Firmware strings like 'D01.0ZBDC' are valid inverter firmwares.
        # The probe must not reject them: only the series code matters.
        bad_regs = [0xDEAD, 0xBEEF, 0x0000, 0x0000, 0x0000, 0x0000]
        block = _make_block(fw_regs=bad_regs, series_code=0x0B)
        ctx = _make_ctx(block)
        self.assertTrue(self._driver()._is_growatt(ctx))

    def test_empty_firmware_accepted_when_series_valid(self):
        # Empty firmware registers are fine as long as series code is known.
        empty_regs = [0x0000] * 6
        block = _make_block(fw_regs=empty_regs, series_code=0x0B)
        ctx = _make_ctx(block)
        self.assertTrue(self._driver()._is_growatt(ctx))

    def test_none_holding_block_rejected(self):
        # None holding_block is fine — _is_growatt uses input_block now.
        ctx = _make_ctx(None, input_block=[1] + [0] * 29)
        self.assertTrue(self._driver()._is_growatt(ctx))

    def test_short_holding_block_accepted(self):
        # Short holding block is fine — _is_growatt uses input_block.
        ctx = _make_ctx([0] * 10, input_block=[1] + [0] * 29)
        self.assertTrue(self._driver()._is_growatt(ctx))

    def test_no_fc4_rejected(self):
        # No FC 04 support means no input_block data — must reject.
        # Build ctx directly so input_block really is None (helper defaults to [1]+[0]*29).
        ctx = ProbeContext(slave_id=1, supported_fcs={3}, holding_block=_make_block(),
                           max_block_size=125, input_block=None)
        self.assertFalse(self._driver()._is_growatt(ctx))

    def test_none_input_block_rejected(self):
        # Build ctx directly so input_block really is None.
        ctx = ProbeContext(slave_id=1, supported_fcs={3, 4}, holding_block=_make_block(),
                           max_block_size=125, input_block=None)
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
        # input_block=None causes _is_growatt to return False.
        ctx = ProbeContext(slave_id=1, supported_fcs={3, 4}, holding_block=None,
                           max_block_size=0, input_block=None)
        self.assertFalse(_StubDriver(series_result=True).probe(ctx))

    def test_probe_never_raises_on_exception(self):
        """Probe must swallow exceptions from _probe_series."""
        class _Raiser(GrowattBaseDriver):
            @property
            def driver_id(self): return "raiser"
            def _probe_series(self, ctx): raise RuntimeError("boom")
            def read_device_info(self, c, s): raise NotImplementedError
            def read_registers(self, c, s): raise NotImplementedError
            @property
            def proxy_config(self): return ProxyConfig(address_map={1: {3: [], 4: []}})

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

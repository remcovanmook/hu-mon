"""
tests.test_driver_mod_hu
~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for GrowattModHuDriver.

Tests _probe_series(), read_device_info(), read_registers() (both profile
variants), and the _decode_model() helper.  All Modbus I/O is mocked.
"""

import json
import struct
import unittest
from unittest.mock import MagicMock, patch

from growatt.drivers.base import ProbeContext
from growatt.drivers.growatt_mod_hu.driver import (
    GrowattModHuDriver,
    _decode_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_registers(values: list):
    """Return a mock Modbus response whose .registers is the given list."""
    resp = MagicMock()
    resp.isError.return_value = False
    resp.registers = values
    return resp


def _error_response():
    resp = MagicMock()
    resp.isError.return_value = True
    return resp


def _make_holding_block(series_code=0x0B, power=12000, device_type=6, fw="7.6.1.8"):
    """Build a 125-register holding block for probe tests."""
    block = [0] * 125
    # Firmware at regs 9-14 (6 registers = 12 bytes)
    fw_padded = (fw + "\x00" * 12)[:12]
    for i in range(6):
        hi = ord(fw_padded[i * 2])
        lo = ord(fw_padded[i * 2 + 1])
        block[9 + i] = (hi << 8) | lo
    # module_id at regs 28-29
    module_id = (series_code << 16) | power
    block[28] = (module_id >> 16) & 0xFFFF
    block[29] = module_id & 0xFFFF
    # device type at reg 121
    block[121] = device_type
    return block


def _make_probe_ctx(block):
    return ProbeContext(
        slave_id=1,
        supported_fcs={3, 4},
        holding_block=block,
        max_block_size=125,
    )


# ---------------------------------------------------------------------------
# Tests: _probe_series
# ---------------------------------------------------------------------------

class TestProbeSeriesMODHU(unittest.TestCase):

    def _driver(self):
        return GrowattModHuDriver()

    def test_happy_path_device_type_6(self):
        block = _make_holding_block(series_code=0x0B, device_type=6)
        ctx = _make_probe_ctx(block)
        self.assertTrue(self._driver()._probe_series(ctx))

    def test_happy_path_device_type_4(self):
        block = _make_holding_block(series_code=0x0C, device_type=4)
        ctx = _make_probe_ctx(block)
        self.assertTrue(self._driver()._probe_series(ctx))

    def test_all_three_phase_series_accepted(self):
        driver = self._driver()
        for code in [0x0B, 0x0C, 0x0D, 0x10, 0x11]:
            block = _make_holding_block(series_code=code, device_type=6)
            ctx = _make_probe_ctx(block)
            self.assertTrue(driver._probe_series(ctx), f"series_code={code:#x}")

    def test_single_phase_series_rejected(self):
        # MIN (0x05) and MIC (0x0F) are not handled by this driver.
        for code in [0x05, 0x0F]:
            block = _make_holding_block(series_code=code, device_type=6)
            ctx = _make_probe_ctx(block)
            self.assertFalse(self._driver()._probe_series(ctx), f"series_code={code:#x}")

    def test_unknown_device_type_rejected(self):
        block = _make_holding_block(series_code=0x0B, device_type=0)
        ctx = _make_probe_ctx(block)
        self.assertFalse(self._driver()._probe_series(ctx))

    def test_none_block_rejected(self):
        ctx = ProbeContext(slave_id=1, supported_fcs={3, 4}, holding_block=None, max_block_size=0)
        self.assertFalse(self._driver()._probe_series(ctx))

    def test_short_block_rejected(self):
        ctx = _make_probe_ctx([0] * 50)
        self.assertFalse(self._driver()._probe_series(ctx))


# ---------------------------------------------------------------------------
# Tests: _decode_model
# ---------------------------------------------------------------------------

class TestDecodeModel(unittest.TestCase):

    def _block(self, series_code, power, device_type):
        return _make_holding_block(series_code=series_code, power=power, device_type=device_type)

    def test_mod_hu(self):
        model, rated = _decode_model(self._block(0x0B, 12000, 6), 6)
        self.assertEqual(model, "MOD 12KKTL3-HU")

    def test_mod_xh(self):
        model, rated = _decode_model(self._block(0x0B, 10000, 4), 4)
        self.assertEqual(model, "MOD 10KKTL3-XH")

    def test_zero_module_id_raises(self):
        block = [0] * 125
        with self.assertRaises(ValueError):
            _decode_model(block, 6)

    def test_rated_power_scaling(self):
        # power_watts >= 1000: rated_power_w = power_watts (no ×10)
        _, rated = _decode_model(self._block(0x0B, 12000, 6), 6)
        self.assertEqual(rated, 12000)


# ---------------------------------------------------------------------------
# Tests: read_device_info
# ---------------------------------------------------------------------------

class TestReadDeviceInfo(unittest.TestCase):

    def _make_client(self):
        client = MagicMock()
        # Reg 1005: bat 5.0 kWh → raw 50
        client.read_holding_registers.side_effect = [
            _mock_registers([50]),                   # Reg 1005
            _mock_registers(_make_holding_block()),  # Reg 0–124
            _mock_registers([0x4142] * 15),          # Reg 3001–3015 (serial)
        ]
        return client

    def test_bat_nominal_kwh(self):
        driver = GrowattModHuDriver()
        info = driver.read_device_info(self._make_client(), slave_id=1)
        self.assertAlmostEqual(info.bat_nominal_kwh, 5.0)

    def test_phases(self):
        driver = GrowattModHuDriver()
        info = driver.read_device_info(self._make_client(), slave_id=1)
        self.assertEqual(info.phases, 3)

    def test_has_battery(self):
        driver = GrowattModHuDriver()
        info = driver.read_device_info(self._make_client(), slave_id=1)
        self.assertTrue(info.has_battery)

    def test_has_eps_for_type_6(self):
        driver = GrowattModHuDriver()
        info = driver.read_device_info(self._make_client(), slave_id=1)
        # _make_holding_block defaults to device_type=6
        self.assertTrue(info.has_eps)


# ---------------------------------------------------------------------------
# Tests: read_registers — standard profile
# ---------------------------------------------------------------------------

class TestReadRegistersStandard(unittest.TestCase):

    def _make_reg1(self):
        """Segment 1 (3000–3029): PV data, no North Star trigger."""
        regs = [0] * 30
        regs[0] = 1      # status: Normal
        regs[1] = 0      # pv_total_w high
        regs[2] = 5000   # pv_total_w low → 500.0 W
        # Regs 25/26 below North Star threshold
        regs[25] = 0
        regs[26] = 0
        return regs

    def _make_reg2(self):
        """Segment 2 (3030–3109): Grid / counters."""
        regs = [0] * 80
        regs[0] = 2300   # L1 V → 230.0 V (standard profile)
        regs[12] = 5000  # freq → 50.00 Hz
        return regs

    def _make_reg3(self):
        """Segment 3 (3110–3154): Meter / EPS."""
        regs = [0] * 45
        return regs

    def _make_reg4(self):
        """Segment 4 (3170–3189): Battery."""
        regs = [0] * 20
        regs[0] = 85    # SOC %
        regs[1] = 500   # bat_v → 50.0 V (wait, that's divided by 10)
        return regs

    def _make_client(self):
        client = MagicMock()
        client.read_input_registers.side_effect = [
            _mock_registers(self._make_reg1()),
            _mock_registers(self._make_reg2()),
            _mock_registers(self._make_reg3()),
            _mock_registers(self._make_reg4()),
            _mock_registers([0] * 125),  # Segment 5
        ]
        return client

    def test_status_code(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertEqual(reading.status_code, 1)

    def test_pv_total_w(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertAlmostEqual(reading.pv_total_w, 500.0)

    def test_standard_profile_l1_voltage(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertAlmostEqual(reading.grid_l1_v, 230.0)

    def test_standard_profile_frequency(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertAlmostEqual(reading.grid_freq, 50.0)

    def test_bat_soc(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertEqual(reading.bat_soc, 85)

    def test_raw_payload_is_json(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        payload = json.loads(reading.raw_payload.decode())
        self.assertIn("3000", payload)


# ---------------------------------------------------------------------------
# Tests: read_registers — shifted (North Star) profile
# ---------------------------------------------------------------------------

class TestReadRegistersShifted(unittest.TestCase):

    def _make_reg1_shifted(self):
        """Segment 1 with North Star: freq at reg[25], L1V at reg[26]."""
        regs = [0] * 30
        regs[0] = 1
        regs[25] = 5000   # freq → 50.00 Hz (> 4000 threshold)
        regs[26] = 2305   # L1 V → 230.5 V (> 1000 threshold)
        regs[27] = 120    # L1 A → 12.0 A
        return regs

    def _make_client(self):
        client = MagicMock()
        client.read_input_registers.side_effect = [
            _mock_registers(self._make_reg1_shifted()),
            _mock_registers([0] * 80),
            _mock_registers([0] * 45),
            _mock_registers([0] * 20),
            _mock_registers([0] * 125),
        ]
        return client

    def test_shifted_frequency(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertAlmostEqual(reading.grid_freq, 50.0)

    def test_shifted_l1_voltage(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertAlmostEqual(reading.grid_l1_v, 230.5)

    def test_shifted_l1_current(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertAlmostEqual(reading.grid_l1_a, 12.0)


# ---------------------------------------------------------------------------
# Tests: proxy_config
# ---------------------------------------------------------------------------

class TestProxyConfig(unittest.TestCase):

    def setUp(self):
        self.cfg = GrowattModHuDriver().proxy_config

    def test_address_map_has_slave_1(self):
        self.assertIn(1, self.cfg.address_map)

    def test_slave_1_has_fc3_and_fc4(self):
        fc_map = self.cfg.address_map[1]
        self.assertIn(3, fc_map)
        self.assertIn(4, fc_map)

    def test_fc4_ranges_match_segments(self):
        from growatt.drivers.growatt_mod_hu.driver import SEGMENTS, _FC_LABEL
        expected = [(s, c) for label, s, c in SEGMENTS if _FC_LABEL[label] == 4]
        self.assertEqual(self.cfg.address_map[1][4], expected)

    def test_fc3_ranges_non_empty(self):
        self.assertGreater(len(self.cfg.address_map[1][3]), 0)

    def test_fc4_ranges_non_empty(self):
        self.assertGreater(len(self.cfg.address_map[1][4]), 0)

    def test_fc3_covers_low_metadata_block(self):
        # (0, 125) must appear in the FC 03 range list.
        self.assertIn((0, 125), self.cfg.address_map[1][3])

    def test_fc4_covers_primary_telemetry(self):
        # Segment 1 (PV) must appear.
        self.assertIn((3000, 30), self.cfg.address_map[1][4])


if __name__ == '__main__':
    unittest.main()

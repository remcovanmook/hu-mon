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

    def _make_client(self, bat_type=1):
        client = MagicMock()
        client.read_holding_registers.side_effect = [
            _mock_registers([bat_type]),             # Reg 1001: battery type
            _mock_registers([50]),                   # Reg 1005: bat 5.0 kWh
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

    def test_has_battery_when_type_register_nonzero(self):
        driver = GrowattModHuDriver()
        info = driver.read_device_info(self._make_client(bat_type=1), slave_id=1)
        self.assertTrue(info.has_battery)

    def test_no_battery_when_type_register_zero(self):
        driver = GrowattModHuDriver()
        info = driver.read_device_info(self._make_client(bat_type=0), slave_id=1)
        self.assertFalse(info.has_battery)

    def test_pv_strings_is_none(self):
        # No Protocol II register reports MPPT string count.
        driver = GrowattModHuDriver()
        info = driver.read_device_info(self._make_client(), slave_id=1)
        self.assertIsNone(info.pv_strings)

    def test_has_eps_for_type_6(self):
        driver = GrowattModHuDriver()
        info = driver.read_device_info(self._make_client(), slave_id=1)
        # _make_holding_block defaults to device_type=6
        self.assertTrue(info.has_eps)


# ---------------------------------------------------------------------------
# Tests: read_registers — standard profile
# ---------------------------------------------------------------------------

def _make_seg1(overrides=None):
    """
    Build a 125-register Segment 1 block (base 3000).

    :param overrides: dict of {index: value} to set after zero-fill.
    """
    regs = [0] * 125
    if overrides:
        for k, v in overrides.items():
            regs[k] = v
    return regs


def _make_seg2(overrides=None):
    """Build a 125-register Segment 2 block (base 3125)."""
    regs = [0] * 125
    if overrides:
        for k, v in overrides.items():
            regs[k] = v
    return regs


class TestReadRegistersStandard(unittest.TestCase):

    def _make_client(self, s1=None, s2=None):
        """
        Return a mock client that serves 3-segment reads.

        :param s1: dict of {index: value} overrides for Segment 1 (base 3000).
        :param s2: dict of {index: value} overrides for Segment 2 (base 3125).
        """
        client = MagicMock()
        client.read_input_registers.side_effect = [
            _mock_registers(_make_seg1(s1)),
            _mock_registers(_make_seg2(s2)),
            _mock_registers([0] * 125),   # Segment 3: low-block mirror
        ]
        return client

    def test_status_code(self):
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s1={0: 1}), 1)
        self.assertEqual(reading.status_code, 1)

    def test_pv_total_w(self):
        # 3001-3002 = s1[1]/s1[2]; raw 5000 in low word -> 500.0 W
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s1={1: 0, 2: 5000}), 1)
        self.assertAlmostEqual(reading.pv_total_w, 500.0)

    def test_standard_profile_l1_voltage(self):
        # Standard profile: Vac1 at s1[26] (3026); freq at s1[25] below threshold.
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s1={25: 0, 26: 2300}), 1)
        self.assertAlmostEqual(reading.grid_l1_v, 230.0)

    def test_standard_profile_frequency(self):
        # Standard profile: Fac at s1[42] (3042); raw 5000 -> 50.00 Hz.
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s1={25: 0, 42: 5000}), 1)
        self.assertAlmostEqual(reading.grid_freq, 50.0)

    def test_inverter_temp(self):
        # Temp2 at s1[94] (3094); raw 250 -> 25.0 C
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s1={94: 250}), 1)
        self.assertAlmostEqual(reading.inverter_temp, 25.0)

    def test_boost_temp(self):
        # Temp3 at s1[95] (3095); raw 300 -> 30.0 C
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s1={95: 300}), 1)
        self.assertAlmostEqual(reading.boost_temp, 30.0)

    def test_fault_code(self):
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s1={105: 7}), 1)
        self.assertEqual(reading.fault_code, 7)

    def test_pv_today_kwh(self):
        # 3049-3050 = s1[49]/s1[50]; raw 100 -> 10.0 kWh
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s1={49: 0, 50: 100}), 1)
        self.assertAlmostEqual(reading.pv_today_kwh, 10.0)

    def test_meter_total_w(self):
        # 3121-3122 = s1[121]/s1[122]; S32 raw 500 -> 50.0 W
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s1={121: 0, 122: 500}), 1)
        self.assertAlmostEqual(reading.meter_total_w, 50.0)

    def test_bat_discharge_today_kwh(self):
        # 3125-3126 = s2[0]/s2[1]; raw 200 -> 20.0 kWh
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s2={0: 0, 1: 200}), 1)
        self.assertAlmostEqual(reading.bat_discharge_today_kwh, 20.0)

    def test_bat_charge_today_kwh(self):
        # 3129-3130 = s2[4]/s2[5]; raw 150 -> 15.0 kWh
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s2={4: 0, 5: 150}), 1)
        self.assertAlmostEqual(reading.bat_charge_today_kwh, 15.0)

    def test_eps_l1_voltage(self):
        # EPSVac1 at s2[21] (3146); raw 2300 -> 230.0 V
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s2={21: 2300}), 1)
        self.assertAlmostEqual(reading.eps_l1_v, 230.0)

    def test_eps_total_power(self):
        # EPSPacTotal at s2[33]/s2[34] (3158-3159); raw 1000 -> 100.0 W
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s2={33: 0, 34: 1000}), 1)
        self.assertAlmostEqual(reading.eps_p, 100.0)

    def test_bat_soc(self):
        # SOC at s2[46] (3171)
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s2={46: 85}), 1)
        self.assertEqual(reading.bat_soc, 85)

    def test_bat_voltage(self):
        # Vbat at s2[44] (3169); scale 0.01 V; raw 5000 -> 50.00 V
        reading = GrowattModHuDriver().read_registers(
            self._make_client(s2={44: 5000}), 1)
        self.assertAlmostEqual(reading.bat_v, 50.0)

    def test_raw_payload_contains_all_segments(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        payload = json.loads(reading.raw_payload.decode())
        self.assertIn("3000", payload)
        self.assertIn("3125", payload)
        self.assertIn("0",    payload)


# ---------------------------------------------------------------------------
# Tests: read_registers — shifted (North Star) profile
# ---------------------------------------------------------------------------

class TestReadRegistersShifted(unittest.TestCase):

    def _make_client(self, extra_s1=None):
        s1 = {
            25: 5000,   # Fac -> 50.00 Hz  (> 4000 threshold)
            26: 2305,   # Vac1 -> 230.5 V  (> 1000 threshold)
            27: 120,    # Iac1 -> 12.0 A
            30: 2310,   # Vac2 -> 231.0 V
            31: 115,    # Iac2 -> 11.5 A
            34: 2295,   # Vac3 -> 229.5 V
            35: 118,    # Iac3 -> 11.8 A
        }
        if extra_s1:
            s1.update(extra_s1)
        client = MagicMock()
        client.read_input_registers.side_effect = [
            _mock_registers(_make_seg1(s1)),
            _mock_registers(_make_seg2()),
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

    def test_shifted_l2_voltage(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertAlmostEqual(reading.grid_l2_v, 231.0)

    def test_shifted_l3_voltage(self):
        reading = GrowattModHuDriver().read_registers(self._make_client(), 1)
        self.assertAlmostEqual(reading.grid_l3_v, 229.5)


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
        # Segment 1 now covers the full 3000-3124 block per spec.
        self.assertIn((3000, 125), self.cfg.address_map[1][4])


if __name__ == '__main__':
    unittest.main()

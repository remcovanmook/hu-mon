"""
tests.test_driver_vpp
~~~~~~~~~~~~~~~~~~~~~
Unit tests for GrowattVppDriver.
"""

import math
import unittest
from unittest.mock import MagicMock, patch

from growatt.drivers.base import ProbeContext
from growatt.drivers.growatt_vpp.driver import (
    GrowattVppDriver,
    _DtcEntry,
    _VPP_DTC_TABLE,
    _build_model_string,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(vpp_dtc=None, input_block=None):
    """Build a ProbeContext with enough state for VPP probe tests."""
    # input_block defaults to a valid Protocol II status (status=5 → in [0,10])
    if input_block is None:
        input_block = [5] + [0] * 29
    return ProbeContext(
        slave_id=1,
        supported_fcs={3, 4},
        holding_block=[0] * 125,
        max_block_size=64,
        input_block=input_block,
        vpp_dtc=vpp_dtc,
    )


def _mock_regs(values: list):
    """Return a mock Modbus response whose .registers equals values."""
    r = MagicMock()
    r.isError.return_value = False
    r.registers = values
    return r


def _error_response():
    r = MagicMock()
    r.isError.return_value = True
    return r


# ---------------------------------------------------------------------------
# _build_model_string
# ---------------------------------------------------------------------------

class TestBuildModelString(unittest.TestCase):

    def test_3phase_hu(self):
        entry = _DtcEntry("MOD", True, 3)
        self.assertEqual(_build_model_string(entry, 12000), "MOD 12KTL3-HU")

    def test_3phase_xh(self):
        entry = _DtcEntry("MOD", False, 3)
        self.assertEqual(_build_model_string(entry, 10000), "MOD 10KTL3-XH")

    def test_1phase(self):
        entry = _DtcEntry("SPH", False, 1)
        self.assertEqual(_build_model_string(entry, 5000), "SPH 5KTL-XH")

    def test_rounding(self):
        # 11993W → rounds to 12kW
        entry = _DtcEntry("MOD", True, 3)
        self.assertEqual(_build_model_string(entry, 11993), "MOD 12KTL3-HU")


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

class TestProbeSeriesVPP(unittest.TestCase):

    def setUp(self):
        self.driver = GrowattVppDriver()

    def test_known_dtc_accepted(self):
        ctx = _make_ctx(vpp_dtc=5401)
        self.assertTrue(self.driver._probe_series(ctx))

    def test_none_dtc_rejected(self):
        ctx = _make_ctx(vpp_dtc=None)
        self.assertFalse(self.driver._probe_series(ctx))

    def test_unknown_dtc_rejected(self):
        ctx = _make_ctx(vpp_dtc=9999)
        self.assertFalse(self.driver._probe_series(ctx))

    def test_all_known_dtcs_accepted(self):
        for dtc in _VPP_DTC_TABLE:
            with self.subTest(dtc=dtc):
                ctx = _make_ctx(vpp_dtc=dtc)
                self.assertTrue(self.driver._probe_series(ctx))


# ---------------------------------------------------------------------------
# read_device_info
# ---------------------------------------------------------------------------

class TestReadDeviceInfoVPP(unittest.TestCase):

    def _make_client(self, dtc=5401, rated_high=1, rated_low=54464,
                     serial_words=None, fw_words=None,
                     bat_type=1, bat_kwh=100):
        """Build a mock client wired to return fixture data."""
        if serial_words is None:
            # "TSS0F4L02N" padded to 15 words
            serial_words = [0x5453, 0x5330, 0x4634, 0x4C30, 0x324E] + [0] * 10
        if fw_words is None:
            fw_words = [0x444F, 0x3131, 0x2E30, 0x5A42, 0x4443, 0]

        # Build 18-register block: [dtc, ?, ...×14, rated_high, rated_low]
        block30000 = [dtc] + [0] * 15 + [rated_high, rated_low]

        client = MagicMock()

        def read_holding(addr, count, device_id):
            if addr == 30000:
                return _mock_regs(block30000[:count])
            if addr == 30001:
                return _mock_regs(serial_words[:count])
            if addr == 9:
                return _mock_regs(fw_words[:count])
            if addr == 1001:
                return _mock_regs([bat_type])
            if addr == 1005:
                return _mock_regs([bat_kwh])
            return _error_response()

        client.read_holding_registers.side_effect = read_holding
        return client

    def test_model_string(self):
        client = self._make_client(dtc=5401, rated_high=1, rated_low=54464)
        driver = GrowattVppDriver()
        info = driver.read_device_info(client, slave_id=1)
        # rated_w = ((1<<16)|54464)/10 = 120000/10 = 12000 → "MOD 12KTL3-HU"
        self.assertEqual(info.model, "MOD 12KTL3-HU")

    def test_rated_power(self):
        client = self._make_client(rated_high=1, rated_low=54464)
        driver = GrowattVppDriver()
        info = driver.read_device_info(client, slave_id=1)
        # 0x0001_D4C0 = 120000 raw units × 0.1W = 12000W
        self.assertEqual(info.rated_power_w, 12000)

    def test_has_eps_true_for_hu(self):
        client = self._make_client(dtc=5401)
        driver = GrowattVppDriver()
        info = driver.read_device_info(client, slave_id=1)
        self.assertTrue(info.has_eps)

    def test_has_eps_false_for_xh(self):
        client = self._make_client(dtc=5400)
        driver = GrowattVppDriver()
        info = driver.read_device_info(client, slave_id=1)
        self.assertFalse(info.has_eps)

    def test_has_battery_when_bat_type_nonzero(self):
        client = self._make_client(bat_type=1)
        driver = GrowattVppDriver()
        info = driver.read_device_info(client, slave_id=1)
        self.assertTrue(info.has_battery)

    def test_no_battery_when_bat_type_zero(self):
        client = self._make_client(bat_type=0)
        driver = GrowattVppDriver()
        info = driver.read_device_info(client, slave_id=1)
        self.assertFalse(info.has_battery)

    def test_all_errors_give_safe_defaults(self):
        client = MagicMock()
        client.read_holding_registers.return_value = _error_response()
        driver = GrowattVppDriver()
        info = driver.read_device_info(client, slave_id=1)
        self.assertEqual(info.model, "Unknown Growatt VPP")
        self.assertEqual(info.rated_power_w, 0)
        self.assertEqual(info.serial, "")


# ---------------------------------------------------------------------------
# read_registers
# ---------------------------------------------------------------------------

def _make_s1(status=5, fault=0, pv1_v=5285, pv1_a=17,
             pv2_v=5232, pv2_a=20, pv3_v=7204, pv3_a=17,
             pv4_v=0, pv4_a=0, pv_total_h=0, pv_total_l=32369):
    """Build a 60-element S1 register list (base 31000)."""
    s = [0] * 60
    s[0]  = status     # 31000
    s[5]  = fault      # 31005
    s[10] = pv1_v      # 31010
    s[11] = pv1_a      # 31011
    s[12] = pv2_v      # 31012
    s[13] = pv2_a      # 31013
    s[14] = pv3_v      # 31014
    s[15] = pv3_a      # 31015
    s[16] = pv4_v      # 31016
    s[17] = pv4_a      # 31017
    s[58] = pv_total_h  # 31058
    s[59] = pv_total_l  # 31059
    return s


def _make_s2(ac_active_h=0, ac_active_l=31894,
             ac_react_h=0, ac_react_l=276,
             freq=4997, v_ab=4283, v_bc=4279, v_ca=4299,
             i_a=43, i_b=43, i_c=44,
             meter_h=0, meter_l=0,
             temp=553,
             load_today_h=0, load_today_l=0,
             export_today_h=0, export_today_l=0):
    """Build a 26-element S2 register list (base 31100)."""
    s = [0] * 26
    s[0]  = ac_active_h   # 31100
    s[1]  = ac_active_l   # 31101
    s[2]  = ac_react_h    # 31102
    s[3]  = ac_react_l    # 31103
    s[5]  = freq           # 31105
    s[6]  = v_ab           # 31106
    s[7]  = v_bc           # 31107
    s[8]  = v_ca           # 31108
    s[9]  = i_a            # 31109
    s[10] = i_b            # 31110
    s[11] = i_c            # 31111
    s[12] = meter_h        # 31112
    s[13] = meter_l        # 31113
    s[14] = temp           # 31114
    s[18] = load_today_h   # 31118
    s[19] = load_today_l   # 31119
    s[22] = export_today_h # 31122
    s[23] = export_today_l # 31123
    return s


class TestReadRegistersVPP(unittest.TestCase):

    def _make_client(self, s1=None, s2=None, s3=None, s4=None, s5=None):
        s1 = s1 or _make_s1()
        s2 = s2 or _make_s2()

        client = MagicMock()

        def read_input(addr, count, device_id):
            if addr == 31000:
                return _mock_regs(s1)
            if addr == 31100:
                return _mock_regs(s2)
            if addr == 31200:
                return _mock_regs(s3) if s3 else _error_response()
            if addr == 3049:
                return _mock_regs(s4) if s4 else _error_response()
            if addr == 3130:
                return _mock_regs(s5) if s5 else _error_response()
            return _error_response()

        client.read_input_registers.side_effect = read_input
        return client

    def test_status_and_fault(self):
        driver = GrowattVppDriver()
        client = self._make_client(s1=_make_s1(status=5, fault=0))
        r = driver.read_registers(client, slave_id=1)
        self.assertEqual(r.status_code, 5)
        self.assertEqual(r.fault_code, 0)

    def test_pv_voltages_and_currents(self):
        driver = GrowattVppDriver()
        client = self._make_client()
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.pv1_v, 528.5)
        self.assertAlmostEqual(r.pv1_a, 1.7)

    def test_pv_string_power_is_v_times_i(self):
        """Per-string wattage must equal V × I (DC, no PF)."""
        driver = GrowattVppDriver()
        client = self._make_client()
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.pv1_w, r.pv1_v * r.pv1_a)
        self.assertAlmostEqual(r.pv2_w, r.pv2_v * r.pv2_a)

    def test_pv_total_w(self):
        driver = GrowattVppDriver()
        client = self._make_client(s1=_make_s1(pv_total_h=0, pv_total_l=32369))
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.pv_total_w, 3236.9)

    def test_grid_freq(self):
        driver = GrowattVppDriver()
        client = self._make_client(s2=_make_s2(freq=4997))
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.grid_freq, 49.97)

    def test_grid_voltages_ll(self):
        driver = GrowattVppDriver()
        client = self._make_client(s2=_make_s2(v_ab=4283, v_bc=4279, v_ca=4299))
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.grid_l1_v, 428.3)
        self.assertAlmostEqual(r.grid_l2_v, 427.9)
        self.assertAlmostEqual(r.grid_l3_v, 429.9)

    def test_inverter_temp(self):
        driver = GrowattVppDriver()
        client = self._make_client(s2=_make_s2(temp=553))
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.inverter_temp, 55.3)

    def test_meter_total_w_sign_inversion(self):
        """VPP meter_power pos=import; GrowattReading meter_total_w pos=export."""
        driver = GrowattVppDriver()
        # meter_h=0, meter_l=1000 → raw = +1000 (import) → stored as -100.0W
        client = self._make_client(s2=_make_s2(meter_h=0, meter_l=1000))
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.meter_total_w, -100.0)

    def test_per_phase_ac_power(self):
        """meter_l1_w should equal (V_AB/√3) × I_A × PF."""
        driver = GrowattVppDriver()
        s2 = _make_s2(
            ac_active_h=0, ac_active_l=31894,
            ac_react_h=0, ac_react_l=276,
            v_ab=4283, i_a=43,
        )
        client = self._make_client(s2=s2)
        r = driver.read_registers(client, slave_id=1)
        active_w = 3189.4
        reactive_var = 27.6
        pf = active_w / math.sqrt(active_w ** 2 + reactive_var ** 2)
        expected = (428.3 / math.sqrt(3)) * 4.3 * pf
        self.assertAlmostEqual(r.meter_l1_w, expected, places=1)

    def test_battery_skipped_when_all_zero(self):
        driver = GrowattVppDriver()
        s3 = [0] * 30
        client = self._make_client(s3=s3)
        r = driver.read_registers(client, slave_id=1)
        self.assertEqual(r.bat_soc, 0.0)
        self.assertEqual(r.bat_v, 0.0)

    def test_battery_populated_when_nonzero(self):
        driver = GrowattVppDriver()
        s3 = [0] * 30
        s3[0]  = 0       # bat_p high
        s3[1]  = 500     # bat_p low → 50.0W charging
        s3[14] = 512     # bat_v → 51.2V
        s3[17] = 80      # bat_soc → 80%
        client = self._make_client(s3=s3)
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.bat_p, 50.0)
        self.assertAlmostEqual(r.bat_v, 51.2)
        self.assertEqual(r.bat_soc, 80)

    def test_pv_energy_from_s4(self):
        driver = GrowattVppDriver()
        s4 = [0] * 47
        s4[0] = 0;  s4[1] = 250   # pv_today → 25.0 kWh
        s4[2] = 0;  s4[3] = 5000  # pv_total → 500.0 kWh
        s4[46] = 452               # boost_temp → 45.2°C
        client = self._make_client(s4=s4)
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.pv_today_kwh, 25.0)
        self.assertAlmostEqual(r.pv_total_kwh, 500.0)
        self.assertAlmostEqual(r.boost_temp, 45.2)

    def test_eps_populated_when_has_eps(self):
        driver = GrowattVppDriver()
        driver._has_eps = True
        s5 = [0] * 30
        s5[0] = 2300   # eps_l1_v → 230.0V
        s5[1] = 50     # eps_l1_a → 5.0A
        s5[28] = 0
        s5[29] = 11500  # eps_p → 1150.0W
        client = self._make_client(s5=s5)
        r = driver.read_registers(client, slave_id=1)
        self.assertAlmostEqual(r.eps_l1_v, 230.0)
        self.assertAlmostEqual(r.eps_l1_a, 5.0)
        self.assertAlmostEqual(r.eps_p, 1150.0)

    def test_eps_skipped_when_no_eps(self):
        driver = GrowattVppDriver()
        driver._has_eps = False
        s5 = [2300, 50] + [0] * 28
        client = self._make_client(s5=s5)
        r = driver.read_registers(client, slave_id=1)
        self.assertEqual(r.eps_l1_v, 0.0)


if __name__ == "__main__":
    unittest.main()

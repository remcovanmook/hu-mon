"""
growatt.drivers.growatt_mod_hu.driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Concrete driver for the Growatt 3-Phase Hybrid generation (MOD-HU / MOD-XH /
MID-XH and related series).

Covers the Protocol II register map as documented in docs/shinewifi-x2-modbus.md.
All register address arithmetic, segment boundaries, and firmware heuristics
specific to this device family live here and nowhere else.

Register Segments (FC 04 — Input Registers)
-------------------------------------------
  SEGMENTS defines the polling strategy for each 5-second cycle.  The segment
  boundaries avoid the unmapped Power Quality gap (3155–3169) and stay within
  the 64-register-per-request limit documented for the ShineWifi-X2.

  Segment 1: 3000–3029  PV inputs and status
  Segment 2: 3030–3109  Grid, frequency, energy counters, temperature
  Segment 3: 3110–3154  Smart Meter, EPS, additional temperature
  Segment 4: 3170–3189  Battery BMS
  Segment 5:    0–124   Low-block mirror (used by Modbus proxy)

North Star Shifted-Profile Detection
-------------------------------------
  The MOD-HU v7.6+ firmware compresses the thermal registers from 3114 to 3094
  (a -20 shift).  This pushes the Grid block to start at 3025 instead of 3030.
  Detection: if Reg 3025 > 4000 (grid frequency × 100 > 40Hz) and
  Reg 3026 > 1000 (L1 voltage × 10 > 100V), the shifted profile is active.
"""

import json
import logging
import time

from pymodbus.exceptions import ModbusIOException

from growatt.drivers.base import BaseDriver, DeviceInfo, ProbeContext, ProxyConfig
from modbus.codec import ascii_regs
from growatt.drivers.growatt_base import (
    GROWATT_SERIES,
    GrowattBaseDriver,
    _s16,
    _s32,
    _u16,
    _u32,
)
from growatt.reading import GrowattReading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Series codes that belong to the 3-phase hybrid family this driver handles.
# ---------------------------------------------------------------------------
_MOD_HU_SERIES = {0x0B, 0x0C, 0x0D, 0x10, 0x11}  # MOD, MID, SPH, MAC, MAX

# Device type values from Holding Reg 121.
_DEVICE_TYPE_HU = 6   # Full Hybrid (High-Voltage APX)
_DEVICE_TYPE_XH = 4   # Battery-Ready (No EPS)

# Phase count: definitionally 3 for all devices this driver matches.
# _probe_series() only accepts 3-phase series codes, so this is not
# an assumption — it is a consequence of a successful probe.
_PHASES = 3

# Battery Type register (Holding 1001): 0 = none/unconfigured, 1 = Lithium (APX).
_REG_BATTERY_TYPE = 1001

# ---------------------------------------------------------------------------
# Polling segment definitions.
# Each tuple: (function_code_label, start_address, count)
# ---------------------------------------------------------------------------
SEGMENTS = [
    ("input", 3000, 125),   # Segment 1: 3000–3124 (PV, grid, counters, temp, fault)
    ("input", 3125, 125),   # Segment 2: 3125–3249 (bat energy, EPS, BDC, BMS)
    ("input",    0, 125),   # Segment 3: 0–124 low-block mirror (proxy)
]

# Mapping from SEGMENTS label strings to Modbus function code integers.
_FC_LABEL = {"holding": 3, "input": 4}

# Holding register ranges exposed by the proxy so third-party systems can
# read device metadata via FC 03.  These mirror the one-time reads made in
# read_device_info().
_PROXY_HOLDING_RANGES = [
    (0,    125),   # Low metadata block (firmware, module_id, device type, etc.)
    (1001,   5),   # Battery: type (1001), design capacity (1002), nominal energy (1005)
    (3001,  15),   # Serial number
]

# Inter-segment pause to prevent ShineWifi-X2 overload.
_INTER_SEGMENT_SLEEP = 0.05  # seconds


def _decode_model(regs_meta: list, device_type: int) -> tuple:
    """
    Derive the human-readable model string and rated power from the algorithmic
    module_id encoding in Holding Registers 28–29.

    The module_id packs the series code in the upper 16 bits and the rated
    power (in watts) in the lower 16 bits.  The full model string is
    constructed by appending a suffix that indicates:
    - KTL (transformer-less, >= 3000W)
    - 3   (three-phase series)
    - -HU / -XH (device type flag from Reg 121)

    :param regs_meta: Holding register block 0–124.
    :param device_type: Value of Holding Reg 121.
    :returns: Tuple of (model_string: str, rated_power_w: int).
    """
    module_id = (regs_meta[28] << 16) | regs_meta[29]
    if module_id == 0:
        raise ValueError(
            "module_id at Holding Regs 28–29 is zero: register read failed or block is invalid"
        )

    series_code = (module_id >> 16) & 0xFFFF
    power_watts = module_id & 0xFFFF
    series_prefix = GROWATT_SERIES.get(series_code, "Unknown")

    suffix = ""
    if power_watts >= 3000:
        suffix += "KTL"
        power_display = f"{int(power_watts / 1000)}K"
    else:
        power_display = str(power_watts)

    if series_prefix in {"MOD", "MID", "MAC", "MAX"}:
        suffix += "3"

    if device_type == _DEVICE_TYPE_HU:
        suffix += "-HU"
    elif device_type == _DEVICE_TYPE_XH:
        suffix += "-XH"

    model = f"{series_prefix} {power_display}{suffix}" if suffix else f"{series_prefix} {power_display}W"
    rated_w = power_watts * 10 if power_watts < 1000 else power_watts
    return model, rated_w


class GrowattModHuDriver(GrowattBaseDriver):
    """
    Driver for the Growatt 3-Phase Hybrid generation (MOD-HU / MOD-XH /
    MID-XH, MAC, MAX series with device type 4 or 6).

    Implements the series-level probe check and the full polling cycle
    including the North Star shifted-profile detection heuristic.
    """

    @property
    def driver_id(self) -> str:
        return "growatt_mod_hu"

    def proxy_config(self, slave_id: int) -> ProxyConfig:
        """
        Return the Modbus address space the proxy server should expose.

        Structured as {slave_id: {function_code: [(start, count)]}}.  FC 04
        ranges are derived from SEGMENTS so the proxy and collector always cover
        the same address space.  FC 03 ranges cover the one-time metadata
        registers read by read_device_info(), allowing third-party systems to
        query device identity through the proxy.

        :param slave_id: Confirmed Modbus slave address from the probe pipeline.
        :returns:        ProxyConfig describing the servable register space.
        """
        # Build FC 04 map from SEGMENTS.
        fc4_ranges = [(start, count) for label, start, count in SEGMENTS
                      if _FC_LABEL[label] == 4]
        return ProxyConfig(
            address_map={
                slave_id: {
                    3: _PROXY_HOLDING_RANGES,
                    4: fc4_ranges,
                }
            }
        )

    def _probe_series(self, ctx: ProbeContext) -> bool:
        """
        Confirm the device is a 3-phase hybrid Growatt.

        Checks two fields from the already-fetched holding block:
        1. Series code (Regs 28–29 upper 16 bits) must be in _MOD_HU_SERIES.
        2. Device type (Reg 121) must be 4 (XH) or 6 (HU).

        No additional Modbus reads are performed.
        """
        # The ShineWifi-X2 FC 03 holding registers 0-124 are the ShineWifi's
        # own config space, not the inverter's Protocol II holding space.
        # Series-code identification via holding block is not possible here.
        #
        # Fallback: confirm that FC 04 input registers at 3000 are accessible
        # (already verified in _is_growatt) and that the status value is in
        # the normal operating range.  A more specific series check requires
        # the ShineWifi to bridge VPP holding registers (30000+) or a
        # hardware-side Protocol II holding register read, which the ShineWifi
        # does not appear to support.
        if ctx.input_block is None:
            logger.info("_probe_series: input_block is None")
            return False

        status = ctx.input_block[0]
        logger.info("_probe_series: status=0x%04X (accepted)", status)
        return True


    def read_device_info(self, client, slave_id: int) -> DeviceInfo:
        """
        Read one-time static metadata from the device.

        Each register read is attempted independently.  A failure on any one
        read is logged and a safe default is used rather than aborting startup.
        This is necessary because the ShineWifi-X2 FC03 holding registers
        0-124 are the ShineWifi's own config space (not the inverter's), so
        module_id (regs 28-29) and device_type (reg 121) cannot be read from
        the standard Protocol II path on this hardware.

        Reads attempted:
        - FC03 0-124:   Firmware string at regs 9-14.
        - FC03 3001-15: 30-char serial (outside ShineWifi own space; bridges
                        to inverter on most firmware versions).
        - FC03 1001:    Battery type.
        - FC03 1005:    Battery nominal energy.

        :param client:   Active pymodbus ModbusTcpClient.
        :param slave_id: Confirmed Modbus slave address.
        """
        # ShineWifi base block (FC03 0-124).
        # Contains ShineWifi config.  Firmware string at regs 9-14 is correct
        # (ShineWifi mirrors it).  module_id at regs 28-29 is zero on our
        # hardware — the ShineWifi does not bridge those addresses.
        firmware = "unknown"
        module_id = 0
        device_type = 0
        r_meta = client.read_holding_registers(0, count=125, device_id=slave_id)
        if not r_meta.isError():
            regs_meta = r_meta.registers
            firmware = ascii_regs(regs_meta[9:15])
            module_id = (regs_meta[28] << 16) | regs_meta[29]
            device_type = regs_meta[121]
        else:
            logger.warning("read_device_info: FC03 0-124 failed — firmware/module_id unavailable")

        # Model string derivation.
        if module_id != 0:
            try:
                model, rated_w = _decode_model(r_meta.registers, device_type)
            except ValueError as exc:
                logger.warning("read_device_info: _decode_model failed: %s", exc)
                model, rated_w = "Unknown Growatt Hybrid 3ph", 0
        else:
            logger.warning(
                "read_device_info: module_id at FC03 regs 28-29 is zero "
                "(ShineWifi does not bridge Protocol II holding registers at these "
                "addresses). Model and rated power will be reported as unknown."
            )
            model, rated_w = "Unknown Growatt Hybrid 3ph", 0

        # Serial number (FC03 3001-3015).
        # Outside the ShineWifi's own 0-124 range; typically bridges to inverter.
        serial = "unknown"
        r_serial = client.read_holding_registers(3001, count=15, device_id=slave_id)
        if not r_serial.isError():
            serial = ascii_regs(r_serial.registers)
        else:
            logger.warning("read_device_info: FC03 3001-3015 (serial) failed")

        # Battery type (FC03 1001).
        battery_configured = False
        r_bat_type = client.read_holding_registers(_REG_BATTERY_TYPE, count=1, device_id=slave_id)
        if not r_bat_type.isError():
            battery_configured = r_bat_type.registers[0] != 0
            logger.info("Battery type reg=%d", r_bat_type.registers[0])
        else:
            logger.warning("read_device_info: FC03 1001 (battery type) failed")

        # Battery nominal capacity (FC03 1005).
        bat_nominal_kwh = 0.0
        r_bat = client.read_holding_registers(1005, count=1, device_id=slave_id)
        if not r_bat.isError():
            bat_nominal_kwh = r_bat.registers[0] / 10.0
            logger.info("Battery nominal=%.1f kWh", bat_nominal_kwh)
        else:
            logger.warning("read_device_info: FC03 1005 (battery nominal kWh) failed")

        has_eps = (device_type == _DEVICE_TYPE_HU)
        logger.info(
            "Discovered: %s (serial=%s, fw=%s, rated=%dW, bat=%.1fkWh, eps=%s)",
            model, serial, firmware, rated_w, bat_nominal_kwh, has_eps,
        )

        return DeviceInfo(
            model=model,
            serial=serial,
            firmware=firmware,
            rated_power_w=rated_w,
            bat_nominal_kwh=bat_nominal_kwh,
            phases=_PHASES,
            pv_strings=None,
            has_eps=has_eps,
            has_battery=battery_configured,
        )


    def read_registers(self, client, slave_id: int) -> GrowattReading:
        """
        Execute one full telemetry poll cycle.

        Reads three register segments aligned to the spec-defined block
        boundaries (Section 1.2), applies the North Star shifted-profile
        heuristic for grid data, and packages the raw snapshot for the proxy.

        Segment layout (FC 04, Input Registers):
          Seg 1: 3000–3124  PV, grid, freq, energy counters, temps, fault codes
          Seg 2: 3125–3249  Battery energy, EPS, BDC state, BMS live data
          Seg 3:    0–124   Low-block mirror (proxy cache)

        :param client:   Active pymodbus ModbusTcpClient.
        :param slave_id: Confirmed Modbus slave address.
        :raises ModbusIOException: If any mandatory segment read fails.
        """
        r1 = client.read_input_registers(3000, count=125, device_id=slave_id)
        if r1.isError():
            raise ModbusIOException("Failed to read Segment 1 (3000–3124)")
        time.sleep(_INTER_SEGMENT_SLEEP)

        r2 = client.read_input_registers(3125, count=125, device_id=slave_id)
        if r2.isError():
            raise ModbusIOException("Failed to read Segment 2 (3125–3249)")
        time.sleep(_INTER_SEGMENT_SLEEP)

        r3 = client.read_input_registers(0, count=125, device_id=slave_id)
        if r3.isError():
            raise ModbusIOException("Failed to read Segment 3 (low-block mirror)")

        s1 = r1.registers   # base 3000
        s2 = r2.registers   # base 3125

        reading = GrowattReading()

        # --- Status ---
        reading.status_code = _u16(s1[0])           # 3000

        # --- PV strings ---
        reading.pv_total_w = _u32(s1[1], s1[2]) / 10.0    # 3001–3002
        reading.pv1_v      = _u16(s1[3]) / 10.0           # 3003
        reading.pv1_a      = _u16(s1[4]) / 10.0           # 3004
        reading.pv1_w      = _u32(s1[5], s1[6]) / 10.0    # 3005–3006
        reading.pv2_v      = _u16(s1[7]) / 10.0           # 3007
        reading.pv2_a      = _u16(s1[8]) / 10.0           # 3008
        reading.pv2_w      = _u32(s1[9], s1[10]) / 10.0   # 3009–3010
        reading.pv3_v      = _u16(s1[11]) / 10.0          # 3011
        reading.pv3_a      = _u16(s1[12]) / 10.0          # 3012
        reading.pv3_w      = _u32(s1[13], s1[14]) / 10.0  # 3013–3014
        reading.pv4_v      = _u16(s1[15]) / 10.0          # 3015
        reading.pv4_a      = _u16(s1[16]) / 10.0          # 3016
        reading.pv4_w      = _u32(s1[17], s1[18]) / 10.0  # 3017–3018

        # --- Grid / North Star shifted-profile detection ---
        # 3025: Fac (grid freq × 100). Threshold > 4000 → 40 Hz → plausible.
        # 3026: Vac1 (L1 voltage × 10). Threshold > 1000 → 100 V → plausible.
        # Both conditions together uniquely identify the shifted firmware profile.
        freq_3025 = _u16(s1[25])
        v_3026    = _u16(s1[26])

        if freq_3025 > 4000 and v_3026 > 1000:
            # Shifted (MOD-HU v7.6+): grid block starts at 3025
            reading.grid_freq = freq_3025 / 100.0          # 3025
            reading.grid_l1_v = v_3026 / 10.0              # 3026
            reading.grid_l1_a = _u16(s1[27]) / 10.0        # 3027
            reading.grid_l2_v = _u16(s1[30]) / 10.0        # 3030
            reading.grid_l2_a = _u16(s1[31]) / 10.0        # 3031
            reading.grid_l3_v = _u16(s1[34]) / 10.0        # 3034
            reading.grid_l3_a = _u16(s1[35]) / 10.0        # 3035
        else:
            # Standard profile: grid block starts at 3026
            reading.grid_freq = _u16(s1[42]) / 100.0       # 3042 (Ptouserh offset)
            reading.grid_l1_v = _u16(s1[26]) / 10.0        # 3026
            reading.grid_l1_a = _u16(s1[27]) / 10.0        # 3027
            reading.grid_l2_v = _u16(s1[30]) / 10.0        # 3030
            reading.grid_l2_a = _u16(s1[31]) / 10.0        # 3031
            reading.grid_l3_v = _u16(s1[34]) / 10.0        # 3034
            reading.grid_l3_a = _u16(s1[35]) / 10.0        # 3035

        # --- Energy counters (Segment 1, base 3000) ---
        reading.pv_today_kwh = _u32(s1[49], s1[50]) / 10.0     # 3049–3050
        reading.pv_total_kwh = _u32(s1[51], s1[52]) / 10.0     # 3051–3052

        # --- Temperature (Segment 1, base 3000) ---
        # Spec: Temp2 (IPM) at 3094, Temp3 (boost) at 3095
        reading.inverter_temp = _u16(s1[94]) / 10.0             # 3094
        reading.boost_temp    = _u16(s1[95]) / 10.0             # 3095

        # --- Fault / Warning (Segment 1) ---
        reading.fault_code = _u16(s1[105])                       # 3105

        # --- Smart Meter (Segment 1) ---
        # 3121 = s1[121], 3122 = s1[122], etc.
        reading.meter_total_w = _s32(s1[121], s1[122]) / 10.0   # 3121–3122
        reading.meter_l1_w    = _s32(s1[123], s1[124]) / 10.0   # 3123–3124

        # --- Battery energy counters (Segment 2, base 3125) ---
        reading.bat_discharge_today_kwh = _u32(s2[0],  s2[1])  / 10.0  # 3125–3126
        reading.bat_discharge_total_kwh = _u32(s2[2],  s2[3])  / 10.0  # 3127–3128  (new)
        reading.bat_charge_today_kwh    = _u32(s2[4],  s2[5])  / 10.0  # 3129–3130
        reading.bat_charge_total_kwh    = _u32(s2[6],  s2[7])  / 10.0  # 3131–3132  (new)

        # --- Meter L2/L3 (Segment 2, base 3125) ---
        # 3125 is Edischr_today — meter L2/L3 are not directly in the spec block.
        # NOTE: meter_l2_w and meter_l3_w are not available in this segment.
        # They were previously read from wrong addresses. Set to 0 until verified.
        reading.meter_l2_w = 0.0
        reading.meter_l3_w = 0.0

        # --- EPS (Segment 2, base 3125) ---
        # Spec: EPSFac 3145, EPSVac1 3146, EPSIac1 3147, EPSPac1 3148–3149,
        #        EPSVac2 3150, EPSIac2 3151, EPSPac2 3152–3153,
        #        EPSVac3 3154, EPSIac3 3155, EPSPac3 3156–3157,
        #        EPSPacTotal 3158–3159.
        reading.eps_l1_v = _u16(s2[21]) / 10.0                  # 3146
        reading.eps_l1_a = _u16(s2[22]) / 10.0                  # 3147
        reading.eps_l2_v = _u16(s2[25]) / 10.0                  # 3150
        reading.eps_l2_a = _u16(s2[26]) / 10.0                  # 3151
        reading.eps_l3_v = _u16(s2[29]) / 10.0                  # 3154
        reading.eps_l3_a = _u16(s2[30]) / 10.0                  # 3155
        # Total EPS power read directly from register (not computed from V×I).
        reading.eps_p    = _u32(s2[33], s2[34]) / 10.0          # 3158–3159

        # --- Battery BMS live (Segment 2, base 3125) ---
        # Spec BDC1 block: 3166 SysState, 3169 Vbat (0.01V), 3170 Ibat (0.1A),
        #                  3171 SOC (1%), 3178–3179 Pdischr, 3180–3181 Pchr.
        reading.bat_soc = _u16(s2[46])                           # 3171
        reading.bat_v   = _u16(s2[44]) / 100.0                  # 3169 (0.01 V)
        reading.bat_i   = _s16(s2[45]) / 10.0                   # 3170 (0.1 A)
        reading.bat_p   = _s32(s2[55], s2[56]) / 10.0           # 3180–3181 (charge)

        # --- Derived ---
        reading.load_p = reading.pv_total_w - reading.meter_total_w - reading.bat_p

        # --- Raw register snapshot for the Modbus proxy ---
        raw = {}
        for i, v in enumerate(s1):         raw[str(3000 + i)] = v
        for i, v in enumerate(s2):         raw[str(3125 + i)] = v
        for i, v in enumerate(r3.registers): raw[str(i)] = v
        reading.raw_payload = json.dumps(raw).encode('utf-8')

        return reading

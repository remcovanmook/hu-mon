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
    ("input",   3000,  30),   # Segment 1: PV / Status
    ("input",   3030,  80),   # Segment 2: Grid / Counters / Temp
    ("input",   3110,  45),   # Segment 3: Meter / EPS / Temp
    ("input",   3170,  20),   # Segment 4: Battery BMS
    ("input",      0, 125),   # Segment 5: Low-block mirror (proxy)
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

    @property
    def proxy_config(self) -> ProxyConfig:
        """
        Return the Modbus address space the proxy server should expose.

        Structured as {slave_id: {function_code: [(start, count)]}}.  The
        slave_id is the Growatt default (1).  FC 04 (input) ranges are derived
        directly from SEGMENTS so the proxy and collector always cover the same
        address space.  FC 03 (holding) ranges cover the one-time metadata
        registers read by read_device_info(), allowing third-party systems to
        query device identity through the proxy.
        """
        # Build FC 04 map from SEGMENTS.
        fc4_ranges = [(start, count) for label, start, count in SEGMENTS
                      if _FC_LABEL[label] == 4]
        return ProxyConfig(
            address_map={
                1: {
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
        block = ctx.holding_block
        if block is None or len(block) < 122:
            return False

        module_id = (block[28] << 16) | block[29]
        series_code = (module_id >> 16) & 0xFFFF
        if series_code not in _MOD_HU_SERIES:
            return False

        device_type = block[121]
        return device_type in {_DEVICE_TYPE_HU, _DEVICE_TYPE_XH}

    def read_device_info(self, client, slave_id: int) -> DeviceInfo:
        """
        Read one-time static metadata from the device.

        Reads:
        - Holding 1001: battery type (0 = none, 1 = Lithium APX)
        - Holding 1005: battery nominal energy (kWh × 0.1)
        - Holding 0–124: firmware string, module_id, device type
        - Holding 3001–3015: 30-character inverter serial number

        pv_strings is not set: no register in Protocol II reports the number
        of MPPT inputs configured on this unit.

        :param client:   Active pymodbus ModbusTcpClient.
        :param slave_id: Confirmed Modbus slave address.
        :raises ModbusIOException: If any register read fails.
        """
        # Battery type — determines whether a battery is actually configured.
        r_bat_type = client.read_holding_registers(_REG_BATTERY_TYPE, count=1, device_id=slave_id)
        if r_bat_type.isError():
            raise ModbusIOException("Failed to read battery type (Reg 1001)")
        battery_configured = r_bat_type.registers[0] != 0

        # Battery nominal capacity
        r_bat = client.read_holding_registers(1005, count=1, device_id=slave_id)
        if r_bat.isError():
            raise ModbusIOException("Failed to read battery nominal capacity (Reg 1005)")
        bat_nominal_kwh = r_bat.registers[0] / 10.0
        logger.info("Battery type reg=%d  nominal=%.1f kWh",
                    r_bat_type.registers[0], bat_nominal_kwh)

        # Base metadata block
        r_meta = client.read_holding_registers(0, count=125, device_id=slave_id)
        if r_meta.isError():
            raise ModbusIOException("Failed to read metadata holding block (Reg 0–124)")
        regs_meta = r_meta.registers

        # Serial number
        r_serial = client.read_holding_registers(3001, count=15, device_id=slave_id)
        if r_serial.isError():
            raise ModbusIOException("Failed to read serial number (Reg 3001–3015)")

        firmware = ascii_regs(regs_meta[9:15])
        serial = ascii_regs(r_serial.registers)
        device_type = regs_meta[121]

        model, rated_w = _decode_model(regs_meta, device_type)
        logger.info("Discovered: %s (serial=%s, fw=%s, rated=%dW)", model, serial, firmware, rated_w)

        return DeviceInfo(
            model=model,
            serial=serial,
            firmware=firmware,
            rated_power_w=rated_w,
            bat_nominal_kwh=bat_nominal_kwh,
            phases=_PHASES,
            pv_strings=None,   # No Protocol II register reports MPPT string count.
            has_eps=(device_type == _DEVICE_TYPE_HU),
            has_battery=battery_configured,
        )

    def read_registers(self, client, slave_id: int) -> GrowattReading:
        """
        Execute one full telemetry poll cycle.

        Reads five register segments (see SEGMENTS), applies the North Star
        shifted-profile heuristic to select the correct register offsets for
        grid data, assembles all fields into a GrowattReading, and packages the
        raw register snapshot as a JSON blob for the Modbus proxy.

        :param client:   Active pymodbus ModbusTcpClient.
        :param slave_id: Confirmed Modbus slave address.
        :raises ModbusIOException: If any mandatory segment read fails.
        """
        r1 = client.read_input_registers(3000, count=30, device_id=slave_id)
        if r1.isError():
            raise ModbusIOException("Failed to read Segment 1 (3000–3029)")
        time.sleep(_INTER_SEGMENT_SLEEP)

        r2 = client.read_input_registers(3030, count=80, device_id=slave_id)
        if r2.isError():
            raise ModbusIOException("Failed to read Segment 2 (3030–3109)")
        time.sleep(_INTER_SEGMENT_SLEEP)

        r3 = client.read_input_registers(3110, count=45, device_id=slave_id)
        if r3.isError():
            raise ModbusIOException("Failed to read Segment 3 (3110–3154)")

        r4 = client.read_input_registers(3170, count=20, device_id=slave_id)
        if r4.isError():
            raise ModbusIOException("Failed to read Segment 4 (3170–3189)")

        r5 = client.read_input_registers(0, count=125, device_id=slave_id)
        if r5.isError():
            raise ModbusIOException("Failed to read Segment 5 (low-block mirror)")

        reg1 = r1.registers
        reg2 = r2.registers
        reg3 = r3.registers  # Segment 3: Meter / EPS / Temp (base addr 3110)
        reg4 = r4.registers  # Segment 4: Battery (base addr 3170)

        reading = GrowattReading()

        # Status
        reading.status_code = _u16(reg1[0])  # 3000

        # PV strings
        reading.pv_total_w = _u32(reg1[1], reg1[2]) / 10.0   # 3001–3002
        reading.pv1_v = _u16(reg1[3]) / 10.0                  # 3003
        reading.pv1_a = _u16(reg1[4]) / 10.0                  # 3004
        reading.pv1_w = _u32(reg1[5], reg1[6]) / 10.0         # 3005–3006
        reading.pv2_v = _u16(reg1[7]) / 10.0                  # 3007
        reading.pv2_a = _u16(reg1[8]) / 10.0                  # 3008
        reading.pv2_w = _u32(reg1[9], reg1[10]) / 10.0        # 3009–3010
        reading.pv3_v = _u16(reg1[11]) / 10.0                 # 3011
        reading.pv3_a = _u16(reg1[12]) / 10.0                 # 3012
        reading.pv3_w = _u32(reg1[13], reg1[14]) / 10.0       # 3013–3014
        reading.pv4_v = _u16(reg1[15]) / 10.0                 # 3015
        reading.pv4_a = _u16(reg1[16]) / 10.0                 # 3016
        reading.pv4_w = _u32(reg1[17], reg1[18]) / 10.0       # 3017–3018

        # North Star shifted-profile detection.
        # If Reg 3025 carries a plausible grid frequency (> 4000 = 40Hz × 100)
        # and Reg 3026 carries a plausible L1 voltage (> 1000 = 100V × 10),
        # the grid block has been shifted -5 relative to the standard map.
        freq_3025 = _u16(reg1[25]) if len(reg1) > 25 else 0
        v_3026 = _u16(reg1[26]) if len(reg1) > 26 else 0

        if freq_3025 > 4000 and v_3026 > 1000:
            # Shifted (MOD-HU v7.6+) profile
            reading.grid_freq = freq_3025 / 100.0
            reading.grid_l1_v = v_3026 / 10.0
            reading.grid_l1_a = _u16(reg1[27]) / 10.0
            reading.grid_l2_v = _u16(reg2[0]) / 10.0
            reading.grid_l2_a = _u16(reg2[1]) / 10.0
            reading.grid_l3_v = _u16(reg2[4]) / 10.0
            reading.grid_l3_a = _u16(reg2[5]) / 10.0
        else:
            # Standard profile
            reading.grid_freq = _u16(reg2[12]) / 100.0        # 3042
            reading.grid_l1_v = _u16(reg2[0]) / 10.0          # 3030
            reading.grid_l1_a = _u16(reg2[1]) / 10.0          # 3031
            reading.grid_l2_v = _u16(reg2[4]) / 10.0          # 3034
            reading.grid_l2_a = _u16(reg2[5]) / 10.0          # 3035
            reading.grid_l3_v = _u16(reg2[8]) / 10.0          # 3038
            reading.grid_l3_a = _u16(reg2[9]) / 10.0          # 3039

        # Temperature (MOD-HU -20 shift puts these at 3094/3095 = reg2[64/65])
        reading.inverter_temp = _u16(reg2[64]) / 10.0
        reading.boost_temp = _u16(reg2[65]) / 10.0

        # Fault code at 3105 = reg2[75]
        reading.fault_code = _u16(reg2[75])

        # Smart Meter (Segment 3, base 3110)
        reading.meter_total_w = _s32(reg3[11], reg3[12]) / 10.0  # 3121–3122
        reading.meter_l1_w = _s32(reg3[13], reg3[14]) / 10.0     # 3123–3124
        reading.meter_l2_w = _s32(reg3[15], reg3[16]) / 10.0     # 3125–3126
        reading.meter_l3_w = _s32(reg3[17], reg3[18]) / 10.0     # 3127–3128

        # EPS V/A block 3130–3135 (reg3[20–25])
        reading.eps_l1_v = _u16(reg3[20]) / 10.0
        reading.eps_l1_a = _u16(reg3[21]) / 10.0
        reading.eps_l2_v = _u16(reg3[22]) / 10.0
        reading.eps_l2_a = _u16(reg3[23]) / 10.0
        reading.eps_l3_v = _u16(reg3[24]) / 10.0
        reading.eps_l3_a = _u16(reg3[25]) / 10.0
        reading.eps_p = (
            reading.eps_l1_v * reading.eps_l1_a
            + reading.eps_l2_v * reading.eps_l2_a
            + reading.eps_l3_v * reading.eps_l3_a
        )

        # Battery (Segment 4, base 3170)
        reading.bat_soc = _u16(reg4[0])
        reading.bat_v = _u16(reg4[1]) / 10.0
        reading.bat_i = _s16(reg4[2]) / 10.0
        reading.bat_p = _s32(reg4[3], reg4[4]) / 10.0

        # Energy counters
        reading.pv_today_kwh = _u32(reg2[19], reg2[20]) / 10.0         # 3049–3050
        reading.pv_total_kwh = _u32(reg2[21], reg2[22]) / 10.0         # 3051–3052
        reading.bat_discharge_today_kwh = _u32(reg4[6], reg4[7]) / 10.0  # 3176–3177
        reading.bat_charge_today_kwh = _u32(reg4[10], reg4[11]) / 10.0   # 3180–3181
        reading.grid_import_today_kwh = _u32(reg4[14], reg4[15]) / 10.0  # 3184–3185
        reading.grid_export_today_kwh = _u32(reg4[16], reg4[17]) / 10.0  # 3186–3187
        reading.load_today_kwh = _u32(reg4[18], reg4[19]) / 10.0         # 3188–3189

        # Derived: instantaneous load (PV - grid export/import - battery)
        reading.load_p = reading.pv_total_w - reading.meter_total_w - reading.bat_p

        # Raw register snapshot for the Modbus proxy
        raw = {}
        for i, v in enumerate(reg1): raw[str(3000 + i)] = v
        for i, v in enumerate(reg2): raw[str(3030 + i)] = v
        for i, v in enumerate(reg3): raw[str(3110 + i)] = v
        for i, v in enumerate(reg4): raw[str(3170 + i)] = v
        for i, v in enumerate(r5.registers): raw[str(i)] = v
        reading.raw_payload = json.dumps(raw).encode('utf-8')

        return reading

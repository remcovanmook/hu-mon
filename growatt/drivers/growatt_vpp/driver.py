"""
growatt.drivers.growatt_vpp.driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
GrowattVppDriver — telemetry driver for Growatt inverters supporting
VPP Protocol V2.01 or later (identified via DTC at FC 03 register 30000).

Primary register source: VPP (FC03 30000+, FC04 31000+).
Protocol II FC04 supplements: per-phase L-N voltages (3026-3035),
PV energy + boost temp (3049-3095), EPS data (3130-3159).
FC03 0-124 is the ShineWifi's own space and is not used for inverter data.

Poll segments
-------------
S0  FC04  3026-3035   Per-phase L-N voltages from Protocol II          (soft-fail)
S1  FC04  31000-31059  Status + PV strings + total PV power             (mandatory)
S2  FC04  31100-31125  AC / meter / freq / L-L voltages / temp / kWh   (mandatory)
S3  FC04  31200-31229  Battery 1 live data                              (soft-fail)
S4  FC04  3049-3095    PV energy kWh + boost temp (Protocol II)         (soft-fail)
S5  FC04  3130-3159    EPS V/A/power (Protocol II, has_eps only)        (soft-fail)
"""

import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Dict, Optional

from pymodbus.exceptions import ModbusIOException

from growatt.drivers.base import BaseDriver, DeviceInfo, ProbeContext, ProxyConfig
from growatt.drivers.growatt_base import (
    GrowattBaseDriver,
    _s16,
    _s32,
    _u16,
    _u32,
)
from growatt.reading import GrowattReading
from modbus.codec import ascii_regs

logger = logging.getLogger(__name__)

# Seconds to sleep between successive segment reads to avoid overwhelming
# the ShineWifi-X2 single-threaded TCP stack.
_INTER_SEGMENT_SLEEP: float = 0.05

# √3 — used to convert L-L voltages to L-N for per-phase power derivation.
_SQRT3: float = math.sqrt(3)


# ---------------------------------------------------------------------------
# DTC table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _DtcEntry:
    """
    Metadata for a Growatt VPP Device Type Code.

    :param series:   Growatt product family string, e.g. "MOD", "MID", "WIT".
    :param has_eps:  True when the device includes EPS / backup output.
    :param phases:   Number of AC phases (1 or 3).
    """
    series: str
    has_eps: bool
    phases: int


_VPP_DTC_TABLE: Dict[int, _DtcEntry] = {
    5400: _DtcEntry("MOD", False, 3),   # MOD-XH / MID-XH  (VPP V2.01 spec)
    5401: _DtcEntry("MOD", True,  3),   # MOD/MID-HU (V2.02; live device: 12KTL3-HU)
    5601: _DtcEntry("WIT", True,  3),
    3725: _DtcEntry("SPA", False, 3),
    3601: _DtcEntry("SPH", False, 1),
    5800: _DtcEntry("WIS", False, 3),
    5201: _DtcEntry("MIN", False, 1),
    5200: _DtcEntry("MIC", False, 1),
}

# DTCs for which battery registers (31200-31599) are not applicable.
_VPP_DTC_NO_BATTERY: frozenset = frozenset({5201, 5200})


def _build_model_string(entry: _DtcEntry, rated_w: int) -> str:
    """
    Construct a human-readable inverter model string from DTC metadata
    and rated power.

    Pattern: ``<series> <kW>KTL[<phases>]-<suffix>``

    The suffix is ``HU`` when the device has EPS output, ``XH`` otherwise.
    This mirrors the algorithm used by the Protocol II driver's
    ``_decode_model`` for consistency.

    :param entry:   DTC table entry (series, has_eps, phases).
    :param rated_w: Rated power in watts from VPP register 30016-30017.
    :returns:       Model string, e.g. ``"MOD 12KTL3-HU"``.
    """
    kw = max(1, round(rated_w / 1000))
    suffix = "HU" if entry.has_eps else "XH"
    if entry.phases > 1:
        return f"{entry.series} {kw}KTL{entry.phases}-{suffix}"
    return f"{entry.series} {kw}KTL-{suffix}"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class GrowattVppDriver(GrowattBaseDriver):
    """
    Growatt VPP Protocol V2.01/V2.02 telemetry driver.

    Targets Growatt inverters that expose the VPP register set over Modbus
    TCP (typically via ShineWifi-X2).  Probes via the DTC code at FC03
    register 30000, populated by registry Stage 3c.

    Stores ``_dtc_entry`` and ``_has_eps`` after ``read_device_info`` so
    ``read_registers`` can skip S5 when the device has no EPS output.
    """

    def __init__(self) -> None:
        self._dtc_entry: Optional[_DtcEntry] = None
        self._has_eps: bool = False

    @property
    def driver_id(self) -> str:
        """Unique driver identifier string."""
        return "growatt_vpp"

    # ------------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------------

    def _probe_series(self, ctx: ProbeContext) -> bool:
        """
        VPP series check: succeeds when ``ctx.vpp_dtc`` is a known DTC.

        Called only if ``_is_growatt()`` returned True (Protocol II status
        register confirms vendor identity).  A non-None, recognised DTC at
        FC03 30000 uniquely identifies a VPP-capable Growatt inverter.

        :param ctx: ProbeContext populated by registry Stages 1-3c.
        :returns:   True if this is a VPP-capable Growatt inverter.
        """
        if ctx.vpp_dtc is None:
            logger.info("growatt_vpp: vpp_dtc is None — no VPP registers")
            return False
        entry = _VPP_DTC_TABLE.get(ctx.vpp_dtc)
        if entry is None:
            logger.info(
                "growatt_vpp: DTC 0x%04X (%d) not in VPP table",
                ctx.vpp_dtc, ctx.vpp_dtc,
            )
            return False
        logger.info(
            "growatt_vpp: DTC %d → %s, has_eps=%s, phases=%d",
            ctx.vpp_dtc, entry.series, entry.has_eps, entry.phases,
        )
        return True

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    def read_device_info(self, client, slave_id: int) -> DeviceInfo:
        """
        Read static device metadata from VPP FC03 holding registers.

        All reads are soft-fail: on error the field falls back to a safe
        default and a warning is logged.  The collector will not crash on
        unavailable registers.

        Register layout:
          FC03 30000-30017  DTC + serial (first 2 words) + rated power
          FC03 30001-30015  Serial number (15 words, 30-char ASCII)
          FC03 9-14         Firmware string (ShineWifi mirrors DSP fw here)
          FC03 1001         Battery type (0=none, 1=Li-ion)
          FC03 1005         Battery nominal capacity (0.1 kWh)

        :param client:   Active pymodbus ModbusTcpClient.
        :param slave_id: Confirmed Modbus slave address.
        :returns:        Populated DeviceInfo.
        """
        dtc = None
        entry: Optional[_DtcEntry] = None
        model = "Unknown Growatt VPP"
        has_eps = False
        phases = 3
        rated_w = 0

        # DTC + rated power (30000-30017, 18 registers in one read)
        try:
            r = client.read_holding_registers(30000, count=18, device_id=slave_id)
            if not r.isError():
                dtc = r.registers[0]
                entry = _VPP_DTC_TABLE.get(dtc)
                pn_raw = _u32(r.registers[16], r.registers[17])
                rated_w = int(pn_raw / 10.0)
                if entry:
                    model = _build_model_string(entry, rated_w)
                    has_eps = entry.has_eps
                    phases = entry.phases
                    logger.info(
                        "read_device_info: DTC=%d → %s, rated_w=%dW, has_eps=%s",
                        dtc, model, rated_w, has_eps,
                    )
                else:
                    logger.warning(
                        "read_device_info: DTC %d unknown — using generic model name",
                        dtc,
                    )
            else:
                logger.warning("read_device_info: FC03 30000-30017 error: %s", r)
        except Exception as exc:
            logger.warning("read_device_info: FC03 30000-30017 exception: %s", exc)

        # Serial number (30001-30015, 15 words ASCII)
        serial = ""
        try:
            r = client.read_holding_registers(30001, count=15, device_id=slave_id)
            if not r.isError():
                serial = ascii_regs(r.registers).strip("\x00").strip()
                logger.info("read_device_info: serial=%r", serial)
            else:
                logger.warning("read_device_info: serial read error: %s", r)
        except Exception as exc:
            logger.warning("read_device_info: serial exception: %s", exc)

        # Firmware string (FC03 9-14; ShineWifi mirrors inverter DSP version)
        firmware = ""
        try:
            r = client.read_holding_registers(9, count=6, device_id=slave_id)
            if not r.isError():
                firmware = ascii_regs(r.registers).strip("\x00").strip()
                logger.info("read_device_info: firmware=%r", firmware)
            else:
                logger.warning("read_device_info: firmware read error: %s", r)
        except Exception as exc:
            logger.warning("read_device_info: firmware exception: %s", exc)

        # Battery type + nominal capacity
        bat_nominal_kwh = 0.0
        has_battery = False
        if dtc is not None and dtc not in _VPP_DTC_NO_BATTERY:
            try:
                r = client.read_holding_registers(1001, count=1, device_id=slave_id)
                if not r.isError() and r.registers[0] != 0:
                    has_battery = True
                    logger.info("read_device_info: battery type=%d", r.registers[0])
            except Exception as exc:
                logger.warning("read_device_info: battery type exception: %s", exc)

            try:
                r = client.read_holding_registers(1005, count=1, device_id=slave_id)
                if not r.isError() and r.registers[0] != 0:
                    bat_nominal_kwh = _u16(r.registers[0]) / 10.0
                    logger.info("read_device_info: bat_nominal_kwh=%.1f", bat_nominal_kwh)
            except Exception as exc:
                logger.warning("read_device_info: bat_nominal_kwh exception: %s", exc)

        # Cache has_eps for use in read_registers (S5 gating)
        self._dtc_entry = entry
        self._has_eps = has_eps

        return DeviceInfo(
            model=model,
            serial=serial,
            firmware=firmware,
            rated_power_w=rated_w,
            bat_nominal_kwh=bat_nominal_kwh,
            phases=phases,
            pv_strings=None,
            has_eps=has_eps,
            has_battery=has_battery,
        )

    # ------------------------------------------------------------------
    # Register poll
    # ------------------------------------------------------------------

    def read_registers(self, client, slave_id: int) -> GrowattReading:
        """
        Execute one full VPP telemetry poll cycle.

        Segment reads:
          S0  FC04  3026-3035    Protocol II per-phase L-N voltages       (soft-fail)
          S1  FC04  31000-31059  Status + PV strings + total PV power     (mandatory)
          S2  FC04  31100-31125  AC / meter / freq / L-L V / temp / kWh  (mandatory)
          S3  FC04  31200-31229  Battery 1                                (soft-fail)
          S4  FC04  3049-3095    PV energy kWh + boost temp               (soft-fail)
          S5  FC04  3130-3159    EPS data, only when has_eps=True         (soft-fail)

        S0 and S4/S5 use Protocol II FC04 addresses.  All reads go through
        the same ShineWifi TCP endpoint.

        Per-string PV power: V × I (DC, no power factor).
        Grid voltages: L-N from Protocol II registers 3026/3030/3034 (S0).
          If S0 fails, falls back to VPP L-L registers 31106-31108 ÷ √3
          (approximation valid only for a balanced system).
        Per-phase AC power: V_LN × I × PF where PF = P / |S|.

        :param client:   Active pymodbus ModbusTcpClient.
        :param slave_id: Confirmed Modbus slave address.
        :raises ModbusIOException: If S1 or S2 fails.
        """
        # S0: Protocol II per-phase L-N voltages (FC04 3026-3035, 10 registers, soft-fail).
        # Layout: [Vac1, Iac1, Pac1_H, Pac1_L, Vac2, Iac2, Pac2_H, Pac2_L, Vac3, Iac3]
        # Offsets 0/4/8 give actual measured L-N voltages for L1/L2/L3.
        s0 = None
        try:
            r = client.read_input_registers(3026, count=10, device_id=slave_id)
            if not r.isError():
                s0 = r.registers
        except Exception as exc:
            logger.debug("growatt_vpp: S0 (3026-3035) failed: %s", exc)
        time.sleep(_INTER_SEGMENT_SLEEP)

        # S1: Status + PV (31000-31059, 60 registers)
        r1 = client.read_input_registers(31000, count=60, device_id=slave_id)
        if r1.isError():
            raise ModbusIOException("growatt_vpp: S1 (31000-31059) read failed")
        time.sleep(_INTER_SEGMENT_SLEEP)

        # S2: AC + grid + energy (31100-31125, 26 registers)
        r2 = client.read_input_registers(31100, count=26, device_id=slave_id)
        if r2.isError():
            raise ModbusIOException("growatt_vpp: S2 (31100-31125) read failed")
        time.sleep(_INTER_SEGMENT_SLEEP)

        # S3: Battery 1 (31200-31229, 30 registers, soft-fail)
        s3 = None
        try:
            r = client.read_input_registers(31200, count=30, device_id=slave_id)
            if not r.isError():
                s3 = r.registers
        except Exception as exc:
            logger.debug("growatt_vpp: S3 (31200-31229) failed: %s", exc)
        time.sleep(_INTER_SEGMENT_SLEEP)

        # S4: PV energy + boost temp (FC04 3049-3095, 47 registers, soft-fail)
        s4 = None
        try:
            r = client.read_input_registers(3049, count=47, device_id=slave_id)
            if not r.isError():
                s4 = r.registers
        except Exception as exc:
            logger.debug("growatt_vpp: S4 (3049-3095) failed: %s", exc)
        time.sleep(_INTER_SEGMENT_SLEEP)

        # S5: EPS (FC04 3130-3159, 30 registers, soft-fail, has_eps only)
        s5 = None
        if self._has_eps:
            try:
                r = client.read_input_registers(3130, count=30, device_id=slave_id)
                if not r.isError():
                    s5 = r.registers
            except Exception as exc:
                logger.debug("growatt_vpp: S5 (3130-3159) failed: %s", exc)

        s1 = r1.registers   # base 31000
        s2 = r2.registers   # base 31100

        reading = GrowattReading()

        # --- Status (S1) ---
        reading.status_code = _u16(s1[0])    # 31000
        reading.fault_code  = _u16(s1[5])    # 31005

        # --- PV strings (S1, 2 registers per string: V + A; P = V × I DC) ---
        reading.pv1_v = _u16(s1[10]) / 10.0   # 31010
        reading.pv1_a = _u16(s1[11]) / 10.0   # 31011
        reading.pv1_w = reading.pv1_v * reading.pv1_a

        reading.pv2_v = _u16(s1[12]) / 10.0   # 31012
        reading.pv2_a = _u16(s1[13]) / 10.0   # 31013
        reading.pv2_w = reading.pv2_v * reading.pv2_a

        reading.pv3_v = _u16(s1[14]) / 10.0   # 31014
        reading.pv3_a = _u16(s1[15]) / 10.0   # 31015
        reading.pv3_w = reading.pv3_v * reading.pv3_a

        reading.pv4_v = _u16(s1[16]) / 10.0   # 31016
        reading.pv4_a = _u16(s1[17]) / 10.0   # 31017
        reading.pv4_w = reading.pv4_v * reading.pv4_a

        # Total PV power: INT32 at 31058-31059 (offsets 58-59 from base 31000)
        reading.pv_total_w = _u32(s1[58], s1[59]) / 10.0

        # --- AC / grid (S2, base 31100) ---
        # Intermediate values used to derive PF and load_p
        ac_active_w    = _s32(s2[0], s2[1]) / 10.0    # 31100-31101 (pos=export)
        ac_reactive_var = _s32(s2[2], s2[3]) / 10.0   # 31102-31103

        reading.grid_freq = _u16(s2[5])  / 100.0   # 31105
        reading.grid_l1_a = _s16(s2[9])  / 10.0    # 31109
        reading.grid_l2_a = _s16(s2[10]) / 10.0    # 31110
        reading.grid_l3_a = _s16(s2[11]) / 10.0    # 31111

        # Grid L-N voltages: read directly from Protocol II registers 3026/3030/3034 (S0).
        # The VPP spec only provides L-L values (31106-31108); those cannot be reliably
        # converted to individual L-N voltages for a potentially unbalanced system.
        # Fall back to VPP L-L ÷ √3 only when S0 is unavailable.
        if s0:
            reading.grid_l1_v = _u16(s0[0]) / 10.0   # 3026 L1-N (0.1V)
            reading.grid_l2_v = _u16(s0[4]) / 10.0   # 3030 L2-N (0.1V)
            reading.grid_l3_v = _u16(s0[8]) / 10.0   # 3034 L3-N (0.1V)
        else:
            logger.warning("growatt_vpp: S0 unavailable — falling back to L-L/√3 approximation")
            reading.grid_l1_v = (_u16(s2[6]) / 10.0) / _SQRT3   # 31106 L-L AB → L-N
            reading.grid_l2_v = (_u16(s2[7]) / 10.0) / _SQRT3   # 31107 L-L BC → L-N
            reading.grid_l3_v = (_u16(s2[8]) / 10.0) / _SQRT3   # 31108 L-L CA → L-N

        # VPP meter power: pos=import from grid → invert for GrowattReading (pos=export)
        reading.meter_total_w = -(_s32(s2[12], s2[13]) / 10.0)   # 31112-31113

        reading.inverter_temp = _s16(s2[14]) / 10.0   # 31114

        # Energy counters
        reading.load_today_kwh        = _u32(s2[18], s2[19]) / 10.0   # 31118-31119
        reading.grid_export_today_kwh = _u32(s2[22], s2[23]) / 10.0   # 31122-31123

        # --- Derived: power factor and per-phase AC power ---
        # PF = P / |S|; guard against near-zero apparent power (night / standby)
        apparent_w = math.sqrt(ac_active_w ** 2 + ac_reactive_var ** 2)
        pf = (ac_active_w / apparent_w) if apparent_w > 1.0 else 1.0

        # Per-phase W = V_LN × I × PF  (grid_l*_v is now already L-N)
        reading.meter_l1_w = reading.grid_l1_v * reading.grid_l1_a * pf
        reading.meter_l2_w = reading.grid_l2_v * reading.grid_l2_a * pf
        reading.meter_l3_w = reading.grid_l3_v * reading.grid_l3_a * pf

        # --- Battery 1 (S3, soft-fail; all-zero when no battery present) ---
        if s3 and any(v != 0 for v in s3):
            reading.bat_p                  = _s32(s3[0],  s3[1])  / 10.0   # 31200-31201
            reading.bat_charge_today_kwh    = _u32(s3[2],  s3[3])  / 10.0   # 31202-31203
            reading.bat_charge_total_kwh    = _u32(s3[4],  s3[5])  / 10.0   # 31204-31205
            reading.bat_discharge_today_kwh = _u32(s3[6],  s3[7])  / 10.0   # 31206-31207
            reading.bat_discharge_total_kwh = _u32(s3[8],  s3[9])  / 10.0   # 31208-31209
            reading.bat_v                   = _s16(s3[14])          / 10.0   # 31214
            reading.bat_i                   = _s32(s3[15], s3[16]) / 10.0   # 31215-31216
            reading.bat_soc                 = _u16(s3[17])                   # 31217

        # --- PV energy + boost temp (S4, Protocol II supplement, soft-fail) ---
        if s4:
            reading.pv_today_kwh = _u32(s4[0],  s4[1])  / 10.0   # 3049-3050
            reading.pv_total_kwh = _u32(s4[2],  s4[3])  / 10.0   # 3051-3052
            reading.boost_temp   = _u16(s4[46]) / 10.0            # 3095 (offset 46)

        # --- EPS (S5, Protocol II fallback, soft-fail, has_eps only) ---
        if s5:
            reading.eps_l1_v = _u16(s5[0]) / 10.0    # 3130
            reading.eps_l1_a = _u16(s5[1]) / 10.0    # 3131
            reading.eps_l2_v = _u16(s5[2]) / 10.0    # 3132
            reading.eps_l2_a = _u16(s5[3]) / 10.0    # 3133
            reading.eps_l3_v = _u16(s5[4]) / 10.0    # 3134
            reading.eps_l3_a = _u16(s5[5]) / 10.0    # 3135
            reading.eps_p    = _u32(s5[28], s5[29]) / 10.0   # 3158-3159

        # --- Derived load power ---
        reading.load_p = reading.pv_total_w - reading.meter_total_w - reading.bat_p

        # --- Raw register snapshot for the Modbus proxy ---
        raw: dict = {}
        if s0:
            for i, v in enumerate(s0):
                raw[str(3026 + i)] = v
        for i, v in enumerate(s1):
            raw[str(31000 + i)] = v
        for i, v in enumerate(s2):
            raw[str(31100 + i)] = v
        if s3:
            for i, v in enumerate(s3):
                raw[str(31200 + i)] = v
        if s4:
            for i, v in enumerate(s4):
                raw[str(3049 + i)] = v
        if s5:
            for i, v in enumerate(s5):
                raw[str(3130 + i)] = v
        reading.raw_payload = json.dumps(raw).encode("utf-8")

        return reading

    # ------------------------------------------------------------------
    # Proxy config
    # ------------------------------------------------------------------

    def proxy_config(self, slave_id: int) -> ProxyConfig:
        """
        Modbus address ranges the proxy server should expose.

        FC03 30000-30099 covers VPP identity + control holding registers.
        FC04 ranges mirror the five poll segments.

        :param slave_id: Confirmed Modbus slave address.
        :returns:        ProxyConfig describing servable register ranges.
        """
        return ProxyConfig(
            address_map={
                slave_id: {
                    3: [(30000, 100)],
                    4: [
                        (3026,  10),
                        (31000, 60),
                        (31100, 26),
                        (31200, 30),
                        (3049,  47),
                        (3130,  30),
                    ],
                }
            }
        )

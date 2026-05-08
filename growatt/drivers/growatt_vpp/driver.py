"""
growatt.drivers.growatt_vpp.driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
GrowattVppDriver — telemetry driver for Growatt inverters supporting
VPP Protocol V2.01 or later (identified via DTC at FC 03 register 30000).

Primary register source: VPP (FC03 30000+, FC04 31000+).
Protocol II FC04 supplements: per-phase L-N voltages (3026-3035),
PV energy + boost temp (3049-3095), EPS data (3130-3159).
FC03 0-124 holds inverter configuration registers (firmware, device_type, etc.)

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
from enum import Enum
from typing import Dict, List, Optional, Tuple

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


def _ll_to_ln(v_rs: float, v_st: float, v_tr: float) -> tuple:
    """
    Derive per-phase L-N voltage magnitudes from the three L-L magnitudes.

    The three L-N phasor tips (V_R, V_S, V_T) form a triangle whose side
    lengths are the L-L voltages.  In a wye system the neutral lies at the
    centroid of that triangle; each L-N voltage is the distance from its
    vertex to the centroid.

    Method:
      1. Fix V_S at the origin and V_T on the positive x-axis.
      2. Locate V_R using the law of cosines at vertex S.
      3. Compute the centroid G = (V_R + V_S + V_T) / 3.
      4. Return |V_R − G|, |V_S − G|, |V_T − G|.

    Works for any triangle (balanced or unbalanced phase voltages) and
    requires no approximation beyond the wye-with-grounded-neutral model.

    :param v_rs: Line-to-line voltage magnitude RS (volts).
    :param v_st: Line-to-line voltage magnitude ST (volts).
    :param v_tr: Line-to-line voltage magnitude TR (volts).
    :returns:    Tuple (v_rn, v_sn, v_tn) — L-N voltage magnitudes in volts.
    :raises ValueError: If the three magnitudes cannot form a valid triangle.
    """
    # Guard: triangle inequality (any two sides must exceed the third)
    if v_rs + v_st <= v_tr or v_st + v_tr <= v_rs or v_tr + v_rs <= v_st:
        raise ValueError(
            f"L-L values ({v_rs}, {v_st}, {v_tr}) do not form a valid triangle"
        )

    # Place S at origin, T on the positive x-axis
    sx, sy = 0.0, 0.0
    tx, ty = v_st, 0.0

    # Locate R via law of cosines at vertex S (angle between sides RS and ST)
    cos_s = (v_rs ** 2 + v_st ** 2 - v_tr ** 2) / (2.0 * v_rs * v_st)
    sin_s = math.sqrt(max(0.0, 1.0 - cos_s ** 2))  # always take positive root
    rx = v_rs * cos_s
    ry = v_rs * sin_s

    # Centroid = neutral point N
    gx = (rx + sx + tx) / 3.0
    gy = (ry + sy + ty) / 3.0

    v_rn = math.sqrt((rx - gx) ** 2 + (ry - gy) ** 2)
    v_sn = math.sqrt((sx - gx) ** 2 + (sy - gy) ** 2)
    v_tn = math.sqrt((tx - gx) ** 2 + (ty - gy) ** 2)

    return v_rn, v_sn, v_tn


# ---------------------------------------------------------------------------
# Register profiles and DTC table
# ---------------------------------------------------------------------------

class _RegProfile(str, Enum):
    """
    Describes the Modbus register space available on a given device family.

    Profiles are additive: VPP devices also have Protocol II registers.
    The proxy exposes all ranges in the detected profile.
    """
    BASE_PROTO_II_VPP = "base_proto_ii_vpp"  # FC03 0-124 + 3000-3374 + 30000-30099
    BASE_PROTO_II     = "base_proto_ii"      # FC03 0-124 + 3000-3374
    BASE_STORAGE      = "base_storage"       # FC03 0-124 + 1000-1124
    BASE_PROTO_I_WIT  = "base_proto_i_wit"   # FC03 0-124 + 125-249 + 875-999


# Full Protocol II FC04 block (3000-3374) is exposed for all Protocol II and
# VPP profiles.  Our driver polls sub-ranges within this space; external clients
# get the complete block.  VPP FC04 space (31000+) added for VPP profiles.
_FC03_RANGES: Dict[_RegProfile, List[Tuple[int, int]]] = {
    _RegProfile.BASE_PROTO_II_VPP: [(0, 125), (3000, 125), (3250, 125), (30000, 100)],
    _RegProfile.BASE_PROTO_II:     [(0, 125), (3000, 125), (3250, 125)],
    _RegProfile.BASE_STORAGE:      [(0, 125), (1000, 125)],
    _RegProfile.BASE_PROTO_I_WIT:  [(0, 125), (125, 125),  (875, 125)],
}
_FC04_RANGES: Dict[_RegProfile, List[Tuple[int, int]]] = {
    _RegProfile.BASE_PROTO_II_VPP: [(3000, 125), (3125, 125), (3250, 125),
                                    (31000, 60),  (31100, 26), (31200, 30)],
    _RegProfile.BASE_PROTO_II:     [(3000, 125), (3125, 125), (3250, 125)],
    _RegProfile.BASE_STORAGE:      [(0, 125), (1000, 125)],
    _RegProfile.BASE_PROTO_I_WIT:  [(0, 125), (125, 125), (8000, 125)],
}


@dataclass(frozen=True)
class _DtcEntry:
    """
    Metadata for a Growatt VPP Device Type Code.

    :param series:      Growatt product family string, e.g. "MOD", "MID", "WIT".
    :param has_eps:     True when the device includes EPS / backup output.
    :param phases:      Number of AC phases (1 or 3).
    :param reg_profile: Register space this device family supports.
    """
    series:      str
    has_eps:     bool
    phases:      int
    reg_profile: _RegProfile


_VPP_DTC_TABLE: Dict[int, _DtcEntry] = {
    # Source: VPP Communication Protocol V2.01, Table 3-1
    #
    # DTC structure: [family (first 2 digits)] [variant (last 2 digits)]
    #   Family identifies the product line (54=MOD/MID, 56=WIT, 58=WIS,
    #           51=MIN-XH, 52=MIC/MIN-X, 36=SPH-3ph, 37=SPA-3ph, ...)
    #   Variant: 00=XH/no-EPS, 01=HU/hybrid(EPS+battery).
    #   Exception: 52xx uses variant for power range, not EPS.
    3502: _DtcEntry("SPH", False, 1, _RegProfile.BASE_STORAGE),  # SPH 3000-6000TL BL
    3601: _DtcEntry("SPH", True,  3, _RegProfile.BASE_STORAGE),  # SPH 4000-10000TL3 BH-UP
    3725: _DtcEntry("SPA", True,  3, _RegProfile.BASE_STORAGE),  # SPA 4000-10000TL3 BH-UP
    3735: _DtcEntry("SPA", False, 1, _RegProfile.BASE_STORAGE),  # SPA 3000-6000TL BL
    5100: _DtcEntry("MIN", False, 1, _RegProfile.BASE_PROTO_II), # MIN 2500-6000TL-XH/XH(P)
    5200: _DtcEntry("MIC", False, 1, _RegProfile.BASE_PROTO_II), # MIC/MIN 2500-6000TL-X/X2
    5201: _DtcEntry("MIN", False, 1, _RegProfile.BASE_PROTO_II), # MIN 7000-10000TL-X/X2
    5400: _DtcEntry("MOD", False, 3, _RegProfile.BASE_PROTO_II_VPP), # MOD-XH / MID-XH
    5401: _DtcEntry("MOD", True,  3, _RegProfile.BASE_PROTO_II_VPP), # MOD/MID-HU (confirmed: 12KTL3-HU V2.02)
    5601: _DtcEntry("WIT", True,  3, _RegProfile.BASE_PROTO_I_WIT),  # WIT 100KTL3-H
    5800: _DtcEntry("WIS", False, 3, _RegProfile.BASE_PROTO_II),     # WIS 215KTL3
}

# DTCs for which battery registers (31200+) are not applicable.
_VPP_DTC_NO_BATTERY: frozenset = frozenset({5200, 5201})



def _dtc_infer_entry(dtc: int) -> _DtcEntry:
    """
    Return a generic _DtcEntry for DTC codes not in _VPP_DTC_TABLE.

    Called only when the probe has already confirmed VPP capability via
    vpp_protocol_version, so it is safe to assume BASE_PROTO_II_VPP.
    Phase count defaults to 3; callers should override from FC03 reg 44 (TP).
    Series is "UNK" to make the fallback path visible in logs.

    :param dtc: Raw DTC value from VPP register 30000.
    :returns:   Generic _DtcEntry with BASE_PROTO_II_VPP profile.
    """
    return _DtcEntry("UNK", False, 3, _RegProfile.BASE_PROTO_II_VPP)



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
        self._vpp_protocol_version: int = 0
        # Populated by read_device_info from FC03 30099.
        # 201 = V2.01 (spec doc version), 202 = V2.02 (seen on MOD 12KTL3-HU).
        # Use this to gate register-map differences between protocol generations.
        self._static_regs: dict = {}
        # FC03 holding register snapshot (0-124 and 30000-30099) keyed by
        # absolute address string, e.g. {"0": 1, "44": 2051, "30000": 5401}.
        # Populated once by read_device_info and merged into every raw_payload
        # so the proxy serves correct values for all claimed FC03 ranges.

    @property
    def driver_id(self) -> str:
        """Unique driver identifier string."""
        return "growatt_vpp"

    # ------------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------------

    def _probe_series(self, ctx: ProbeContext) -> bool:
        """
        VPP series check.

        Priority:
          1. Known DTC in _VPP_DTC_TABLE  →  accept unconditionally.
             DTC codes are from the VPP spec; their presence is authoritative.
          2. Unknown DTC + valid vpp_protocol_version (200-299)  →  accept.
             Newer hardware likely supports VPP; infer a generic profile.
          3. Anything else  →  reject.

        vpp_protocol_version is NOT used as a gate for known DTCs —
        it is retained for version-gated register-map branching in
        read_registers.

        :param ctx: ProbeContext populated by registry Stages 1-3c.
        :returns:   True if this is a VPP-capable Growatt inverter.
        """
        if ctx.vpp_dtc is None:
            logger.info("growatt_vpp: no DTC — not a VPP device")
            return False

        entry = _VPP_DTC_TABLE.get(ctx.vpp_dtc)
        if entry:
            logger.info(
                "growatt_vpp: DTC %d → %s, profile=%s, has_eps=%s, phases=%d",
                ctx.vpp_dtc, entry.series, entry.reg_profile.value,
                entry.has_eps, entry.phases,
            )
            return True

        # Unknown DTC: require VPP version confirmation before accepting.
        ver = ctx.vpp_protocol_version
        if ver is not None and 200 <= ver <= 299:
            logger.info(
                "growatt_vpp: DTC %d unknown, VPP V%d.%02d confirmed — using generic profile",
                ctx.vpp_dtc, ver // 100, ver % 100,
            )
            return True

        logger.info(
            "growatt_vpp: DTC %d unknown and no valid vpp_protocol_version (%s) — rejecting",
            ctx.vpp_dtc, ver,
        )
        return False


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
          FC03 30000-30099  Single block covering all Basic Parameter and
                            Version Information registers:
            30000           DTC (device type code)
            30001-30015     Serial number (15 words, 30-char ASCII)
            30016-30017     Rated power Pn (0.1 W)
            30060-30061     Inverter type-model chars (ASCII, e.g. "TL" + "AA")
            30099           VPP protocol version (201 = V2.01, 202 = V2.02 …)
          FC03 9-14         Firmware string (inverter FC03 holding register)
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

        # ---------------------------------------------------------------
        # DTC, rated power, model-type chars, VPP protocol version
        # Read full Basic Parameter block 30000-30099 (100 registers) in one call.
        try:
            r = client.read_holding_registers(30000, count=100, device_id=slave_id)
            if not r.isError():
                # Seed proxy static register cache for FC03 30000-30099.
                for i, v in enumerate(r.registers):
                    self._static_regs[str(30000 + i)] = v

                dtc = r.registers[0]
                entry = _VPP_DTC_TABLE.get(dtc)
                if entry is None:
                    entry = _dtc_infer_entry(dtc)
                pn_raw = _u32(r.registers[16], r.registers[17])
                rated_w = int(pn_raw / 10.0)

                # 30060-30061: DSP firmware model code (2×ASCII, high+low byte per reg).
                # e.g. 'DO'+'AA' on MOD 12KTL3-HU running DO1.0.  This is the internal
                # DSP version name, *not* the inverter topology suffix ('TL'/'KTL').
                # The topology comes from _build_model_string via the DTC entry.
                def _ascii2(reg: int) -> str:
                    hi, lo = (reg >> 8) & 0xFF, reg & 0xFF
                    return "".join(chr(b) if 32 <= b < 127 else "" for b in (hi, lo))
                model_type = _ascii2(r.registers[60]) + _ascii2(r.registers[61])
                model_type = model_type.strip()

                # 30099: VPP protocol version (e.g. 201 = V2.01)
                vpp_ver = r.registers[99]
                self._vpp_protocol_version = vpp_ver
                vpp_ver_str = f"V{vpp_ver // 100}.{vpp_ver % 100:02d}" if vpp_ver else "unknown"

                if entry and entry.series != "UNK":
                    model = _build_model_string(entry, rated_w)
                    has_eps = entry.has_eps
                    phases = entry.phases
                    logger.info(
                        "read_device_info: DTC=%d → %s, rated_w=%dW, has_eps=%s"
                        ", type=%r, vpp=%s",
                        dtc, model, rated_w, has_eps, model_type, vpp_ver_str,
                    )
                else:
                    logger.warning(
                        "read_device_info: DTC %d unknown (inferred), type=%r, vpp=%s",
                        dtc, model_type, vpp_ver_str,
                    )
            else:
                logger.warning("read_device_info: FC03 30000-30099 error: %s", r)
        except Exception as exc:
            logger.warning("read_device_info: FC03 30000-30099 exception: %s", exc)

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

        # Firmware string at FC03 9-14 — inverter holding register, accessed
        # directly via the ShineWifi gateway (transparent Modbus TCP proxy).
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

        # FC03 reg 44: TP — input tracker count (high byte) and AC phase count (low byte).
        # High byte: total input count.  On MOD 12KTL3-HU this is 8 (4 MPPTs × 2 strings,
        # or 4 PV + 4 BDC — ambiguous from the AppNote alone).
        # Low byte: AC output phase count.  This is authoritative: no model-string inference.
        pv_inputs = None
        try:
            r = client.read_holding_registers(44, count=1, device_id=slave_id)
            if not r.isError() and r.registers[0] != 0:
                raw_tp = r.registers[0]
                pv_inputs = (raw_tp >> 8) & 0xFF
                tp_phases = raw_tp & 0xFF
                if tp_phases in (1, 3):
                    phases = tp_phases   # override DTC-inferred value
                logger.info(
                    "read_device_info: TP=0x%04X — inputs=%d, phases=%d",
                    raw_tp, pv_inputs, phases,
                )
            else:
                logger.debug("read_device_info: FC03 reg 44 unavailable — keeping DTC-inferred phases=%d", phases)
        except Exception as exc:
            logger.warning("read_device_info: FC03 reg 44 exception: %s", exc)

        # FC03 0-124: base holding block — firmware, DTC, RTC, TP, grid thresholds.
        # Read once here so the proxy can serve this range.  The data is static;
        # no need to re-read on every poll cycle.
        try:
            r = client.read_holding_registers(0, count=125, device_id=slave_id)
            if not r.isError():
                for i, v in enumerate(r.registers):
                    self._static_regs[str(i)] = v
            else:
                logger.debug("read_device_info: FC03 0-124 error: %s", r)
        except Exception as exc:
            logger.debug("read_device_info: FC03 0-124 exception: %s", exc)

        # Cache has_eps and VPP protocol version for use in read_registers
        self._dtc_entry = entry
        self._has_eps = has_eps
        # _vpp_protocol_version already set above (or stays 0 if block read failed)

        return DeviceInfo(
            model=model,
            serial=serial,
            firmware=firmware,
            rated_power_w=rated_w,
            bat_nominal_kwh=bat_nominal_kwh,
            phases=phases,
            pv_strings=pv_inputs,
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
          If S0 fails, falls back to VPP L-L registers 31106-31108 via
          phasor triangle geometry (_ll_to_ln).
        Per-phase AC power: V_LN × I × PF where PF = P / |S|.

        Version-gated behaviour: ``self._vpp_protocol_version`` (from FC03
        30099, set by ``read_device_info``) can be used to select different
        register maps for V2.00 vs V2.01 vs V2.02 devices.  No branching is
        currently active; the field is available for future use.

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

        # L-L voltages (VPP 31106-31108): always store directly, RS/ST/TR naming.
        reading.grid_ll_rs_v = _u16(s2[6]) / 10.0   # 31106 RS
        reading.grid_ll_st_v = _u16(s2[7]) / 10.0   # 31107 ST
        reading.grid_ll_tr_v = _u16(s2[8]) / 10.0   # 31108 TR

        # Grid L-N voltages: read directly from Protocol II registers 3026/3030/3034 (S0).
        # The VPP spec only provides L-L values (31106-31108); those cannot be reliably
        # converted to individual L-N voltages for a potentially unbalanced system.
        # If S0 is unavailable, derive L-N values via phasor triangle geometry (_ll_to_ln).
        if s0:
            reading.grid_l1_v = _u16(s0[0]) / 10.0   # 3026 L1-N (0.1V)
            reading.grid_l2_v = _u16(s0[4]) / 10.0   # 3030 L2-N (0.1V)
            reading.grid_l3_v = _u16(s0[8]) / 10.0   # 3034 L3-N (0.1V)
        else:
            logger.warning("growatt_vpp: S0 unavailable — deriving L-N from L-L via phasor triangle")
            reading.grid_l1_v, reading.grid_l2_v, reading.grid_l3_v = _ll_to_ln(
                reading.grid_ll_rs_v, reading.grid_ll_st_v, reading.grid_ll_tr_v
            )

        # VPP meter power: pos=import from grid → invert for GrowattReading (pos=export)
        # Grid power: inverter AC output at 31100-31101 (pos = export to grid).
        # Register 31112-31113 (smart meter net power) would be more accurate for
        # net import/export, but requires a CT clamp that is not installed here.
        # Without a meter, the inverter AC output IS the grid exchange value.
        reading.meter_total_w = ac_active_w   # 31100-31101

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
        # Start with static holding register snapshot (FC03 0-124 and 30000-30099)
        # populated by read_device_info.  Dynamic FC04 poll values are added on
        # top; keys don't overlap so no dynamic data is overwritten.
        raw: dict = dict(self._static_regs)

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

    def proxy_config(self, slave_id: int, ctx: ProbeContext) -> ProxyConfig:
        """
        Build the Modbus address map from the DTC register profile.

        The profile is derived from ``ctx.vpp_dtc`` (populated during Stage 3c
        of the probe pipeline) so this method is correct when called immediately
        after ``auto_select`` — before ``read_device_info`` has run.

        Falls back to ``BASE_PROTO_II_VPP`` for unknown DTCs (VPP confirmed by
        ``ctx.vpp_protocol_version``) or when DTC is absent.

        :param slave_id: Confirmed Modbus slave address.
        :param ctx:      ProbeContext carrying vpp_dtc and protocol flags.
        :returns:        ProxyConfig describing the servable register space.
        """
        entry = _VPP_DTC_TABLE.get(ctx.vpp_dtc) if ctx.vpp_dtc else None
        profile = entry.reg_profile if entry else _RegProfile.BASE_PROTO_II_VPP
        fc03 = list(_FC03_RANGES[profile])
        fc04 = list(_FC04_RANGES[profile])
        if ctx.proto_ii_us_available:
            fc03.append((3125, 125))
        return ProxyConfig(address_map={slave_id: {3: fc03, 4: fc04}})

"""
growatt.drivers.growatt_base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Intermediate abstract driver for all Growatt inverter families.

Implements the vendor-level portion of the two-tier probe:
  1. GrowattBaseDriver.probe() calls _is_growatt() first.
  2. If the device is confirmed as Growatt, it delegates to _probe_series()
     which subclasses implement to narrow down the model family.

Also provides Growatt-specific sentinel-aware register wrappers that call into
growatt.drivers.codec.  The 0xFFFF sentinel is a Growatt firmware convention
(registers hold 0xFFFF during night / sleep mode) and does not belong in the
generic codec.

Known Growatt series codes (Holding Regs 28-29, upper 16 bits of module_id):
"""

import re
from abc import abstractmethod

from growatt.drivers.base import BaseDriver, ProbeContext
from growatt.drivers.codec import ascii_regs, s32_be, u16_be, u32_be

# ---------------------------------------------------------------------------
# Growatt series code → series name mapping.
# All series codes Growatt has assigned across the Protocol I/II range.
# ---------------------------------------------------------------------------
GROWATT_SERIES = {
    0x05: "MIN",
    0x0B: "MOD",
    0x0C: "MID",
    0x0D: "SPH",
    0x0E: "SPA",
    0x0F: "MIC",
    0x10: "MAC",
    0x11: "MAX",
}

# Firmware version pattern used by all known Growatt Protocol II devices.
# Format: one or more dotted numeric segments, e.g. "7.6.1.8" or "1.24".
_FW_PATTERN = re.compile(r'^\d+(\.\d+)+$')

# Sentinel value used in Growatt firmware to indicate "no data" / sleep mode.
_SENTINEL = 0xFFFF


# ---------------------------------------------------------------------------
# Sentinel-aware register wrappers
# ---------------------------------------------------------------------------

def _u16(reg: int) -> int:
    """
    Growatt-safe unsigned 16-bit register read.

    Returns 0 when the register holds the 0xFFFF sleep sentinel,
    otherwise delegates to the generic u16_be codec.
    """
    return 0 if reg == _SENTINEL else u16_be(reg)


def _s16(reg: int) -> int:
    """
    Growatt-safe signed 16-bit register read.

    Returns 0 on the 0xFFFF sentinel, otherwise two's-complement from the
    generic s16_be codec.
    """
    if reg == _SENTINEL:
        return 0
    val = u16_be(reg)
    return val - 0x10000 if val > 0x7FFF else val


def _u32(high: int, low: int) -> int:
    """
    Growatt-safe unsigned 32-bit register read.

    Returns 0 when both registers are the 0xFFFF sentinel.
    """
    return 0 if (high == _SENTINEL and low == _SENTINEL) else u32_be(high, low)


def _s32(high: int, low: int) -> int:
    """
    Growatt-safe signed 32-bit register read.

    Returns 0 when both registers are the 0xFFFF sentinel.
    """
    return 0 if (high == _SENTINEL and low == _SENTINEL) else s32_be(high, low)


# ---------------------------------------------------------------------------
# Vendor-level abstract driver
# ---------------------------------------------------------------------------

class GrowattBaseDriver(BaseDriver):
    """
    Abstract driver for all Growatt inverter families.

    Implements the vendor-level probe check (_is_growatt) and delegates the
    series-specific check to concrete subclasses (_probe_series).

    Subclasses must still implement:
      - driver_id (property)
      - _probe_series(ctx)
      - read_device_info(client, slave_id)
      - read_registers(client, slave_id)
    """

    def probe(self, ctx: ProbeContext) -> bool:
        """
        Two-tier probe: confirm vendor identity, then confirm series.

        Returns False immediately if the holding block is absent or the
        device does not look like a Growatt.  Never raises.
        """
        try:
            if not self._is_growatt(ctx):
                return False
            return self._probe_series(ctx)
        except Exception:
            return False

    def _is_growatt(self, ctx: ProbeContext) -> bool:
        """
        Vendor-level heuristic: does the ProbeContext look like a Growatt?

        Checks two things from the holding block (Regs 0–124):
        1. Firmware string (Regs 9–14) must decode to a dotted-numeric
           version pattern (e.g. '7.6.1.8').
        2. The upper 16 bits of the module_id (Regs 28–29) must map to a
           known Growatt series code.

        Returns False (never raises) if the holding block is absent or
        either heuristic fails.

        :param ctx: ProbeContext from the probe pipeline.
        """
        block = ctx.holding_block
        if block is None or len(block) < 122:
            return False

        # Check firmware version string (Regs 9–14).
        fw = ascii_regs(block[9:15])
        if not _FW_PATTERN.match(fw):
            return False

        # Check series code from module_id (Regs 28–29).
        module_id = u32_be(block[28], block[29])
        if module_id == 0:
            return False
        series_code = (module_id >> 16) & 0xFFFF
        if series_code not in GROWATT_SERIES:
            return False

        return True

    @abstractmethod
    def _probe_series(self, ctx: ProbeContext) -> bool:
        """
        Series-level check: which Growatt model family is this?

        Called only if _is_growatt() returned True.  Subclasses inspect the
        holding block for series-specific identifiers (series code from Regs
        28–29 and device type from Reg 121).

        Must return False (not raise) on any uncertainty.

        :param ctx: ProbeContext from the probe pipeline.
        """

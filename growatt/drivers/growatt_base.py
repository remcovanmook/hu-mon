"""
growatt.drivers.growatt_base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Intermediate abstract driver for all Growatt inverter families.

Implements the vendor-level portion of the two-tier probe:
  1. GrowattBaseDriver.probe() calls _is_growatt() first.
  2. If the device is confirmed as Growatt, it delegates to _probe_series()
     which subclasses implement to narrow down the model family.

Also provides Growatt-specific sentinel-aware register wrappers that call into
modbus.codec.  The 0xFFFF sentinel is a Growatt firmware convention
(registers hold 0xFFFF during night / sleep mode) and does not belong in the
generic codec.

Known Growatt series codes (Holding Regs 28-29, upper 16 bits of module_id):
"""

from abc import abstractmethod

from growatt.drivers.base import BaseDriver, ProbeContext
from modbus.codec import ascii_regs, s32_be, u16_be, u32_be

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
        import logging
        _log = logging.getLogger(__name__)
        try:
            if not self._is_growatt(ctx):
                _log.info("%s: _is_growatt() returned False", self.driver_id)
                return False
            result = self._probe_series(ctx)
            if not result:
                _log.info("%s: _probe_series() returned False", self.driver_id)
            return result
        except Exception as exc:
            _log.info("%s: probe() raised %s: %s", self.driver_id, type(exc).__name__, exc)
            return False

    def _is_growatt(self, ctx: ProbeContext) -> bool:
        """
        Vendor-level heuristic: does the ProbeContext look like a Growatt?

        Uses ctx.input_block (FC 04, registers 3000-3029) for identification.
        FC 03 holding registers 0-124 are also inverter registers but the
        status register is only available via FC 04.

        The check: FC 04 responded (input_block is not None) AND the status
        register at 3000 (input_block[0]) is in the Protocol II defined range
        0-10.  Any valid Growatt Protocol II inverter will satisfy this.

        Returns False (never raises) on any uncertainty.

        :param ctx: ProbeContext from the probe pipeline.
        """
        import logging
        _log = logging.getLogger(__name__)

        if 4 not in ctx.supported_fcs:
            _log.info("_is_growatt: FC 04 not supported")
            return False

        if ctx.input_block is None:
            _log.info("_is_growatt: input_block (FC04 3000-3029) is None")
            return False

        status = ctx.input_block[0]
        if status > 10:
            _log.info("_is_growatt: status register 3000 = %d is out of range [0,10]", status)
            return False

        _log.info("_is_growatt: OK — status=0x%04X FC04 3000-3029 present", status)
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

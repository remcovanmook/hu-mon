"""
growatt.drivers.codec
~~~~~~~~~~~~~~~~~~~~~
Vendor-neutral Modbus register type library.

Provides conversion functions for every standard Modbus data type in both
big-endian and little-endian register ordering.  No device-specific logic
(sentinels, scaling, model decoding) belongs here — keep those concerns in
the driver that owns them.

Naming convention:
    <type><width>_<endianness>(...)
    e.g. u16_be, s32_le, float32_be, ascii_regs
"""

import struct


# ---------------------------------------------------------------------------
# 16-bit integers
# ---------------------------------------------------------------------------

def u16_be(reg: int) -> int:
    """
    16-bit unsigned integer from a single Modbus register.

    Modbus registers are natively 16-bit big-endian, so this is a no-op
    type assertion — the value is returned as-is after masking to 16 bits.
    """
    return reg & 0xFFFF


def s16_be(reg: int) -> int:
    """
    16-bit signed integer from a single Modbus register (two's complement,
    big-endian).  Values above 0x7FFF are interpreted as negative.
    """
    val = reg & 0xFFFF
    return val - 0x10000 if val > 0x7FFF else val


def u16_le(reg: int) -> int:
    """
    16-bit unsigned integer from a single register whose two bytes are in
    little-endian order (low byte first).  Swaps the two bytes of the
    register value.
    """
    val = reg & 0xFFFF
    return ((val & 0x00FF) << 8) | ((val & 0xFF00) >> 8)


def s16_le(reg: int) -> int:
    """
    16-bit signed integer from a byte-swapped (little-endian) register.
    Applies byte swap then interprets as two's complement.
    """
    val = u16_le(reg)
    return val - 0x10000 if val > 0x7FFF else val


# ---------------------------------------------------------------------------
# 32-bit integers
# ---------------------------------------------------------------------------

def u32_be(high: int, low: int) -> int:
    """
    32-bit unsigned integer from two consecutive registers in big-endian
    register order (high register first, low register second).

    This is the register ordering used by Growatt and most IEC 61850 devices.
    """
    return ((high & 0xFFFF) << 16) | (low & 0xFFFF)


def s32_be(high: int, low: int) -> int:
    """
    32-bit signed integer from two consecutive registers in big-endian
    register order (high register first).  Interprets the combined value
    as two's complement.
    """
    val = u32_be(high, low)
    return val - 0x100000000 if val > 0x7FFFFFFF else val


def u32_le(low: int, high: int) -> int:
    """
    32-bit unsigned integer from two consecutive registers in little-endian
    register order (low register first, high register second).

    Used by some Schneider / Modicon devices.
    """
    return ((high & 0xFFFF) << 16) | (low & 0xFFFF)


def s32_le(low: int, high: int) -> int:
    """
    32-bit signed integer from two consecutive registers in little-endian
    register order (low register first).  Interprets the combined value
    as two's complement.
    """
    val = u32_le(low, high)
    return val - 0x100000000 if val > 0x7FFFFFFF else val


# ---------------------------------------------------------------------------
# IEEE 754 floats
# ---------------------------------------------------------------------------

def float32_be(high: int, low: int) -> float:
    """
    IEEE 754 single-precision float from two consecutive registers in
    big-endian register order (high register first).

    The two 16-bit register values are packed into 4 bytes and interpreted
    as a 32-bit float.
    """
    raw = struct.pack('>HH', high & 0xFFFF, low & 0xFFFF)
    return struct.unpack('>f', raw)[0]


def float32_le(low: int, high: int) -> float:
    """
    IEEE 754 single-precision float from two consecutive registers in
    little-endian register order (low register first).

    Used by some SMA and ABB inverters.
    """
    raw = struct.pack('>HH', high & 0xFFFF, low & 0xFFFF)
    return struct.unpack('>f', raw)[0]


# ---------------------------------------------------------------------------
# String
# ---------------------------------------------------------------------------

def ascii_regs(reg_list: list) -> str:
    """
    Decode a list of U16 Modbus registers as packed ASCII.

    Each register contributes two bytes (big-endian: high byte first).
    Null bytes and non-printable characters are stripped from the result.

    :param reg_list: List of raw register integers.
    :returns: Decoded, stripped ASCII string.
    """
    buf = bytearray()
    for reg in reg_list:
        buf.extend((reg & 0xFFFF).to_bytes(2, 'big'))
    return ''.join(c for c in buf.decode('ascii', errors='ignore') if c.isprintable()).strip()

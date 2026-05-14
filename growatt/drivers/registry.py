"""
growatt.drivers.registry
~~~~~~~~~~~~~~~~~~~~~~~~
Device driver registry and the five-stage probe pipeline.

Probe pipeline (runs once at startup, not on reconnect)
-------------------------------------------------------
Stage 1 -- Slave ID discovery
    Tries candidate slave IDs in order.  First to respond wins.

Stage 2 -- Function code support
    Tests FC 03 (holding) and FC 04 (input) individually.  Records which
    codes are available; drivers that require an absent FC are skipped.

Stage 3 -- Inverter holding block (FC 03, 0-124)
    Inverter FC03 holding registers accessed directly via the RS485-to-TCP
    gateway.  Cached for drivers that read firmware / device_type from this
    range; not used for primary VPP identification.

Stage 3b -- Inverter input block (FC 04, 3000-3029)
    Inverter FC04 input registers (Protocol II address space).  Used by
    GrowattBaseDriver to confirm vendor identity via the status register.

Stage 3c -- VPP DTC + Protocol Version (FC 03, 30000 + 30099)
    Reads the full 100-register Basic Parameter block.  DTC from 30000 is
    used for model metadata (series, phases, has_eps).  Protocol Version from
    30099 (e.g. 202 = V2.02) is the primary identifier: a value in 200-299
    confirms VPP capability and is stored in ctx.vpp_protocol_version.
    ctx.vpp_dtc is retained for use by GrowattVppDriver._probe_series().

Stage 4 -- Driver matching
    Iterates DRIVER_REGISTRY in order.  Returns the first driver whose
    probe() returns True.

Adding a new driver
-------------------
1. Implement BaseDriver (or GrowattBaseDriver for Growatt devices).
2. Append the class to DRIVER_REGISTRY below, in probe-priority order.
"""

import logging
from typing import Optional, Tuple

from growatt.drivers.base import BaseDriver, ProbeContext
from growatt.drivers.growatt_mod_hu.driver import GrowattModHuDriver
from growatt.drivers.growatt_vpp.driver import GrowattVppDriver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Slave IDs to probe, in priority order.
# ---------------------------------------------------------------------------
_SLAVE_ID_CANDIDATES = [1, 2, 3, 247]

# ---------------------------------------------------------------------------
# Chunk sizes to attempt for the holding block read, largest first.
# ---------------------------------------------------------------------------
_BLOCK_CHUNK_SIZES = [125, 64, 32, 16]

# ---------------------------------------------------------------------------
# Driver registry -- probe priority order matters.
# VPP driver first: takes precedence when DTC register 30000 responds.
# GrowattModHuDriver is the fallback for older firmware without VPP.
# ---------------------------------------------------------------------------
DRIVER_REGISTRY: list = [
    GrowattVppDriver,
    GrowattModHuDriver,
]


def _discover_slave_id(client) -> Optional[int]:
    """
    Attempt to find a responding Modbus slave by reading one holding register
    from each candidate slave ID.

    :param client: Active pymodbus ModbusTcpClient.
    :returns: The first slave ID that responds, or None if none respond.
    """
    for slave_id in _SLAVE_ID_CANDIDATES:
        try:
            r = client.read_holding_registers(0, count=1, device_id=slave_id)
            if not r.isError():
                logger.info("Slave ID %d responded", slave_id)
                return slave_id
        except Exception as exc:
            logger.debug("Slave ID %d: %s", slave_id, exc)
    return None


def _detect_function_codes(client, slave_id: int) -> set:
    """
    Determine which Modbus function codes the device supports.

    Tests FC 03 (Read Holding Registers) and FC 04 (Read Input Registers).

    :param client:   Active pymodbus ModbusTcpClient.
    :param slave_id: Confirmed slave address.
    :returns: Set of integer FC numbers that responded without error.
    """
    supported = set()
    try:
        r = client.read_holding_registers(0, count=1, device_id=slave_id)
        if not r.isError():
            supported.add(3)
            logger.debug("FC 03 (holding) supported")
    except Exception as exc:
        logger.debug("FC 03 not available: %s", exc)

    try:
        r = client.read_input_registers(3000, count=1, device_id=slave_id)
        if not r.isError():
            supported.add(4)
            logger.debug("FC 04 (input) supported")
    except Exception as exc:
        logger.debug("FC 04 not available: %s", exc)

    return supported


def _read_holding_block(client, slave_id: int) -> Tuple[Optional[list], int]:
    """
    Read Holding Registers 0-124 in chunks, falling back to smaller chunk
    sizes if the device rejects larger requests.

    The successful chunk size is itself a device capability tell (e.g. a
    device accepting only 16 registers per request is more constrained than
    one accepting 125).

    :param client:   Active pymodbus ModbusTcpClient.
    :param slave_id: Confirmed slave address.
    :returns: Tuple of (register_list_or_None, max_chunk_size_or_0).
    """
    target_end = 125  # Read registers 0-124 inclusive.
    max_chunk = 0

    # Determine the largest accepted chunk size.
    for chunk_size in _BLOCK_CHUNK_SIZES:
        try:
            r = client.read_holding_registers(0, count=chunk_size, device_id=slave_id)
            if not r.isError():
                max_chunk = chunk_size
                logger.info("Holding block chunk size: %d registers", max_chunk)
                break
        except Exception as exc:
            logger.debug("Chunk size %d rejected: %s", chunk_size, exc)

    if max_chunk == 0:
        logger.warning("Could not read holding block in any chunk size")
        return None, 0

    # Read remaining registers using the confirmed chunk size.
    block = []
    addr = 0
    while addr < target_end:
        count = min(max_chunk, target_end - addr)
        try:
            r = client.read_holding_registers(addr, count=count, device_id=slave_id)
            if r.isError():
                logger.warning("Holding block read failed at addr %d", addr)
                return None, max_chunk
            block.extend(r.registers)
        except Exception as exc:
            logger.warning("Holding block read exception at addr %d: %s", addr, exc)
            return None, max_chunk
        addr += count

    return block, max_chunk


def auto_select(
    client,
    force_driver_id: Optional[str] = None,
) -> Tuple[BaseDriver, int, ProbeContext]:
    """
    Run the probe pipeline and return the matching driver, slave ID, and
    ProbeContext.

    Stages 1-3 always run (needed to establish slave_id and ProbeContext).
    Stage 4 (driver matching) is skipped if force_driver_id is given.

    :param client:          Active pymodbus ModbusTcpClient.
    :param force_driver_id: If set, skip registry matching and use this
                            driver ID directly.  Raises ValueError if the
                            ID is not in DRIVER_REGISTRY.
    :returns: (driver_instance, slave_id, ctx)
    :raises RuntimeError: If no slave responds or no driver matches.
    """
    # Stage 1: Slave ID
    slave_id = _discover_slave_id(client)
    if slave_id is None:
        raise RuntimeError(
            f"No Modbus device responded on slave IDs {_SLAVE_ID_CANDIDATES}"
        )

    # Stage 2: Function codes
    supported_fcs = _detect_function_codes(client, slave_id)
    logger.info("Supported function codes: %s", sorted(supported_fcs))

    # Stage 3: Inverter FC03 holding block (0-124).
    # All FC03 reads go directly to the inverter via the RS485-to-TCP gateway.
    # Cached for drivers that need firmware / device_type from this range.
    holding_block, max_block_size = None, 0
    if 3 in supported_fcs:
        holding_block, max_block_size = _read_holding_block(client, slave_id)
        if holding_block:
            non_zero = {i: v for i, v in enumerate(holding_block) if v != 0}
            logger.debug(
                "FC03 0-124 non-zero: %s",
                {f"reg{k}": f"0x{v:04X}({v})" for k, v in sorted(non_zero.items())},
            )

    # Stage 3b: Inverter FC04 input block (Protocol II, 3000-3029).
    # 30 registers are enough for status + PV identification.
    input_block = None
    if 4 in supported_fcs:
        try:
            r = client.read_input_registers(3000, count=30, device_id=slave_id)
            if not r.isError():
                input_block = r.registers
                logger.info("Input block 3000-3029: %d registers read", len(input_block))
                non_zero_in = {3000 + i: v for i, v in enumerate(input_block) if v != 0}
                logger.debug("Input block non-zero: %s",
                             {f"reg{k}": f"0x{v:04X}({v})" for k, v in sorted(non_zero_in.items())})
            else:
                logger.warning("Input block 3000-3029 read error: %s", r)
        except Exception as exc:
            logger.warning("Input block 3000-3029 exception: %s", exc)

    # Stage 3c: VPP DTC (FC 03, register 30000) and Protocol Version (30099).
    # Reading the full 100-register block saves a round-trip and gives us both.
    vpp_dtc = None
    vpp_protocol_version = None
    if 3 in supported_fcs:
        try:
            r = client.read_holding_registers(30000, count=100, device_id=slave_id)
            if not r.isError():
                dtc = r.registers[0]
                ver = r.registers[99]
                if dtc != 0:
                    vpp_dtc = dtc
                    logger.info("VPP DTC: %d (0x%04X)", vpp_dtc, vpp_dtc)
                if 200 <= ver <= 299:
                    vpp_protocol_version = ver
                    logger.info("VPP Protocol Version: %d (V%d.%02d)", ver, ver // 100, ver % 100)
                else:
                    logger.debug("VPP 30099=%d -- not a plausible VPP version", ver)
                non_zero_vpp = {30000 + i: v for i, v in enumerate(r.registers) if v != 0}
                logger.debug(
                    "VPP block 30000-30099 non-zero: %s",
                    {f"reg{k}": f"0x{v:04X}({v})" for k, v in sorted(non_zero_vpp.items())},
                )
            else:
                logger.debug("VPP block 30000-30099 returned error")
        except Exception as exc:
            logger.debug("VPP block read failed: %s", exc)

    # Stage 3d: US-variant probe -- only for MIN TL-XH (DTC 5100).
    # FC03 3125 is the start of the US-specific extension block.  All other
    # model families have a fixed register map; only 5100 has two variants.
    proto_ii_us_available = False
    if 3 in supported_fcs and vpp_dtc == 5100:
        try:
            r = client.read_holding_registers(3125, count=1, device_id=slave_id)
            if not r.isError():
                proto_ii_us_available = True
                logger.info("Proto II US extension (FC03 3125) confirmed for DTC 5100")
        except Exception as exc:
            logger.debug("US probe failed: %s", exc)

    ctx = ProbeContext(
        slave_id=slave_id,
        supported_fcs=supported_fcs,
        holding_block=holding_block,
        max_block_size=max_block_size,
        input_block=input_block,
        vpp_dtc=vpp_dtc,
        vpp_protocol_version=vpp_protocol_version,
        proto_ii_us_available=proto_ii_us_available,
    )

    # Stage 4: Driver matching
    if force_driver_id is not None:
        for driver_cls in DRIVER_REGISTRY:
            instance = driver_cls()
            if instance.driver_id == force_driver_id:
                logger.info("Reusing pre-selected driver: %s", force_driver_id)

                return instance, slave_id, ctx
        raise ValueError(
            f"Driver '{force_driver_id}' not found in registry. "
            f"Available: {[d().driver_id for d in DRIVER_REGISTRY]}"
        )

    for driver_cls in DRIVER_REGISTRY:
        instance = driver_cls()
        if instance.probe(ctx):
            logger.info("Auto-selected driver: %s (slave_id=%d)", instance.driver_id, slave_id)
            return instance, slave_id, ctx

    raise RuntimeError(
        f"No driver matched the device on slave_id={slave_id}. "
        f"Tried: {[d().driver_id for d in DRIVER_REGISTRY]}"
    )

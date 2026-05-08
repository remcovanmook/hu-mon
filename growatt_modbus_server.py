"""
growatt_modbus_server.py
~~~~~~~~~~~~~~~~~~~~~~~~
Modbus TCP proxy server.

Exposes a local Modbus TCP endpoint that mirrors the live register state
collected from the real inverter.  Slave ID, supported function codes, and
register address ranges are sourced from the selected driver's proxy_config
property rather than hardcoded here.

ProxyConfig structure:
    {slave_id: {function_code: [(start_address, count), ...]}}

Third-party systems (Home Assistant, EMS, Victron Cerbo) can poll this proxy
without connecting directly to the ShineWifi-X2 datalogger, which only supports
one concurrent Modbus TCP connection.
"""

import json
import logging

from pymodbus.simulator import SimDevice, SimData, DataType
from pymodbus.server import StartTcpServer

from growatt.drivers.base import ProxyConfig
from growatt.store import GrowattStore

logger = logging.getLogger("growatt_modbus_server")


def run(store: GrowattStore, proxy_cfg: ProxyConfig, port: int = 5020):
    """
    Start the Modbus TCP proxy server (blocking).

    Iterates proxy_cfg.address_map to build one SimDevice per slave ID, with
    one SimData block per (function_code, address_range) pair.  On each
    incoming read request the update_registers callback injects the latest
    cached register snapshot from the store.

    :param store:     GrowattStore instance providing the latest register cache.
    :param proxy_cfg: ProxyConfig from the selected driver.
                      Shape: {slave_id: {fc: [(start, count), ...]}}
    :param port:      TCP port to listen on (default: 5020).
    """
    devices = []

    for slave_id, fc_map in proxy_cfg.address_map.items():
        sim_blocks = []
        for fc, ranges in fc_map.items():
            for start, count in ranges:
                sim_blocks.append(
                    SimData(
                        address=start,
                        count=count,
                        values=[0] * count,
                        datatype=DataType.REGISTERS,
                    )
                )

        async def update_registers(func_code, start_address, address, count, registers, values):
            """
            PyModbus SimDevice callback invoked on every Modbus read request.

            On a read (values is None), fetches the latest JSON register
            snapshot from the store and injects the relevant values into the
            simulator's memory block for the requested address range.
            """
            if values is not None:
                return None  # Write request — not handled.

            raw_bytes = store.get_latest_registers()
            if not raw_bytes:
                return None

            try:
                cache = json.loads(raw_bytes.decode("utf-8"))
                for i in range(count):
                    reg_addr = address + i
                    offset = reg_addr - start_address
                    if 0 <= offset < len(registers):
                        registers[offset] = cache.get(str(reg_addr), 0)
            except Exception as exc:
                logger.error("Failed to decode register cache: %s", exc)

            return None

        devices.append(
            SimDevice(
                id=slave_id,
                simdata=sim_blocks,
                action=update_registers,
            )
        )

    # Log the full address map for operator visibility.
    for slave_id, fc_map in proxy_cfg.address_map.items():
        for fc, ranges in fc_map.items():
            addr_spans = [(s, s + c - 1) for s, c in ranges]
            logger.info(
                "Proxy slave_id=%d  FC %02d  ranges=%s",
                slave_id, fc, addr_spans,
            )

    logger.info("Starting Modbus TCP proxy on 0.0.0.0:%d", port)

    # pymodbus StartTcpServer accepts a single device or a list.
    context = devices[0] if len(devices) == 1 else devices
    StartTcpServer(context=context, address=("0.0.0.0", port))

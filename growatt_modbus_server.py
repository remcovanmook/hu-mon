"""
growatt_modbus_server.py
~~~~~~~~~~~~~~~~~~~~~~~~
Modbus TCP proxy server.

Exposes a local Modbus TCP endpoint that mirrors the live register state
collected from the real inverter.  Slave ID, supported function codes, and
register address ranges are sourced from the selected driver's proxy_config
property rather than hardcoded here.

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

    Builds a SimDevice whose address ranges and slave ID come from the driver's
    ProxyConfig.  On each incoming read request the update_registers callback
    injects the latest cached register snapshot from the store.

    :param store:     GrowattStore instance providing the latest register cache.
    :param proxy_cfg: ProxyConfig from the selected driver (slave_id, FCs, ranges).
    :param port:      TCP port to listen on (default: 5020).
    """
    # Build one SimData block per segment range declared by the driver.
    sim_blocks = [
        SimData(
            address=start,
            count=count,
            values=[0] * count,
            datatype=DataType.REGISTERS,
        )
        for start, count in proxy_cfg.ranges
    ]

    async def update_registers(func_code, start_address, address, count, registers, values):
        """
        PyModbus SimDevice callback invoked on every Modbus read request.

        On a read (values is None), fetches the latest JSON register snapshot
        from the store and injects the relevant values into the simulator's
        memory block for the requested address range.
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

    device = SimDevice(
        id=proxy_cfg.slave_id,
        simdata=sim_blocks,
        action=update_registers,
    )

    logger.info(
        "Starting Modbus TCP proxy on 0.0.0.0:%d (slave_id=%d, ranges=%s)",
        port,
        proxy_cfg.slave_id,
        [(s, s + c - 1) for s, c in proxy_cfg.ranges],
    )
    StartTcpServer(context=device, address=("0.0.0.0", port))

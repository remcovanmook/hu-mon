"""
growatt_collector.py
~~~~~~~~~~~~~~~~~~~~
Telemetry collector entry point.

Connects to a Growatt ShineWifi-X2 datalogger, auto-detects the device using
the driver probe pipeline, reads static metadata once, then polls telemetry at
a 5-second cadence and writes results to the GrowattStore.

The collector deliberately contains no register addresses, segment boundaries,
or device-specific logic — all of that lives in growatt.drivers.
"""

import argparse
import logging
import time

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusIOException

from growatt.drivers.registry import auto_select
from growatt.store import GrowattStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("growatt_collector")

_POLL_INTERVAL = 5.0   # seconds


def poll_datalogger(ip: str, port: int, store: GrowattStore, driver_id: str = None):
    """
    Main collection loop.

    Connects to the datalogger, runs the probe pipeline once to select a driver
    and discover the slave ID, reads static device metadata, then enters a
    continuous 5-second poll loop.

    The driver and slave_id are sticky for the session — they are not re-selected
    on reconnect.  Only the TCP socket is re-established after a connection drop.

    :param ip:        Datalogger IP address.
    :param port:      Modbus TCP port (default 502).
    :param store:     GrowattStore instance for data persistence.
    :param driver_id: Optional driver ID to force (skips auto-detection in Stage 4).
    """
    client = ModbusTcpClient(ip, port=port)
    client.connect()

    logger.info("Running probe pipeline against %s:%d", ip, port)
    driver, slave_id, _ctx = auto_select(client, force_driver_id=driver_id)
    logger.info("Driver: %s  Slave ID: %d", driver.driver_id, slave_id)

    device_info = driver.read_device_info(client, slave_id)
    logger.info(
        "Device: %s  Serial: %s  FW: %s  Rated: %dW  Battery: %.1f kWh",
        device_info.model,
        device_info.serial,
        device_info.firmware,
        device_info.rated_power_w,
        device_info.bat_nominal_kwh,
    )

    while True:
        start_time = time.time()
        try:
            if not client.is_socket_open():
                logger.info("Reconnecting to %s:%d (driver sticky: %s)", ip, port, driver.driver_id)
                client.connect()

            reading = driver.read_registers(client, slave_id)

            # Annotate reading with static device metadata.
            reading.inverter_model = device_info.model
            reading.inverter_serial = device_info.serial
            reading.inverter_firmware = device_info.firmware
            reading.rated_power_w = device_info.rated_power_w
            reading.bat_nominal_kwh = device_info.bat_nominal_kwh

            store.insert(reading)

        except (ConnectionException, ConnectionResetError, OSError) as e:
            logger.warning("Connection dropped (%s). Reconnecting...", type(e).__name__)
            client.close()
        except ModbusIOException as e:
            logger.error("Modbus read error: %s", e)
            client.close()
        except Exception:
            logger.exception("Unexpected error in polling loop")
            client.close()

        elapsed = time.time() - start_time
        sleep_time = max(0.0, _POLL_INTERVAL - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)


def run(ip: str, port: int, db_path: str, driver_id: str = None):
    """
    Initialise the store and start the collection loop.

    :param ip:        Datalogger IP address.
    :param port:      Modbus TCP port.
    :param db_path:   Path to the SQLite database file.
    :param driver_id: Optional forced driver ID.
    """
    store = GrowattStore(db_path)
    logger.info("Starting collector targeting %s:%d", ip, port)
    poll_datalogger(ip, port, store, driver_id=driver_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Growatt telemetry collector")
    parser.add_argument("--ip", required=True, help="Datalogger IP address")
    parser.add_argument("--port", type=int, default=502, help="Modbus TCP port (default: 502)")
    parser.add_argument("--db", default="growatt.db", help="SQLite database path")
    parser.add_argument(
        "--driver",
        default=None,
        metavar="DRIVER_ID",
        help=(
            "Force a specific driver by ID (e.g. growatt_mod_hu). "
            "Skips Stage 4 auto-detection; Stages 1-3 still run to establish slave ID. "
            "Available drivers: see growatt/drivers/registry.py DRIVER_REGISTRY."
        ),
    )
    args = parser.parse_args()
    run(args.ip, args.port, args.db, driver_id=args.driver)

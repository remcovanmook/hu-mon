import argparse
import logging
import threading
import time

from growatt.drivers.registry import auto_select
from growatt.store import GrowattStore
from pymodbus.client import ModbusTcpClient
from growatt_collector import poll_datalogger
from growatt_modbus_server import run as run_modbus_server
from dashboard.app import create_app

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
)
logger = logging.getLogger("growatt_server")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-ip", required=True, help="Datalogger IP")
    parser.add_argument("--datalogger-port", type=int, default=502)
    parser.add_argument("--proxy-port", type=int, default=5020)
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--db", default="growatt.db")
    
    # MQTT Options
    parser.add_argument("--mqtt-host", default="")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-user", default="")
    parser.add_argument("--mqtt-pass", default="")
    
    # InfluxDB Options
    parser.add_argument("--influx-url", default="")
    parser.add_argument("--influx-token", default="")
    parser.add_argument("--influx-org", default="")
    parser.add_argument("--influx-bucket", default="")
    parser.add_argument("--influx-db", default="growatt")

    # Driver override (optional — auto-detected by default)
    parser.add_argument(
        "--driver",
        default=None,
        metavar="DRIVER_ID",
        help="Force a specific driver ID (e.g. growatt_mod_hu). Default: auto-detect.",
    )

    args = parser.parse_args()

    store = GrowattStore(args.db)

    # Run the probe pipeline once to select the driver and get the proxy config.
    # The collector will re-use the same driver internally (sticky session).
    probe_client = ModbusTcpClient(args.device_ip, port=args.datalogger_port)
    probe_client.connect()
    driver, slave_id = auto_select(probe_client, force_driver_id=args.driver)
    proxy_cfg = driver.proxy_config
    probe_client.close()
    logger.info("Driver: %s  Proxy ranges: %s", driver.driver_id, proxy_cfg.ranges)

    # 1. Start Collector thread
    threading.Thread(
        target=poll_datalogger,
        args=(args.device_ip, args.datalogger_port, store),
        kwargs={"driver_id": driver.driver_id},
        daemon=True,
        name="growatt-collector"
    ).start()
    logger.info("Collector thread started targeting %s:%d", args.device_ip, args.datalogger_port)

    # 2. Start Modbus proxy server thread
    threading.Thread(
        target=run_modbus_server,
        args=(store, proxy_cfg, args.proxy_port),
        daemon=True,
        name="growatt-proxy"
    ).start()
    logger.info("Modbus proxy server started on port %d (slave_id=%d)", args.proxy_port, proxy_cfg.slave_id)

    # 3. Start MQTT Exporter (Optional)
    if args.mqtt_host:
        from growatt.mqtt_publisher import run as run_mqtt
        threading.Thread(
            target=run_mqtt,
            args=(store, args.mqtt_host, args.mqtt_port, args.mqtt_user, args.mqtt_pass),
            daemon=True,
            name="growatt-mqtt"
        ).start()

    # 4. Start InfluxDB Exporter (Optional)
    if args.influx_url:
        from growatt.influx_publisher import run_influx_loop
        threading.Thread(
            target=run_influx_loop,
            args=(store, args.influx_url, args.influx_token, args.influx_org, args.influx_bucket, args.influx_db),
            daemon=True,
            name="growatt-influx"
        ).start()
        logger.info("InfluxDB exporter started targeting %s", args.influx_url)

    # 5. Run Flask dashboard blocking in main thread (matching hegg-emon pattern)
    application = create_app(store)
    logger.info("Dashboard and metrics on http://0.0.0.0:%d/", args.http_port)
    try:
        application.run(
            host="0.0.0.0", port=args.http_port, debug=False,
            use_reloader=False, threaded=True
        )
    except KeyboardInterrupt:
        logger.info("Shutting down")

if __name__ == "__main__":
    main()

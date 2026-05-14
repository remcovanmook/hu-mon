import argparse
import logging
import os
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
    """
    Growatt all-in-one server entry point.

    Starts the telemetry collector, optional Modbus proxy, optional MQTT
    and InfluxDB exporters, and the Flask dashboard.

    Configuration is read from environment variables (typically loaded via
    /etc/default/growatt by the init system).  Command-line arguments
    override env vars when provided.
    """
    parser = argparse.ArgumentParser(
        description="Growatt Modbus Proxy & Telemetry Server"
    )
    parser.add_argument("--device-ip",
        default=os.environ.get("GROWATT_DEVICE_IP"),
        help="Datalogger IP address (env: GROWATT_DEVICE_IP)")
    parser.add_argument("--datalogger-port", type=int,
        default=int(os.environ.get("GROWATT_DATALOGGER_PORT", "502")),
        help="Modbus TCP port on the datalogger (env: GROWATT_DATALOGGER_PORT, default: 502)")
    parser.add_argument("--proxy-port", type=int,
        default=int(os.environ.get("GROWATT_PROXY_PORT", "5020")),
        help="Modbus proxy listen port, 0 to disable (env: GROWATT_PROXY_PORT, default: 5020)")
    parser.add_argument("--http-port", type=int,
        default=int(os.environ.get("GROWATT_HTTP_PORT", "8081")),
        help="Dashboard HTTP port (env: GROWATT_HTTP_PORT, default: 8081)")
    parser.add_argument("--db",
        default=os.environ.get("GROWATT_DB", "growatt.db"),
        help="SQLite database path (env: GROWATT_DB, default: growatt.db)")
    
    # MQTT Options
    parser.add_argument("--mqtt-host",
        default=os.environ.get("GROWATT_MQTT_HOST", ""),
        help="MQTT broker host, empty to disable (env: GROWATT_MQTT_HOST)")
    parser.add_argument("--mqtt-port", type=int,
        default=int(os.environ.get("GROWATT_MQTT_PORT", "1883")),
        help="MQTT broker port (env: GROWATT_MQTT_PORT, default: 1883)")
    parser.add_argument("--mqtt-user",
        default=os.environ.get("GROWATT_MQTT_USER", ""),
        help="MQTT username (env: GROWATT_MQTT_USER)")
    parser.add_argument("--mqtt-pass",
        default=os.environ.get("GROWATT_MQTT_PASS", ""),
        help="MQTT password (env: GROWATT_MQTT_PASS)")
    parser.add_argument("--mqtt-topic-prefix",
        default=os.environ.get("GROWATT_MQTT_TOPIC_PREFIX", ""),
        help="MQTT topic prefix (env: GROWATT_MQTT_TOPIC_PREFIX, default: growatt/<serial>/)")
    
    # InfluxDB Options
    parser.add_argument("--influx-url",
        default=os.environ.get("GROWATT_INFLUX_URL", ""),
        help="InfluxDB URL, empty to disable (env: GROWATT_INFLUX_URL)")
    parser.add_argument("--influx-token",
        default=os.environ.get("GROWATT_INFLUX_TOKEN", ""),
        help="InfluxDB auth token (env: GROWATT_INFLUX_TOKEN)")
    parser.add_argument("--influx-org",
        default=os.environ.get("GROWATT_INFLUX_ORG", ""),
        help="InfluxDB organisation (env: GROWATT_INFLUX_ORG)")
    parser.add_argument("--influx-bucket",
        default=os.environ.get("GROWATT_INFLUX_BUCKET", ""),
        help="InfluxDB bucket (env: GROWATT_INFLUX_BUCKET)")
    parser.add_argument("--influx-db",
        default=os.environ.get("GROWATT_INFLUX_DB", "growatt"),
        help="InfluxDB v1 database name (env: GROWATT_INFLUX_DB, default: growatt)")

    # Driver override (optional — auto-detected by default)
    parser.add_argument("--driver",
        default=os.environ.get("GROWATT_DRIVER"),
        metavar="DRIVER_ID",
        help="Force a specific driver ID (env: GROWATT_DRIVER, default: auto-detect)")

    args = parser.parse_args()

    if not args.device_ip:
        parser.error("Device IP is required. Set GROWATT_DEVICE_IP or pass --device-ip.")

    store = GrowattStore(args.db)

    # Run the probe pipeline once to select the driver and get the proxy config.
    # The collector will re-use the same driver internally (sticky session).
    probe_client = ModbusTcpClient(args.device_ip, port=args.datalogger_port)
    probe_client.connect()
    driver, slave_id, ctx = auto_select(probe_client, force_driver_id=args.driver)
    proxy_cfg = driver.proxy_config(slave_id, ctx)
    probe_client.close()
    logger.info("Driver: %s  Proxy address_map: %s", driver.driver_id, proxy_cfg.address_map)

    # 1. Start Collector thread
    threading.Thread(
        target=poll_datalogger,
        args=(args.device_ip, args.datalogger_port, store),
        kwargs={"driver_id": driver.driver_id},
        daemon=True,
        name="growatt-collector"
    ).start()
    logger.info("Collector thread started targeting %s:%d", args.device_ip, args.datalogger_port)

    # 2. Start Modbus proxy server thread (optional — disabled when port is 0)
    if args.proxy_port:
        threading.Thread(
            target=run_modbus_server,
            args=(store, proxy_cfg, args.proxy_port),
            daemon=True,
            name="growatt-proxy"
        ).start()
        logger.info("Modbus proxy server started on port %d (slave_id=%d)", args.proxy_port, slave_id)
    else:
        logger.info("Modbus proxy disabled (port=0)")

    # 3. Start MQTT Exporter (Optional)
    if args.mqtt_host:
        from growatt.mqtt_publisher import run as run_mqtt
        threading.Thread(
            target=run_mqtt,
            args=(store, args.mqtt_host, args.mqtt_port, args.mqtt_user, args.mqtt_pass,
                  args.mqtt_topic_prefix),
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


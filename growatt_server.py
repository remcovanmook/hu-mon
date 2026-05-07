import argparse
import logging
import threading
import time

from growatt.store import GrowattStore
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
    args = parser.parse_args()

    store = GrowattStore(args.db)

    # 1. Start Collector thread
    threading.Thread(
        target=poll_datalogger,
        args=(args.device_ip, args.datalogger_port, store),
        daemon=True,
        name="growatt-collector"
    ).start()
    logger.info("Collector thread started targeting %s:%d", args.device_ip, args.datalogger_port)

    # 2. Start Modbus proxy server thread
    threading.Thread(
        target=run_modbus_server,
        args=(store, args.proxy_port),
        daemon=True,
        name="growatt-proxy"
    ).start()
    logger.info("Modbus proxy server started on port %d", args.proxy_port)

    # 3. Run Flask dashboard blocking in main thread (matching hegg-emon pattern)
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

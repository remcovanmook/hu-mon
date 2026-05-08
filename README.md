# Growatt Modbus Proxy

A resilient, high-performance Modbus TCP proxy and telemetry collector for the Growatt MOD 12KTL3-HU inverter (via ShineWifi-X2).

## Features
- **Strict 5s Polling:** Hardware-accurate telemetry extraction.
- **Aggressive Reconnect:** Instantly recovers from datalogger socket closures.
- **Hardware-Accurate Telemetry:** Extracts elusive metrics including APX battery data, EPS Backup power flows, and grid frequencies.
- **Thermal Visibility:** Integrates reverse-engineered register shifts to track Inverter and Boost temperatures live.
- **Web Dashboard:** A high-performance, live-updating frontend powered by Server-Sent Events (SSE). Features include responsive SVG sparklines, zero-filled historical extrapolation, EPS/Grid dynamic axis synchronization, and dark mode.
- **Transparent Proxy:** Mimics the inverter to allow third-party systems (like Home Assistant) to poll at unlimited frequencies without crashing the datalogger.
- **Prometheus Metrics:** Native `/metrics` endpoint for integration into Grafana stacks.
- **Tiered SQLite Backend:** Lock-free, WAL-mode database gracefully managing high-frequency rolling averages for 1-minute and 1-hour historical chart retention.

## Requirements
- Python 3.10+
- `pymodbus>=3.5.0`
- `flask>=3.0.0`

## Installation

```bash
# Clone the repository
git clone <repo_url>
cd growatt

# Create virtual environment 
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Running the Server

Start the full stack (Collector, Proxy, Dashboard, Metrics) by pointing it at your inverter's IP address:

```bash
.venv/bin/python growatt_server.py --device-ip <INVERTER_IP>
```

**Options:**
- `--device-ip`: (Required) The IP of your Growatt datalogger.
- `--datalogger-port`: Defaults to 502.
- `--proxy-port`: The port the local mimic proxy will listen on (default 5020).
- `--http-port`: The port for the web dashboard and metrics (default 8080).
- `--db`: SQLite database file (default `growatt.db`).

**MQTT Integration (Optional):**
- `--mqtt-host`: MQTT broker IP. (Requires `pip install aiomqtt`)
- `--mqtt-port`: MQTT broker port (default 1883).
- `--mqtt-user` / `--mqtt-pass`: Optional credentials.

**InfluxDB Integration (Optional):**
- `--influx-url`: Base URL of InfluxDB (e.g. `http://localhost:8086`).
- `--influx-token`, `--influx-org`, `--influx-bucket`: For InfluxDB v2.
- `--influx-db`: For InfluxDB v1 (default `growatt`).

## Testing

Run the test suite to verify Modbus parsing math and SQLite moving average logic:
```bash
.venv/bin/python -m unittest discover -s tests
```

To quickly test connectivity to your datalogger without launching the DB:
```bash
.venv/bin/python test_connection.py --ip <INVERTER_IP>
```

## Dashboard
- Navigate to `http://<HOST>:8080/` to view the live dynamic dashboard. 
- Navigate to `http://<HOST>:8080/metrics` for Prometheus scraping.

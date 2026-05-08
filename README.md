# Growatt Modbus Proxy

A Modbus TCP proxy and telemetry collector for the Growatt MOD 12KTL3-HU inverter (via ShineWifi-X2).

## Features
- **5s Polling:** Telemetry extraction.
- **Reconnect:** Recovers from datalogger socket closures.
- **Telemetry:** Extracts APX battery data, EPS Backup power flows, and grid frequencies.
- **Thermal Visibility:** Tracks Inverter and Boost temperatures.
- **Web Dashboard:** Frontend powered by Server-Sent Events (SSE). Features include SVG sparklines, historical extrapolation, EPS/Grid axis synchronization, and dark mode.
- **Transparent Proxy:** Mimics the inverter to allow third-party systems (like Home Assistant) to poll without querying the datalogger directly.
- **Prometheus Metrics:** Native `/metrics` endpoint.
- **SQLite Backend:** WAL-mode database managing rolling averages for 1-minute and 1-hour historical charts.

## Requirements
- Python 3.10+
- `pymodbus>=3.5.0`
- `flask>=3.0.0`

## Installation

```bash
# Clone the repository to /opt
sudo git clone https://github.com/remcovanmook/growatt /opt/growatt
cd /opt/growatt

# Create virtual environment 
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
```

Create the database directory and a system user:

```bash
sudo useradd -r -s /bin/false growatt
sudo mkdir -p /var/lib/growatt
sudo chown growatt:growatt /var/lib/growatt
sudo cp /opt/growatt/etc/default/growatt /etc/default/growatt
```

Edit `/etc/default/growatt` to set `GROWATT_DEVICE_IP` to your inverter's IP address.

## Running the Server

### Development (Single Command)

Start the full stack (Collector, Proxy, Dashboard, Metrics) manually:

```bash
.venv/bin/python growatt_server.py --device-ip <INVERTER_IP> --db db/growatt.db
```

### systemd (Recommended for Production)

Deploy the all-in-one daemon to run in the background:

```bash
sudo cp /opt/growatt/etc/systemd/growatt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now growatt
sudo systemctl status growatt
```

**Options for CLI/Environment overrides:**
- `GROWATT_DEVICE_IP` / `--device-ip`: (Required) The IP of your Growatt datalogger.
- `GROWATT_PROXY_PORT` / `--proxy-port`: Local proxy listening port (default 5020).
- `GROWATT_HTTP_PORT` / `--http-port`: Web dashboard/metrics port (default 8080).
- `GROWATT_DB` / `--db`: SQLite database file (default `growatt.db`).

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
- Navigate to `http://<HOST>:8080/` to view the dashboard. 
- Navigate to `http://<HOST>:8080/metrics` for Prometheus scraping.

# Growatt Proxy Architecture

This document describes the design and architecture of the Growatt Modbus Proxy & Telemetry Server.

## Core Philosophy
The architecture is inspired by the `hegg-emon` pattern. It focuses on absolute resilience against datalogger socket closures, high-fidelity data extraction at hardware-constrained intervals (5s), and tiered SQLite WAL-mode storage.

## Components

### 1. Collector (`growatt_collector.py`)
- **Role:** The high-frequency data ingester.
- **Timing:** Implements a strict 5-second cadence using execution-duration tracking (`max(0.0, 5.0 - elapsed)`).
- **Resilience:** ShineWifi dataloggers are notorious for aggressively closing idle sockets. The collector runs in a daemon thread, catches `ModbusIOException` or socket drops, and instantly triggers a reconnect loop.
- **Protocol:** Uses `pymodbus` to pull 29 critical hardware telemetry data points across 4 separate register segments to avoid unsupported large block reads. It coerces `0xFFFF` registers into valid zero values to handle night-mode sleep correctly.

### 2. Tiered Storage (`growatt/store.py`)
- **Role:** Thread-safe data persistence.
- **WAL Mode:** Write-Ahead Logging is enforced to allow the Flask frontend and Prometheus scraper to read from the DB without locking the high-frequency Collector thread.
- **Atomic Cache:** An in-memory JSON payload (`latest_registers`) is stored on every tick. This serves as the source of truth for the Modbus Proxy, preventing "torn reads" where half a segment might be updated while a client is polling.
- **Rollups (Moving Average):** Readings are inserted into the 5-second bucket. We use a mathematically correct weighted moving average query (`INSERT OR REPLACE INTO readings_5s ... (mean*n + new)/(n+1)`) to handle exactly-overlapping sub-second writes gracefully.

### 3. Modbus Proxy (`growatt_modbus_server.py`)
- **Role:** Third-party Integration.
- **Implementation:** Creates a local PyModbus TCP Server that mimics the Growatt MOD 12KTL3-HU. It maps the `latest_registers` JSON directly into a `ModbusSparseDataBlock`. 
- **Benefit:** Energy Management Systems (EMS) or Home Assistant can poll this proxy aggressively without hammering the physical datalogger, which would otherwise crash.

### 4. Flask Dashboard & Metrics (`dashboard/app.py` & `growatt_server.py`)
- **Role:** Real-time observability.
- **Dashboard:** A Server-Sent Events (SSE) `/stream` pushes JSON to a vanilla JS frontend rendering live power-flow graphs and MPPT PV strings without page reloads.
- **Metrics:** A native `/metrics` endpoint formats the `latest_reading` into Prometheus text syntax (`growatt_pv_total_w 400.0`) without requiring the heavy `prometheus_client` dependency.
- **Thread Model:** Matches the `hegg-emon` WSGI pattern. The daemon threads handle collection and proxying, while the main thread blocks on the robust Werkzeug WSGI server.

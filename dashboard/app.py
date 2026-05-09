import json
import logging
import time
from flask import Flask, Response, render_template, send_from_directory
from growatt.store import GrowattStore

logger = logging.getLogger("growatt_dashboard")


# ---------------------------------------------------------------------------
# Prometheus metric definitions
# Each entry: (field_name, prometheus_name, help_text, multiplier)
# multiplier lets us express stored units (e.g. 0.1 W) as base SI units (W).
# ---------------------------------------------------------------------------
_GAUGES = [
    # PV
    ("pv_total_w",   "growatt_pv_power_watts",          "Total PV input power",                   1),
    ("pv1_v",        "growatt_pv1_voltage_volts",        "PV string 1 voltage",                    1),
    ("pv1_a",        "growatt_pv1_current_amps",         "PV string 1 current",                    1),
    ("pv1_w",        "growatt_pv1_power_watts",          "PV string 1 power",                      1),
    ("pv2_v",        "growatt_pv2_voltage_volts",        "PV string 2 voltage",                    1),
    ("pv2_a",        "growatt_pv2_current_amps",         "PV string 2 current",                    1),
    ("pv2_w",        "growatt_pv2_power_watts",          "PV string 2 power",                      1),
    ("pv3_v",        "growatt_pv3_voltage_volts",        "PV string 3 voltage",                    1),
    ("pv3_a",        "growatt_pv3_current_amps",         "PV string 3 current",                    1),
    ("pv3_w",        "growatt_pv3_power_watts",          "PV string 3 power",                      1),
    ("pv4_v",        "growatt_pv4_voltage_volts",        "PV string 4 voltage",                    1),
    ("pv4_a",        "growatt_pv4_current_amps",         "PV string 4 current",                    1),
    ("pv4_w",        "growatt_pv4_power_watts",          "PV string 4 power",                      1),
    # Grid / AC
    ("grid_freq",       "growatt_grid_frequency_hz",       "Grid frequency",                         1),
    ("grid_l1_v",       "growatt_grid_l1_voltage_volts",   "Grid phase L1 voltage",                  1),
    ("grid_l1_a",       "growatt_grid_l1_current_amps",    "Grid phase L1 current",                  1),
    ("grid_l2_v",       "growatt_grid_l2_voltage_volts",   "Grid phase L2 voltage",                  1),
    ("grid_l2_a",       "growatt_grid_l2_current_amps",    "Grid phase L2 current",                  1),
    ("grid_l3_v",       "growatt_grid_l3_voltage_volts",   "Grid phase L3 voltage",                  1),
    ("grid_l3_a",       "growatt_grid_l3_current_amps",    "Grid phase L3 current",                  1),
    ("grid_ll_rs_v",    "growatt_grid_ll_rs_voltage_volts","Grid line voltage RS (L1-L2)",            1),
    ("grid_ll_st_v",    "growatt_grid_ll_st_voltage_volts","Grid line voltage ST (L2-L3)",            1),
    ("grid_ll_tr_v",    "growatt_grid_ll_tr_voltage_volts","Grid line voltage TR (L3-L1)",            1),
    ("meter_total_w",   "growatt_meter_power_watts",       "Net meter power (pos=export, neg=import)",1),
    # Battery
    ("bat_soc",         "growatt_battery_soc_ratio",       "Battery state of charge (0.0-100.0 %)",  1),
    ("bat_v",           "growatt_battery_voltage_volts",   "Battery terminal voltage",                1),
    ("bat_i",           "growatt_battery_current_amps",    "Battery current (pos=charge)",            1),
    ("bat_p",           "growatt_battery_power_watts",     "Battery power (pos=charge, neg=discharge)",1),
    ("bat_nominal_kwh", "growatt_battery_capacity_kwh",    "Nominal battery capacity",                1),
    # Load / EPS
    ("load_p",          "growatt_load_power_watts",        "Total load power",                        1),
    ("eps_p",           "growatt_eps_power_watts",         "EPS/backup output power",                 1),
    ("eps_l1_v",        "growatt_eps_l1_voltage_volts",    "EPS phase L1 voltage",                    1),
    ("eps_l1_a",        "growatt_eps_l1_current_amps",     "EPS phase L1 current",                    1),
    ("eps_l2_v",        "growatt_eps_l2_voltage_volts",    "EPS phase L2 voltage",                    1),
    ("eps_l2_a",        "growatt_eps_l2_current_amps",     "EPS phase L2 current",                    1),
    ("eps_l3_v",        "growatt_eps_l3_voltage_volts",    "EPS phase L3 voltage",                    1),
    ("eps_l3_a",        "growatt_eps_l3_current_amps",     "EPS phase L3 current",                    1),
    # Energy counters
    ("pv_today_kwh",            "growatt_pv_energy_today_kwh",          "PV energy generated today",           1),
    ("pv_total_kwh",            "growatt_pv_energy_total_kwh",          "PV energy generated all-time",        1),
    ("grid_import_today_kwh",   "growatt_grid_import_today_kwh",        "Grid energy imported today",          1),
    ("grid_export_today_kwh",   "growatt_grid_export_today_kwh",        "Grid energy exported today",          1),
    ("bat_charge_today_kwh",    "growatt_battery_charge_today_kwh",     "Battery energy charged today",        1),
    ("bat_discharge_today_kwh", "growatt_battery_discharge_today_kwh",  "Battery energy discharged today",     1),
    ("bat_charge_total_kwh",    "growatt_battery_charge_total_kwh",     "Battery energy charged all-time",     1),
    ("bat_discharge_total_kwh", "growatt_battery_discharge_total_kwh",  "Battery energy discharged all-time",  1),
    # Metadata / status
    ("inverter_temp",   "growatt_inverter_temperature_celsius", "Inverter heat-sink temperature",     1),
    ("boost_temp",      "growatt_boost_temperature_celsius",    "Boost module temperature",            1),
    ("status_code",     "growatt_status_code",                  "Working state code (0-9)",            1),
    ("rated_power_w",   "growatt_rated_power_watts",            "Inverter rated AC output power",      1),
]


def _render_prometheus(r) -> str:
    """
    Render a single GrowattReading as Prometheus text format (0.0.4).

    Writes one ``# HELP``, one ``# TYPE``, and one sample line per gauge.
    An ``growatt_info`` gauge carries static device metadata as labels.

    :param r: GrowattReading instance from the store.
    :returns: UTF-8 string in Prometheus exposition format.
    """
    lines = []
    ts_ms = r.ts  # Prometheus uses millisecond timestamps

    # Device info gauge (value=1, metadata in labels)
    serial  = r.inverter_serial.replace('"', '')
    model   = r.inverter_model.replace('"', '')
    fw      = r.inverter_firmware.replace('"', '')
    lines.append("# HELP growatt_info Growatt inverter identity metadata")
    lines.append("# TYPE growatt_info gauge")
    lines.append(
        f'growatt_info{{serial="{serial}",model="{model}",firmware="{fw}"}} 1 {ts_ms}'
    )

    for field, metric, help_text, mult in _GAUGES:
        val = getattr(r, field, 0.0)
        if mult != 1:
            val = val * mult
        lines.append(f"# HELP {metric} {help_text}")
        lines.append(f"# TYPE {metric} gauge")
        lines.append(f'{metric}{{serial="{serial}"}} {val} {ts_ms}')

    lines.append("")  # trailing newline
    return "\n".join(lines)


def create_app(store: GrowattStore) -> Flask:
    """
    Create and configure the Flask dashboard application.

    :param store: GrowattStore instance shared with the collector thread.
    :returns:     Configured Flask application.
    """
    app = Flask(__name__)

    @app.route('/')
    def index():
        return render_template('dashboard.html', logo_text='Growatt')

    @app.route('/stream')
    def stream():
        def generate():
            last_ts = 0
            yield ": keep-alive\n\n"
            while True:
                time.sleep(1)
                r = store.latest_reading()
                if r and r.ts > last_ts:
                    last_ts = r.ts
                    d = r.to_dict()
                    yield f"event: reading\ndata: {json.dumps(d)}\n\n"
                else:
                    yield ": keep-alive\n\n"
        return Response(generate(), mimetype='text/event-stream', headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        })

    @app.route('/api/history')
    def history():
        from flask import request
        hours = int(request.args.get('hours', 24))
        since = int(time.time() * 1000) - (hours * 3600 * 1000)

        conn = store._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM readings_1m WHERE ts >= ? ORDER BY ts ASC", (since,))
        columns = [description[0] for description in cur.description]

        results = []
        for row in cur.fetchall():
            d = dict(zip(columns, row))
            results.append(d)

        return json.dumps(results), 200, {'Content-Type': 'application/json'}

    @app.route('/metrics')
    def metrics():
        """
        Expose the latest inverter reading in Prometheus text format (0.0.4).

        Returns 503 if no reading is available yet (collector has not
        completed its first poll cycle).
        """
        r = store.latest_reading()
        if r is None:
            return Response(
                "# No data available yet\n",
                status=503,
                mimetype="text/plain; version=0.0.4",
            )
        body = _render_prometheus(r)
        return Response(body, mimetype="text/plain; version=0.0.4")

    return app

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, Response, jsonify, send_from_directory, request
from growatt.store import GrowattStore

logger = logging.getLogger("growatt_dashboard")

def create_app(store: GrowattStore) -> Flask:
    app = Flask(__name__, static_folder='static', static_url_path='')

    @app.route('/')
    def index():
        return app.send_static_file('dashboard.html')

    @app.route('/api/device')
    def device():
        return jsonify({
            "ip": "172.28.2.36",
            "serial": "AXXXXXXX",
            "model": "MOD 12KTL3-HU",
            "swVersion": "v1.0",
            "wifiRSSI": -65
        })

    @app.route('/api/latest')
    def latest():
        r = store.latest_reading()
        if not r: return Response(status=204)
        return jsonify(r.to_dict())

    @app.route('/stream')
    def stream():
        def generate():
            last_ts = 0
            while True:
                time.sleep(1)
                r = store.latest_reading()
                if r and r.ts > last_ts:
                    last_ts = r.ts
                    # Map Growatt to expected dashboard JS keys
                    d = r.to_dict()
                    d["timestamp"] = datetime.fromtimestamp(r.ts/1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
                    d["p_net"] = d.get("meter_total_w", 0)
                    d["pv_total"] = d.get("pv_total_w", 0)
                    
                    d["v1"] = d.get("grid_l1_v", 0)
                    d["v2"] = d.get("grid_l2_v", 0)
                    d["v3"] = d.get("grid_l3_v", 0)
                    
                    d["voltage_l1"] = d.get("grid_l1_v", 0)
                    d["voltage_l2"] = d.get("grid_l2_v", 0)
                    d["voltage_l3"] = d.get("grid_l3_v", 0)
                    
                    d["current_l1"] = d.get("grid_l1_a", 0)
                    d["current_l2"] = d.get("grid_l2_a", 0)
                    d["current_l3"] = d.get("grid_l3_a", 0)
                    yield f"data: {json.dumps(d)}\\n\\n"
        return Response(generate(), mimetype='text/event-stream')


    @app.route('/api/summary/latest')
    def summary_latest():
        return Response(status=204)

    @app.route('/api/summary/delta')
    def summary_delta():
        return Response(status=204)

    return app


    @app.route('/api/summary/hourly')
    def summary_hourly():
        return Response(status=204)


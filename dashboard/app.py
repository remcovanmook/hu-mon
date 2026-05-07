import json
import logging
import time
from flask import Flask, Response, jsonify
from growatt.store import GrowattStore

logger = logging.getLogger("growatt_dashboard")

def create_app(store: GrowattStore) -> Flask:
    app = Flask(__name__, static_folder='static', static_url_path='')

    @app.route('/')
    def index():
        return app.send_static_file('dashboard.html')

    @app.route('/stream')
    def stream():
        def generate():
            reading = store.latest_reading()
            if reading:
                yield f"data: {json.dumps(reading.to_dict())}\n\n"
                
            last_ts = reading.ts if reading else 0
            while True:
                time.sleep(1.0)
                reading = store.latest_reading()
                if reading and reading.ts > last_ts:
                    last_ts = reading.ts
                    yield f"data: {json.dumps(reading.to_dict())}\n\n"
                    
        return Response(generate(), mimetype='text/event-stream')

    @app.route('/metrics')
    def metrics():
        reading = store.latest_reading()
        if not reading:
            return Response("", mimetype="text/plain")
            
        lines = []
        for k, v in reading.to_dict().items():
            if isinstance(v, (int, float)):
                lines.append(f"growatt_{k} {v}")
        
        return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")

    @app.route('/api/history')
    def history():
        # Future endpoint for serving readings_1m / readings_1h
        return jsonify([])

    return app

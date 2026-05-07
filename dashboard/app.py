import json
import logging
import time
from flask import Flask, Response, send_from_directory
from growatt.store import GrowattStore

logger = logging.getLogger("growatt_dashboard")

def create_app(store: GrowattStore) -> Flask:
    app = Flask(__name__)

    @app.route('/')
    def index():
        return app.send_static_file('dashboard.html')

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

    return app

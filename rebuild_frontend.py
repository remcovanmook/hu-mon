import os

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Growatt · Live Monitor</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="/static/css/dashboard.css" />
  <script>document.documentElement.dataset.theme = localStorage.getItem("hegg-theme") || "dark";</script>
</head>
<body>
  <header class="header">
    <div class="header-inner">
      <div class="logo">
        <div class="logo-mark" aria-hidden="true" style="background: linear-gradient(135deg, #16a34a, #0ea5e9);">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none"><path d="M16 2L4 16h9l-1 10 12-14h-9l1-10z" fill="currentColor"/></svg>
        </div>
        <span class="logo-text">Growatt</span>
        <span class="logo-sub">MOD 12KTL3-HU</span>
      </div>
      <div class="header-controls">
        <span class="header-time" id="header-time" aria-live="off">—</span>
        <button id="theme-toggle" class="theme-toggle" aria-label="Toggle colour theme">🌙 Dark</button>
        <output class="connection-status" id="connection-status">
          <span class="status-dot connecting" id="status-dot"></span>
          <span class="status-label" id="status-label">Connecting…</span>
        </output>
      </div>
    </div>
  </header>

  <main class="main">
    <!-- Live Production vs Grid -->
    <section class="section">
      <h2 class="section-title">Power Overview</h2>
      <div class="cards-row cards-row--three">
        <!-- Solar Power -->
        <article class="card card--delivered" id="card-solar">
          <div class="card-label">Solar Generation</div>
          <div class="phase-value-group">
            <div class="card-value" id="val-solar">—</div>
            <div class="card-unit">W</div>
          </div>
          <div class="card-hint">Total PV output</div>
        </article>

        <!-- Grid Net -->
        <article class="card card--returned" id="card-grid">
          <div class="card-label">Grid Net</div>
          <div class="phase-value-group">
            <div class="card-value" id="val-grid">—</div>
            <div class="card-unit">W</div>
          </div>
          <div class="card-hint" id="hint-grid">Import / Export</div>
        </article>

        <!-- Battery -->
        <article class="card card--net" id="card-battery">
          <div class="card-label">Battery SOC</div>
          <div class="phase-value-group">
            <div class="card-value" id="val-bat-soc">—</div>
            <div class="card-unit">%</div>
          </div>
          <div class="card-hint"><span id="val-bat-p">— W</span> <span id="hint-bat-dir">Idle</span></div>
        </article>
      </div>
    </section>

    <!-- PV Strings -->
    <section class="section">
      <h2 class="section-title">PV Strings</h2>
      <div class="cards-row cards-row--three">
        <article class="card">
          <div class="phase-row"><div class="phase-badge" style="background:#22c55e22;color:#22c55e">PV1</div></div>
          <div class="device-info">
            <div class="device-row"><span class="device-key">Power</span><span class="device-val" id="val-pv1-w">— W</span></div>
            <div class="device-row"><span class="device-key">Voltage</span><span class="device-val" id="val-pv1-v">— V</span></div>
            <div class="device-row"><span class="device-key">Current</span><span class="device-val" id="val-pv1-a">— A</span></div>
          </div>
        </article>
        <article class="card">
          <div class="phase-row"><div class="phase-badge" style="background:#22c55e22;color:#22c55e">PV2</div></div>
          <div class="device-info">
            <div class="device-row"><span class="device-key">Power</span><span class="device-val" id="val-pv2-w">— W</span></div>
            <div class="device-row"><span class="device-key">Voltage</span><span class="device-val" id="val-pv2-v">— V</span></div>
            <div class="device-row"><span class="device-key">Current</span><span class="device-val" id="val-pv2-a">— A</span></div>
          </div>
        </article>
      </div>
    </section>

    <!-- AC Phase Grid -->
    <section class="section">
      <h2 class="section-title">AC Grid (L1-L3)</h2>
      <div class="cards-row cards-row--three">
        <article class="card" id="card-v-l1">
          <div class="phase-row"><div class="phase-badge">L1</div></div>
          <div class="device-info">
            <div class="device-row"><span class="device-key">Voltage</span><span class="device-val" id="val-grid-l1-v">— V</span></div>
            <div class="device-row"><span class="device-key">Current</span><span class="device-val" id="val-grid-l1-a">— A</span></div>
          </div>
        </article>
        <article class="card" id="card-v-l2">
          <div class="phase-row"><div class="phase-badge">L2</div></div>
          <div class="device-info">
            <div class="device-row"><span class="device-key">Voltage</span><span class="device-val" id="val-grid-l2-v">— V</span></div>
            <div class="device-row"><span class="device-key">Current</span><span class="device-val" id="val-grid-l2-a">— A</span></div>
          </div>
        </article>
        <article class="card" id="card-v-l3">
          <div class="phase-row"><div class="phase-badge">L3</div></div>
          <div class="device-info">
            <div class="device-row"><span class="device-key">Voltage</span><span class="device-val" id="val-grid-l3-v">— V</span></div>
            <div class="device-row"><span class="device-key">Current</span><span class="device-val" id="val-grid-l3-a">— A</span></div>
          </div>
        </article>
      </div>
    </section>

    <!-- Chart -->
    <section class="section">
      <h2 class="section-title">Live Trend</h2>
      <div class="chart-card">
        <div class="chart-wrapper">
          <canvas id="chart-live"></canvas>
        </div>
      </div>
    </section>
  </main>
  
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <script src="/static/js/dashboard.js"></script>
</body>
</html>
"""

JS = """
"use strict";

let liveChart;
const maxPoints = 60; // 1 minute of 1-sec data

document.addEventListener("DOMContentLoaded", () => {
    // Clock
    setInterval(() => {
        document.getElementById("header-time").innerText = new Date().toLocaleTimeString();
    }, 1000);

    // Theme toggle
    document.getElementById("theme-toggle").addEventListener("click", () => {
        const current = document.documentElement.dataset.theme;
        const next = current === "light" ? "dark" : "light";
        document.documentElement.dataset.theme = next;
        localStorage.setItem("hegg-theme", next);
        document.getElementById("theme-toggle").innerText = next === "light" ? "☀️ Light" : "🌙 Dark";
        updateChartTheme();
    });

    initChart();
    connectSSE();
});

function initChart() {
    const ctx = document.getElementById("chart-live").getContext("2d");
    Chart.defaults.color = "#6b7490";
    
    liveChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Solar (W)',
                    borderColor: '#22c55e',
                    backgroundColor: '#22c55e22',
                    data: [],
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0
                },
                {
                    label: 'Grid Net (W)',
                    borderColor: '#f59e0b',
                    backgroundColor: 'transparent',
                    data: [],
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: "index", intersect: false },
            scales: {
                x: { display: false },
                y: { grid: { color: "rgba(255,255,255,0.04)" } }
            },
            plugins: { legend: { display: true } }
        }
    });
}

function updateChartTheme() {
    const isDark = document.documentElement.dataset.theme === "dark";
    const gridColor = isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.06)";
    const textColor = isDark ? "#6b7490" : "#6b7490";
    
    Chart.defaults.color = textColor;
    if (liveChart) {
        liveChart.options.scales.y.grid.color = gridColor;
        liveChart.update();
    }
}

function updateDOM(id, val) {
    const el = document.getElementById(id);
    if(el) {
        el.innerText = val;
        el.classList.add("value-updated");
        setTimeout(() => el.classList.remove("value-updated"), 300);
    }
}

function connectSSE() {
    const dot = document.getElementById("status-dot");
    const lbl = document.getElementById("status-label");
    const es = new EventSource("/stream");

    es.onopen = () => {
        dot.className = "status-dot connected";
        lbl.innerText = "Live";
    };
    es.onerror = () => {
        dot.className = "status-dot disconnected";
        lbl.innerText = "Reconnecting...";
    };

    es.addEventListener("reading", (e) => {
        const d = JSON.parse(e.data);
        
        // Solar
        updateDOM("val-solar", d.pv_total_w.toFixed(0));
        
        // Grid
        updateDOM("val-grid", Math.abs(d.meter_total_w).toFixed(0));
        updateDOM("hint-grid", d.meter_total_w >= 0 ? "Exporting to Grid" : "Importing from Grid");
        document.getElementById("card-grid").className = d.meter_total_w >= 0 ? "card card--returned" : "card card--delivered";

        // Battery
        updateDOM("val-bat-soc", d.bat_soc.toFixed(1));
        updateDOM("val-bat-p", Math.abs(d.bat_p).toFixed(0) + " W");
        updateDOM("hint-bat-dir", d.bat_p > 0 ? "Charging" : (d.bat_p < 0 ? "Discharging" : "Idle"));

        // PV1 & PV2
        updateDOM("val-pv1-w", d.pv1_w.toFixed(0) + " W");
        updateDOM("val-pv1-v", d.pv1_v.toFixed(1) + " V");
        updateDOM("val-pv1-a", d.pv1_a.toFixed(2) + " A");

        updateDOM("val-pv2-w", d.pv2_w.toFixed(0) + " W");
        updateDOM("val-pv2-v", d.pv2_v.toFixed(1) + " V");
        updateDOM("val-pv2-a", d.pv2_a.toFixed(2) + " A");

        // Grid Phase L1-L3
        updateDOM("val-grid-l1-v", d.grid_l1_v.toFixed(1) + " V");
        updateDOM("val-grid-l1-a", d.grid_l1_a.toFixed(2) + " A");
        updateDOM("val-grid-l2-v", d.grid_l2_v.toFixed(1) + " V");
        updateDOM("val-grid-l2-a", d.grid_l2_a.toFixed(2) + " A");
        updateDOM("val-grid-l3-v", d.grid_l3_v.toFixed(1) + " V");
        updateDOM("val-grid-l3-a", d.grid_l3_a.toFixed(2) + " A");

        // Update Chart
        const timeStr = new Date(d.ts).toLocaleTimeString();
        liveChart.data.labels.push(timeStr);
        liveChart.data.datasets[0].data.push(d.pv_total_w);
        liveChart.data.datasets[1].data.push(d.meter_total_w);

        if (liveChart.data.labels.length > maxPoints) {
            liveChart.data.labels.shift();
            liveChart.data.datasets[0].data.shift();
            liveChart.data.datasets[1].data.shift();
        }
        liveChart.update('none');
    });
}
"""

APP_PY = """import json
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
            while True:
                time.sleep(1)
                r = store.latest_reading()
                if r and r.ts > last_ts:
                    last_ts = r.ts
                    d = r.to_dict()
                    yield f"event: reading\\ndata: {json.dumps(d)}\\n\\n"
        return Response(generate(), mimetype='text/event-stream')

    return app
"""

with open("dashboard/static/dashboard.html", "w") as f:
    f.write(HTML)

with open("dashboard/static/js/dashboard.js", "w") as f:
    f.write(JS)

with open("dashboard/app.py", "w") as f:
    f.write(APP_PY)

print("Rewrote frontend to natively match Growatt architecture while preserving Hegg-emon CSS.")

import os

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Growatt Dashboard</title>
  <link rel="stylesheet" href="/static/css/dashboard.css?v=4">
  <script>document.documentElement.dataset.theme = localStorage.getItem("hegg-theme") || "dark";</script>
  <style>
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    
    .tabs-nav {
      display: flex; gap: 1rem; margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 1rem;
    }
    .tab-btn {
      background: none; border: none; color: var(--text-muted); font-size: 1.1rem; font-weight: 500;
      cursor: pointer; padding: 0.5rem 1rem; border-radius: 6px; transition: all 0.2s;
    }
    .tab-btn:hover { color: var(--text); background: var(--bg-hover); }
    .tab-btn.active { color: var(--primary); background: var(--primary-alpha); font-weight: 600; }
    
    .power-flow {
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
      padding: 2rem; margin-bottom: 2rem; position: relative;
    }
    .flow-container {
      position: relative; height: 300px; max-width: 800px; margin: 0 auto;
    }
    .flow-node {
      position: absolute; display: flex; flex-direction: column; align-items: center;
      justify-content: center; width: 130px; height: 110px;
      background: var(--bg); border: 1px solid var(--border); border-radius: 12px;
      z-index: 10; font-weight: 500; font-size: 0.95rem; color: var(--text);
    }
    .flow-node .icon { font-size: 2.2rem; margin-bottom: 0.4rem; }
    .flow-node .val { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 1.2rem; margin-top: 0.25rem; color: var(--text); }
    
    #node-pv { top: 20px; left: 0; }
    #node-inv { top: 20px; left: 335px; border-color: var(--primary); }
    #node-grid { top: 20px; right: 0; }
    #node-bat { top: 180px; left: 160px; }
    #node-load { top: 180px; right: 160px; }

    .flow-lines {
      position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; pointer-events: none;
    }
    .flow-line {
      fill: none; stroke: var(--text-muted); stroke-width: 4; stroke-dasharray: 8; opacity: 0.2;
    }
    .flow-line.active {
      stroke: var(--primary); opacity: 0.8; animation: flowDash 1s linear infinite;
    }
    .flow-line.export { stroke: #f59e0b; animation-direction: reverse; }
    @keyframes flowDash {
      to { stroke-dashoffset: -16; }
    }
    
    .cards-row--four { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1rem; }
    .summary-strip { margin-bottom: 2rem; }
    
    .phase-value-group { display: flex; align-items: baseline; gap: 0.3rem; }
    .status-ok { color: #22c55e; font-weight: 600; }
    .status-warn { color: #f59e0b; font-weight: 600; }
    .status-err { color: #ef4444; font-weight: 600; }
  </style>
</head>
<body>
  <header class="header">
    <div class="header-inner">
      <div class="logo">
        <span class="logo-text">Growatt MOD 12KTL3</span>
      </div>
      <div class="header-controls">
        <button id="theme-toggle" class="theme-toggle">🌙 Dark</button>
      </div>
    </div>
  </header>

  <main class="main">
    <section class="summary-strip">
      <div class="cards-row cards-row--four">
        <article class="card card--delivered">
          <div class="card-label">Current Production</div>
          <div class="phase-value-group"><div class="card-value" id="sum-pv">—</div><div class="card-unit">W</div></div>
          <div class="card-hint" id="sum-pv-hint">WAITING</div>
        </article>
        <article class="card card--returned" id="sum-grid-card">
          <div class="card-label">Grid Power</div>
          <div class="phase-value-group"><div class="card-value" id="sum-grid">—</div><div class="card-unit">W</div></div>
          <div class="card-hint" id="sum-grid-hint">Importing</div>
        </article>
        <article class="card card--net">
          <div class="card-label">Battery SOC</div>
          <div class="phase-value-group"><div class="card-value" id="sum-bat">—</div><div class="card-unit">%</div></div>
          <div class="card-hint" id="sum-bat-hint">Idle</div>
        </article>
        <article class="card card--net" style="border-color:#a855f7">
          <div class="card-label">House Consumption</div>
          <div class="phase-value-group"><div class="card-value" id="sum-load" style="color:#a855f7">—</div><div class="card-unit">W</div></div>
          <div class="card-hint">Live Load</div>
        </article>
      </div>
    </section>

    <nav class="tabs-nav">
      <button class="tab-btn active" data-target="tab-overview">Overview</button>
      <button class="tab-btn" data-target="tab-pv">PV Power</button>
      <button class="tab-btn" data-target="tab-grid">Grid Power</button>
      <button class="tab-btn" data-target="tab-battery">Battery Power</button>
    </nav>

    <section id="tab-overview" class="tab-content active">
      <div class="power-flow">
        <div class="flow-container">
          <div class="flow-node" id="node-pv">
            <span class="icon">☀️</span><span class="label">PV Array</span><span class="val" id="flow-pv">0 W</span>
          </div>
          <div class="flow-node" id="node-inv">
            <span class="icon">⚡</span><span class="label">Inverter</span><span class="val" id="flow-inv">WAITING</span>
          </div>
          <div class="flow-node" id="node-grid">
            <span class="icon">🏢</span><span class="label">Grid</span><span class="val" id="flow-grid">0 W</span>
          </div>
          <div class="flow-node" id="node-bat">
            <span class="icon">🔋</span><span class="label">Battery <span id="flow-soc">0%</span></span><span class="val" id="flow-bat">0 W</span>
          </div>
          <div class="flow-node" id="node-load">
            <span class="icon">🏠</span><span class="label">Load</span><span class="val" id="flow-load">0 W</span>
          </div>
          <svg class="flow-lines">
            <path d="M 130 75 L 335 75" class="flow-line" id="line-pv-inv" />
            <path d="M 465 75 L 670 75" class="flow-line" id="line-inv-grid" />
            <path d="M 400 130 L 400 235 L 290 235" class="flow-line" id="line-inv-bat" />
            <path d="M 400 130 L 400 235 L 510 235" class="flow-line" id="line-inv-load" />
          </svg>
        </div>
      </div>
      <div class="chart-card"><div class="chart-wrapper"><canvas id="chart-overview"></canvas></div></div>
    </section>

    <section id="tab-pv" class="tab-content">
      <div class="chart-card" style="margin-bottom:2rem;"><div class="chart-wrapper"><canvas id="chart-pv"></canvas></div></div>
      <h3 class="section-title">PV Voltage</h3><div class="cards-row cards-row--four" id="pv-v-cards"></div>
      <h3 class="section-title">PV Current</h3><div class="cards-row cards-row--four" id="pv-a-cards"></div>
      <h3 class="section-title">PV Power</h3><div class="cards-row cards-row--four" id="pv-w-cards"></div>
    </section>

    <section id="tab-grid" class="tab-content">
      <div class="chart-card" style="margin-bottom:2rem;"><div class="chart-wrapper"><canvas id="chart-grid"></canvas></div></div>
      <h3 class="section-title">Grid Voltage</h3><div class="cards-row cards-row--four" id="grid-v-cards"></div>
      <h3 class="section-title">Grid Current</h3><div class="cards-row cards-row--four" id="grid-a-cards"></div>
      <h3 class="section-title">Grid Power</h3><div class="cards-row cards-row--four" id="grid-w-cards"></div>
    </section>

    <section id="tab-battery" class="tab-content">
      <div class="chart-card" style="margin-bottom:2rem;"><div class="chart-wrapper"><canvas id="chart-battery"></canvas></div></div>
      <div class="cards-row cards-row--four">
        <article class="card"><div class="card-label">Battery Voltage</div><div class="phase-value-group"><div class="card-value" id="bat-v">—</div><div class="card-unit">V</div></div></article>
        <article class="card"><div class="card-label">Battery Current</div><div class="phase-value-group"><div class="card-value" id="bat-a">—</div><div class="card-unit">A</div></div></article>
        <article class="card"><div class="card-label">Battery Power</div><div class="phase-value-group"><div class="card-value" id="bat-w">—</div><div class="card-unit">W</div></div></article>
        <article class="card"><div class="card-label">Battery SOC</div><div class="phase-value-group"><div class="card-value" id="bat-soc2">—</div><div class="card-unit">%</div></div></article>
      </div>
    </section>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <script src="/static/js/dashboard.js?v=4"></script>
</body>
</html>
"""

JS = """
"use strict";

const charts = {};
const maxPoints = 60;
const STATUS_MAP = {0: "WAITING", 1: "NORMAL", 3: "FAULT", 4: "FLASH"};

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(btn.dataset.target).classList.add('active');
        });
    });

    const createGroup = (id, label, unit, count, l_prefix) => {
        const el = document.getElementById(id);
        for(let i=1; i<=count; i++) {
            el.innerHTML += `<article class="card"><div class="card-label">${l_prefix} ${i} ${label}</div><div class="phase-value-group"><div class="card-value" id="${l_prefix.toLowerCase()}${i}-${unit.toLowerCase()}">—</div><div class="card-unit">${unit}</div></div></article>`;
        }
    };
    
    createGroup('pv-v-cards', 'Voltage', 'V', 4, 'PV');
    createGroup('pv-a-cards', 'Current', 'A', 4, 'PV');
    createGroup('pv-w-cards', 'Power', 'W', 4, 'PV');
    
    createGroup('grid-v-cards', 'Voltage', 'V', 3, 'Grid');
    createGroup('grid-a-cards', 'Current', 'A', 3, 'Grid');
    createGroup('grid-w-cards', 'Power', 'W', 3, 'Grid');

    Chart.defaults.color = "#6b7490";
    charts.overview = createChart('chart-overview', [
        { label: 'PV Generation (W)', color: '#22c55e' },
        { label: 'Grid Net (W)', color: '#f59e0b' },
        { label: 'Load (W)', color: '#a855f7' }
    ]);
    charts.pv = createChart('chart-pv', [
        { label: 'String 1 (W)', color: '#3b82f6' },
        { label: 'String 2 (W)', color: '#8b5cf6' },
        { label: 'String 3 (W)', color: '#ec4899' },
        { label: 'String 4 (W)', color: '#14b8a6' }
    ]);
    charts.grid = createChart('chart-grid', [
        { label: 'L1 Power (W)', color: '#ef4444' },
        { label: 'L2 Power (W)', color: '#eab308' },
        { label: 'L3 Power (W)', color: '#3b82f6' }
    ]);
    charts.battery = createChart('chart-battery', [
        { label: 'Battery Power (W)', color: '#a855f7' }
    ]);

    connectSSE();
});

function createChart(id, series) {
    const ctx = document.getElementById(id).getContext('2d');
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: series.map(s => ({
                label: s.label, borderColor: s.color, backgroundColor: s.color + '22',
                data: [], fill: false, tension: 0.3, pointRadius: 0
            }))
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            interaction: { mode: "index", intersect: false },
            scales: { x: { display: false }, y: { grid: { color: "rgba(255,255,255,0.04)" } } },
            plugins: { legend: { display: true } }
        }
    });
}

function updateDOM(id, val) {
    const el = document.getElementById(id);
    if(el) {
        el.innerText = val;
        el.classList.add("value-updated");
        setTimeout(() => el.classList.remove("value-updated"), 300);
    }
}

function pushChart(chart, timeStr, values) {
    chart.data.labels.push(timeStr);
    for(let i=0; i<values.length; i++) {
        chart.data.datasets[i].data.push(values[i]);
    }
    if (chart.data.labels.length > maxPoints) {
        chart.data.labels.shift();
        for(let i=0; i<values.length; i++) chart.data.datasets[i].data.shift();
    }
    chart.update('none');
}

function setFlowLine(id, active, isExport = false) {
    const el = document.getElementById(id);
    if(!el) return;
    el.className = "flow-line";
    if (active) el.classList.add("active");
    if (isExport) el.classList.add("export");
}

function connectSSE() {
    const es = new EventSource("/stream");
    es.addEventListener("reading", (e) => {
        const d = JSON.parse(e.data);
        const timeStr = new Date(d.ts).toLocaleTimeString();
        
        const statText = STATUS_MAP[d.status_code] || "UNKNOWN";
        let statClass = "status-ok";
        if (d.status_code === 0) statClass = "status-warn";
        else if (d.status_code === 3 || d.status_code === 4) statClass = "status-err";

        // Summary Strip
        updateDOM("sum-pv", d.pv_total_w.toFixed(0));
        document.getElementById("sum-pv-hint").innerHTML = `Status: <span class="${statClass}">${statText}</span>`;
        
        updateDOM("sum-grid", Math.abs(d.meter_total_w).toFixed(0));
        updateDOM("sum-grid-hint", d.meter_total_w >= 0 ? "Exporting" : "Importing");
        document.getElementById("sum-grid-card").className = d.meter_total_w >= 0 ? "card card--returned" : "card card--delivered";
        
        updateDOM("sum-bat", d.bat_soc.toFixed(1));
        updateDOM("sum-bat-hint", Math.abs(d.bat_p).toFixed(0) + " W " + (d.bat_p > 0 ? "Charging" : (d.bat_p < 0 ? "Discharging" : "Idle")));
        
        updateDOM("sum-load", d.load_p.toFixed(0));

        // Cute Diagram
        updateDOM("flow-pv", d.pv_total_w.toFixed(0) + " W");
        updateDOM("flow-grid", Math.abs(d.meter_total_w).toFixed(0) + " W");
        updateDOM("flow-bat", Math.abs(d.bat_p).toFixed(0) + " W");
        updateDOM("flow-load", d.load_p.toFixed(0) + " W");
        updateDOM("flow-soc", d.bat_soc.toFixed(0) + "%");
        document.getElementById("flow-inv").innerHTML = `<span class="${statClass}">${statText}</span>`;
        
        setFlowLine("line-pv-inv", d.pv_total_w > 10);
        setFlowLine("line-inv-grid", Math.abs(d.meter_total_w) > 10, d.meter_total_w > 0);
        setFlowLine("line-inv-bat", Math.abs(d.bat_p) > 10, d.bat_p < 0);
        setFlowLine("line-inv-load", d.load_p > 10);

        // Tab 2
        for(let i=1; i<=4; i++) {
            updateDOM(`pv${i}-v`, d[`pv${i}_v`].toFixed(1));
            updateDOM(`pv${i}-a`, d[`pv${i}_a`].toFixed(1));
            updateDOM(`pv${i}-w`, d[`pv${i}_w`].toFixed(0));
        }

        // Tab 3
        const g1w = d.grid_l1_v * d.grid_l1_a;
        const g2w = d.grid_l2_v * d.grid_l2_a;
        const g3w = d.grid_l3_v * d.grid_l3_a;
        for(let i=1; i<=3; i++) {
            updateDOM(`grid${i}-v`, d[`grid_l${i}_v`].toFixed(1));
            updateDOM(`grid${i}-a`, d[`grid_l${i}_a`].toFixed(1));
        }
        updateDOM(`grid1-w`, g1w.toFixed(0));
        updateDOM(`grid2-w`, g2w.toFixed(0));
        updateDOM(`grid3-w`, g3w.toFixed(0));

        // Tab 4
        updateDOM("bat-v", d.bat_v.toFixed(1));
        updateDOM("bat-a", d.bat_i.toFixed(1));
        updateDOM("bat-w", d.bat_p.toFixed(0));
        updateDOM("bat-soc2", d.bat_soc.toFixed(1));

        // Charts
        pushChart(charts.overview, timeStr, [d.pv_total_w, d.meter_total_w, d.load_p]);
        pushChart(charts.pv, timeStr, [d.pv1_w, d.pv2_w, d.pv3_w, d.pv4_w]);
        pushChart(charts.grid, timeStr, [g1w, g2w, g3w]);
        pushChart(charts.battery, timeStr, [d.bat_p]);
    });
}
"""
with open("dashboard/static/dashboard.html", "w") as f: f.write(HTML)
with open("dashboard/static/js/dashboard.js", "w") as f: f.write(JS)

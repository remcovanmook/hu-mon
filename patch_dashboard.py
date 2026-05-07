import json
import os

HTML_PATH = "dashboard/static/dashboard.html"
with open(HTML_PATH, "r") as f:
    html = f.read()

# Add date-fns adapter before dashboard.js
if "chartjs-adapter-date-fns" not in html:
    html = html.replace(
        '<script src="/static/js/dashboard.js?v=4"></script>',
        '<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>\n  <script src="/static/js/dashboard.js?v=5"></script>'
    )
with open(HTML_PATH, "w") as f:
    f.write(html)

JS = """
"use strict";

const charts = {};
const STATUS_MAP = {0: "WAITING", 1: "NORMAL", 3: "FAULT", 4: "FLASH"};

// Use exact Hegg colors
const COLORS = {
  pv: '#22c55e',
  grid: '#f59e0b',
  load: '#a855f7',
  l1: '#ef4444',
  l2: '#eab308',
  l3: '#3b82f6',
  pv1: '#3b82f6',
  pv2: '#8b5cf6',
  pv3: '#ec4899',
  pv4: '#14b8a6'
};

const BASE_OPTS = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    transitions: { active: { animation: { duration: 0 } } },
    interaction: { mode: "index", intersect: false },
    elements: {
        point: { radius: 0, hitRadius: 6 },
        line:  { tension: 0.3, borderWidth: 1.5 },
    },
    scales: {
        x: {
            type: "time",
            time: {
                tooltipFormat: "HH:mm:ss",
                displayFormats: { second: "HH:mm:ss", minute: "HH:mm", hour: "HH:mm", day: "MMM d" },
            },
            ticks: { color: "#6b7490", maxTicksLimit: 8, font: { size: 11 } },
            grid:  { color: "rgba(255,255,255,0.04)" },
            border: { display: false },
        },
        y: {
            ticks: { color: "#6b7490", font: { size: 11 } },
            grid:  { color: "rgba(255,255,255,0.04)" },
            border: { display: false },
        },
    },
    plugins: {
        legend: { display: true, labels: { color: "#9ca3af" } },
        tooltip: {
            backgroundColor: "rgba(22,26,34,0.95)",
            borderColor: "rgba(255,255,255,0.1)",
            borderWidth: 1,
            titleColor: "#e8eaf0",
            bodyColor: "#9ca3af",
            padding: 10,
        }
    }
};

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
        { label: 'PV Generation (W)', color: COLORS.pv },
        { label: 'Grid Net (W)', color: COLORS.grid },
        { label: 'Load (W)', color: COLORS.load }
    ]);
    charts.pv = createChart('chart-pv', [
        { label: 'String 1 (W)', color: COLORS.pv1 },
        { label: 'String 2 (W)', color: COLORS.pv2 },
        { label: 'String 3 (W)', color: COLORS.pv3 },
        { label: 'String 4 (W)', color: COLORS.pv4 }
    ]);
    charts.grid = createChart('chart-grid', [
        { label: 'L1 Power (W)', color: COLORS.l1 },
        { label: 'L2 Power (W)', color: COLORS.l2 },
        { label: 'L3 Power (W)', color: COLORS.l3 }
    ]);
    charts.battery = createChart('chart-battery', [
        { label: 'Battery Power (W)', color: COLORS.load }
    ]);

    loadHistory();
    connectSSE();
    
    // Prune data outside 24h window
    setInterval(() => {
        const cutoff = Date.now() - 24 * 3600 * 1000;
        Object.values(charts).forEach(c => {
            let keepIdx = 0;
            while(keepIdx < c.data.labels.length && c.data.labels[keepIdx] < cutoff) keepIdx++;
            if(keepIdx > 0) {
                c.data.labels.splice(0, keepIdx);
                c.data.datasets.forEach(ds => ds.data.splice(0, keepIdx));
                c.update('none');
            }
        });
    }, 60000);
});

function createChart(id, series) {
    const ctx = document.getElementById(id).getContext('2d');
    const opts = structuredClone(BASE_OPTS);
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: series.map(s => ({
                label: s.label, borderColor: s.color, backgroundColor: s.color + '22',
                data: [], fill: false, tension: 0.3, pointRadius: 0
            }))
        },
        options: opts
    });
}

function updateDOM(id, val) {
    const el = document.getElementById(id);
    if(el) {
        if (el.innerText !== String(val)) {
            el.innerText = val;
            el.classList.add("value-updated");
            setTimeout(() => el.classList.remove("value-updated"), 300);
        }
    }
}

async function loadHistory() {
    try {
        const res = await fetch(`/api/history?hours=24`);
        if(!res.ok) return;
        const data = await res.json();
        if(data.length === 0) return;
        
        const labels = [];
        const datasets = {
            overview: [[], [], []],
            pv: [[], [], [], []],
            grid: [[], [], []],
            battery: [[]]
        };
        
        data.forEach(d => {
            labels.push(d.ts);
            datasets.overview[0].push(d.pv_total_w_mean);
            datasets.overview[1].push(d.meter_total_w_mean);
            datasets.overview[2].push(d.load_p_mean);
            
            datasets.pv[0].push(d.pv1_w_mean);
            datasets.pv[1].push(d.pv2_w_mean);
            datasets.pv[2].push(d.pv3_w_mean);
            datasets.pv[3].push(d.pv4_w_mean);
            
            datasets.grid[0].push(d.grid_l1_v_mean * d.grid_l1_a_mean);
            datasets.grid[1].push(d.grid_l2_v_mean * d.grid_l2_a_mean);
            datasets.grid[2].push(d.grid_l3_v_mean * d.grid_l3_a_mean);
            
            datasets.battery[0].push(d.bat_p_mean);
        });
        
        Object.keys(charts).forEach(k => {
            charts[k].data.labels = [...labels];
            charts[k].data.datasets.forEach((ds, i) => ds.data = [...datasets[k][i]]);
            charts[k].update('none');
        });
    } catch(e) {
        console.error("History load failed", e);
    }
}

function pushChart(chart, ts, values) {
    chart.data.labels.push(ts);
    for(let i=0; i<values.length; i++) {
        chart.data.datasets[i].data.push(values[i]);
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
        const ts = d.ts;
        
        const statText = STATUS_MAP[d.status_code] || "UNKNOWN";
        let statClass = "status-ok";
        if (d.status_code === 0) statClass = "status-warn";
        else if (d.status_code === 3 || d.status_code === 4) statClass = "status-err";

        // Summary
        updateDOM("sum-pv", d.pv_total_w.toFixed(0));
        document.getElementById("sum-pv-hint").innerHTML = `Status: <span class="${statClass}">${statText}</span>`;
        updateDOM("sum-grid", Math.abs(d.meter_total_w).toFixed(0));
        updateDOM("sum-grid-hint", d.meter_total_w >= 0 ? "Exporting" : "Importing");
        document.getElementById("sum-grid-card").className = d.meter_total_w >= 0 ? "card card--returned" : "card card--delivered";
        updateDOM("sum-bat", d.bat_soc.toFixed(1));
        updateDOM("sum-bat-hint", Math.abs(d.bat_p).toFixed(0) + " W " + (d.bat_p > 0 ? "Charging" : (d.bat_p < 0 ? "Discharging" : "Idle")));
        updateDOM("sum-load", d.load_p.toFixed(0));

        // Flow Diagram
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

        for(let i=1; i<=4; i++) {
            updateDOM(`pv${i}-v`, d[`pv${i}_v`].toFixed(1));
            updateDOM(`pv${i}-a`, d[`pv${i}_a`].toFixed(1));
            updateDOM(`pv${i}-w`, d[`pv${i}_w`].toFixed(0));
        }

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

        updateDOM("bat-v", d.bat_v.toFixed(1));
        updateDOM("bat-a", d.bat_i.toFixed(1));
        updateDOM("bat-w", d.bat_p.toFixed(0));
        updateDOM("bat-soc2", d.bat_soc.toFixed(1));

        pushChart(charts.overview, ts, [d.pv_total_w, d.meter_total_w, d.load_p]);
        pushChart(charts.pv, ts, [d.pv1_w, d.pv2_w, d.pv3_w, d.pv4_w]);
        pushChart(charts.grid, ts, [g1w, g2w, g3w]);
        pushChart(charts.battery, ts, [d.bat_p]);
    });
}
"""
with open("dashboard/static/js/dashboard.js", "w") as f:
    f.write(JS)


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

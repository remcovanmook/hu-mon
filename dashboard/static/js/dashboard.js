
"use strict";

// --- Added by Chart Refactor ---
function niceScale(rawMin, rawMax, maxIntervals = 5) {
  if (!Number.isFinite(rawMin) || !Number.isFinite(rawMax) || rawMin === rawMax) {
    return { min: Math.floor(rawMin) - 1, max: Math.ceil(rawMax) + 1, step: 1 };
  }
  const range = rawMax - rawMin;
  const roughStep = range / maxIntervals;
  const magnitude = Math.pow(10, Math.floor(Math.log10(roughStep)));
  const norm = roughStep / magnitude;
  let step;
  if (norm <= 1) step = magnitude;
  else if (norm <= 2) step = 2 * magnitude;
  else if (norm <= 5) step = 5 * magnitude;
  else step = 10 * magnitude;
  return { min: Math.floor(rawMin / step) * step, max: Math.ceil(rawMax / step) * step, step };
}

function syncChartScales(chartArray, extremesArray, minFloor = -Infinity) {
  let globalMin = Infinity, globalMax = -Infinity;
  extremesArray.forEach(e => {
    if (e.min < globalMin) globalMin = e.min;
    if (e.max > globalMax) globalMax = e.max;
  });
  if (!Number.isFinite(globalMin) || !Number.isFinite(globalMax)) return;
  const clampedMin = Math.max(minFloor, globalMin);
  const { min, max, step } = niceScale(clampedMin, globalMax);
  const niceMin = Math.max(minFloor, min);

  chartArray.forEach(c => {
    if(!c) return;
    c.options.scales.y.min = niceMin;
    c.options.scales.y.max = max;
    if(!c.options.scales.y.ticks) c.options.scales.y.ticks = {};
    c.options.scales.y.ticks.stepSize = step;
  });
}

function buildStatusAnnotation(tsMs, statusStr) {
  return {
    type: "line", scaleID: "x", value: tsMs,
    borderColor: "rgba(139, 92, 246, 0.5)", borderWidth: 1, borderDash: [4, 4],
    label: {
      display: true, content: statusStr, position: "center",
      backgroundColor: "rgba(139, 92, 246, 0.8)", color: "#fff",
      font: { size: 9, weight: "600" }, padding: { x: 4, y: 2 }, borderRadius: 4, rotation: -90
    }
  };
}

function updateSparklineAnnotations(chart, min, max, color) {
  if(!chart) return;
  const cStr = typeof color === 'string' && color.startsWith('#') ? color + '80' : color;
  const bg = typeof color === 'string' && color.startsWith('#') ? color + 'd0' : 'rgba(100,100,100,0.8)';
  chart.options.plugins.annotation.annotations = { ...chart.options.plugins.annotation.annotations,
    minLine: {
      type: 'line', yMin: min, yMax: min, borderColor: cStr, borderWidth: 1, borderDash: [2, 2],
      label: { display: true, content: min.toFixed(1), position: 'end', backgroundColor: bg, color: '#fff', font: {size: 9, weight: '600'}, padding: {x: 4, y: 2}, borderRadius: 4 }
    },
    maxLine: {
      type: 'line', yMin: max, yMax: max, borderColor: cStr, borderWidth: 1, borderDash: [2, 2],
      label: { display: true, content: max.toFixed(1), position: 'start', backgroundColor: bg, color: '#fff', font: {size: 9, weight: '600'}, padding: {x: 4, y: 2}, borderRadius: 4 }
    }
  });
}

const extremes = {
    pv_v: Array.from({length: 4}, () => ({min: Infinity, max: -Infinity})),
    pv_c: Array.from({length: 4}, () => ({min: Infinity, max: -Infinity})),
    grid_v: Array.from({length: 3}, () => ({min: Infinity, max: -Infinity})),
    grid_c: Array.from({length: 3}, () => ({min: Infinity, max: -Infinity})),
    eps_v: Array.from({length: 3}, () => ({min: Infinity, max: -Infinity})),
    eps_c: Array.from({length: 3}, () => ({min: Infinity, max: -Infinity}))
};
let statusAnnotations = {};
let lastStatus = null;


const charts = {};
const maxPoints = 60;
const STATUS_MAP = {0: "WAITING", 1: "NORMAL", 3: "FAULT", 4: "FLASH"};

function chartPalette() {
  const s = getComputedStyle(document.documentElement);
  const v = name => s.getPropertyValue(name).trim();
  return {
    delivered: v("--delivered-color") || '#22c55e',
    returned:  v("--returned-color") || '#f59e0b',
    net:       v("--net-color") || '#3b82f6',
    l1:        v("--phase-l1") || '#ef4444',
    l2:        v("--phase-l2") || '#eab308',
    l3:        v("--phase-l3") || '#3b82f6',
    pv1: '#3b82f6', pv2: '#8b5cf6', pv3: '#ec4899', pv4: '#14b8a6', load: '#a855f7'
  };
}
let COLORS = chartPalette();

const THEME_CYCLE  = ["light", "dark", "auto"];
const THEME_LABELS = { light: "☀️ Light", dark: "🌙 Dark", auto: "◐ Auto" };

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("hegg-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = THEME_LABELS[theme] ?? theme;
  recolorCharts();
}
function cycleTheme() {
  const current = document.documentElement.dataset.theme || "light";
  const next    = THEME_CYCLE[(THEME_CYCLE.indexOf(current) + 1) % THEME_CYCLE.length];
  applyTheme(next);
}
function recolorCharts() {
  COLORS = chartPalette();
  const s = getComputedStyle(document.documentElement);
  const grid = s.getPropertyValue("--chart-grid").trim() || "rgba(0,0,0,0.06)";
  const tick = s.getPropertyValue("--text-muted").trim() || "#6b7490";
  Chart.defaults.color = tick;
  Object.values(charts).forEach(chart => {
      Object.values(chart.options.scales).forEach(axis => {
          if (axis.ticks) axis.ticks.color = tick;
          if (axis.grid) axis.grid.color = grid;
      });
      chart.update("none");
  });
}

function getBaseOpts() {
    return {
        responsive: true, maintainAspectRatio: false, animation: false,
        transitions: { active: { animation: { duration: 0 } } },
        interaction: { mode: "index", intersect: false },
        elements: { point: { radius: 0, hitRadius: 6 }, line: { tension: 0.3, borderWidth: 1.5 } },
        scales: {
            x: { type: "time", time: { tooltipFormat: "HH:mm:ss" }, ticks: { maxTicksLimit: 8 } },
            y: {}
        },
        plugins: {
            annotation: { annotations: {} },
            legend: { display: true },
            tooltip: { padding: 10 }
        }
    };
}

function switchTab(id) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('tab-btn--active'));
    document.querySelectorAll('.tab-content').forEach(c => c.hidden = true);
    document.getElementById(`tab-btn-${id}`).classList.add('tab-btn--active');
    document.getElementById(`tab-${id}`).hidden = false;
}




document.addEventListener("DOMContentLoaded", () => {
    const toggleBtn = document.getElementById("theme-toggle");
    if (toggleBtn) {
        toggleBtn.addEventListener("click", cycleTheme);
        const savedTheme = document.documentElement.dataset.theme || "light";
        toggleBtn.textContent = THEME_LABELS[savedTheme] ?? savedTheme;
    }

    document.getElementById("tab-btn-overview").addEventListener("click", () => switchTab("overview"));
    document.getElementById("tab-btn-pv").addEventListener("click", () => switchTab("pv"));
    document.getElementById("tab-btn-grid").addEventListener("click", () => switchTab("grid"));
    document.getElementById("tab-btn-eps").addEventListener("click", () => switchTab("eps"));


    
    document.getElementById("history-range").addEventListener("change", (e) => {
        const hours = Number.parseInt(e.target.value, 10);
        // Clear all charts
        Object.values(charts).forEach(c => {
            if (c) {
                c.data.labels = [];
                c.data.datasets.forEach(ds => ds.data = []);
                c.update('none');
            }
        });
        // Clear extremes
        for(let i=0; i<4; i++) { extremes.pv_v[i] = {min: Infinity, max: -Infinity}; extremes.pv_c[i] = {min: Infinity, max: -Infinity}; }
        for(let i=0; i<3; i++) { extremes.grid_v[i] = {min: Infinity, max: -Infinity}; extremes.grid_c[i] = {min: Infinity, max: -Infinity};
            extremes.eps_v[i] = {min: Infinity, max: -Infinity};
            extremes.eps_c[i] = {min: Infinity, max: -Infinity}; }
        statusAnnotations = {};
        lastStatus = null;
        
        currentHours = hours;
        loadHistory(hours);
    });
    
    // Auto-create DOM cards for phase arrays matching HEGG template
    const createGroup = (id, label, unit, count, l_prefix) => {
        const el = document.getElementById(id);
        if(!el) return;
        
        const colorMap = {
            'PV': [COLORS.pv1, COLORS.pv2, COLORS.pv3, COLORS.pv4],
            'L': [COLORS.l1, COLORS.l2, COLORS.l3]
        };

        let html = '';
        for(let i=1; i<=count; i++) {
            const chartId = `chart-${label.toLowerCase()[0]}-${l_prefix.toLowerCase()}${i}`;
            const valueId = `${l_prefix.toLowerCase()}${i}-${label.toLowerCase()[0]}`; // e.g. pv1-v, pv1-a
            
            const color = colorMap[l_prefix][i-1] || COLORS.pv1;
            html += `
            <article class="card card--phase card--with-chart">
              <div class="phase-row">
                <div class="phase-badge" style="background: ${color}; color: #fff;">${l_prefix}${i}</div>
                <div class="phase-value-group">
                  <div class="card-value" id="${valueId}" style="color: ${color}">—</div>
                  <div class="card-unit">${unit}</div>
                </div>
              </div>
              <div class="chart-wrapper chart-wrapper--inline">
                <canvas id="${chartId}" aria-label="${l_prefix}${i} ${label} history"></canvas>
              </div>
            </article>`;
        }
        el.innerHTML = html;
        
        // Initialize sparkline charts
        for(let i=1; i<=count; i++) {
            const chartId = `chart-${label.toLowerCase()[0]}-${l_prefix.toLowerCase()}${i}`;
            const color = colorMap[l_prefix][i-1] || COLORS.pv1;
            charts[chartId] = createChart(chartId, [{ label: `${l_prefix}${i} ${label}`, color: color }], false);
        }
    };

    createGroup('pv-v-cards', 'Voltage', 'V', 4, 'PV');
    createGroup('pv-a-cards', 'Current', 'A', 4, 'PV');
    createGroup('grid-v-cards', 'Voltage', 'V', 3, 'L');
    createGroup('grid-a-cards', 'Current', 'A', 3, 'L');
    createGroup('eps-v-cards', 'Voltage', 'V', 3, 'eps');
    createGroup('eps-a-cards', 'Current', 'A', 3, 'eps');

    charts.overview = createChart('chart-power', [
        { label: 'PV (W)', color: COLORS.pv1 },
        { label: 'Grid Net (W)', color: COLORS.net },
        { label: 'EPS (W)', color: COLORS.load }
    ]);
    charts.pv = createChart('chart-pv', [
        { label: 'Total', color: COLORS.delivered, borderWidth: 2 },
        { label: 'PV1', color: COLORS.pv1 }, { label: 'PV2', color: COLORS.pv2 },
        { label: 'PV3', color: COLORS.pv3 }, { label: 'PV4', color: COLORS.pv4 }
    ]);
    charts.grid = createChart('chart-grid', [
        {label: 'Net Grid', color: COLORS.net},
        {label: 'L1', color: COLORS.l1},
        {label: 'L2', color: COLORS.l2},
        {label: 'L3', color: COLORS.l3}
    ]);
    
    // Stack the L1/L2/L3 phases together as filled areas, leave Net Grid as an overlay line
    charts.grid.options.scales.y.stacked = true;
    charts.grid.data.datasets[0].stack = 'net';
    charts.grid.data.datasets[0].borderWidth = 3;
    
    for(let i=1; i<=3; i++) {
        charts.grid.data.datasets[i].stack = 'phases';
        charts.grid.data.datasets[i].fill = true;
    }
    charts.eps = createChart('chart-eps', [
        { label: 'EPS Total', color: COLORS.net },
        { label: 'L1', color: COLORS.l1 },
        { label: 'L2', color: COLORS.l2 },
        { label: 'L3', color: COLORS.l3 }
    ]);
    charts.eps.options.scales.y.stacked = true;
    charts.eps.data.datasets[0].stack = 'net';
    charts.eps.data.datasets[0].borderWidth = 3;
    for(let i=1; i<=3; i++) {
        charts.eps.data.datasets[i].stack = 'phases';
        charts.eps.data.datasets[i].fill = true;
    }

    const tickClock = () => {
        const el = document.getElementById("header-time");
        if(el) el.innerText = new Date().toLocaleTimeString();
    };
    tickClock();
    setInterval(tickClock, 1000);

    loadHistory(currentHours);
    connectSSE();
    recolorCharts();
});

let currentHours = 24;

function createChart(id, series, showLegend = true) {
    const el = document.getElementById(id);
    if(!el) return null;
    const ctx = el.getContext('2d');
    
    const datasets = series.map(s => {
        return {
            label: s.label, 
            borderColor: s.color, 
            backgroundColor: s.color,
            data: [], 
            fill: false, 
            tension: 0.1, 
            pointRadius: 0,
            borderWidth: 2,
            borderCapStyle: 'round'
        };
    });

    const opts = {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
            annotation: { annotations: {} },
            legend: { 
                display: showLegend, 
                position: 'bottom',
                labels: { usePointStyle: true, boxWidth: 8, padding: 20 }
            },
            tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.9)',
                titleFont: { size: 13, family: 'JetBrains Mono' },
                bodyFont: { size: 13, family: 'JetBrains Mono' },
                padding: 12,
                cornerRadius: 8,
                displayColors: true
            }
        },
        scales: {
            x: { 
                type: "time", 
                time: { tooltipFormat: "HH:mm" }, 
                grid: { display: true, color: "rgba(100, 100, 100, 0.1)" },
                ticks: { maxTicksLimit: 6, display: showLegend },
                border: { display: showLegend }
            },
            y: { 
                grid: { color: "rgba(100, 100, 100, 0.1)", borderDash: [5, 5] }
            }
        }
    };

    return new Chart(ctx, { type: 'line', data: { labels: [], datasets: datasets }, options: opts });
}

function updateDOM(id, val) {
    const el = document.getElementById(id);
    if(el && el.innerText !== String(val)) el.innerText = val;
}

async function loadHistory(hours = 24) {
    try {
        const res = await fetch(`/api/history?hours=${hours}`);
        if(!res.ok) return;
        const data = await res.json();
        if(data.length === 0) return;
        
        const labels = [];
        const ds = { overview: [[],[],[]], pv: [[],[],[],[],[]], grid: [[],[],[],[]], eps: [[],[],[],[]] };
        
        // Initialize arrays for sparklines
        for(let i=1; i<=4; i++) { ds[`chart-v-pv${i}`] = [[]]; ds[`chart-c-pv${i}`] = [[]]; }
        for(let i=1; i<=3; i++) { ds[`chart-v-l${i}`] = [[]]; ds[`chart-c-l${i}`] = [[]]; }

        let firstTs = null;

        data.forEach(d => {
            labels.push(d.ts);
            if (!firstTs) firstTs = d.ts;
            lastTs = d.ts;
            
            let statusStr = STATUS_MAP[d.status_code] || "UNKNOWN";
            if (statusStr !== lastStatus && lastStatus !== null) {
                statusAnnotations[`status_${d.ts}`] = buildStatusAnnotation(d.ts, statusStr);
            }
            lastStatus = statusStr;

            ds.overview[0].push(Math.round(d.pv_total_w_mean)); ds.overview[1].push(Math.round(-d.meter_total_w_mean)); ds.overview[2].push(Math.round(d.eps_p_mean));
            ds.pv[0].push(Math.round(d.pv_total_w_mean)); ds.pv[1].push(Math.round(d.pv1_w_mean)); ds.pv[2].push(Math.round(d.pv2_w_mean)); ds.pv[3].push(Math.round(d.pv3_w_mean)); ds.pv[4].push(Math.round(d.pv4_w_mean));
            ds.grid[0].push(Math.round(-d.meter_total_w_mean)); ds.grid[1].push(Math.round(d.grid_l1_v_mean * d.grid_l1_a_mean)); ds.grid[2].push(Math.round(d.grid_l2_v_mean * d.grid_l2_a_mean)); ds.grid[3].push(Math.round(d.grid_l3_v_mean * d.grid_l3_a_mean));
            ds.eps[0].push(Math.round(d.eps_p_mean)); ds.eps[1].push(Math.round(d.eps_l1_v_mean * d.eps_l1_a_mean)); ds.eps[2].push(Math.round(d.eps_l2_v_mean * d.eps_l2_a_mean)); ds.eps[3].push(Math.round(d.eps_l3_v_mean * d.eps_l3_a_mean));
            
            for(let i=1; i<=4; i++) {
                let v = d[`pv${i}_v_mean`], c = d[`pv${i}_a_mean`];
                ds[`chart-v-pv${i}`][0].push(v); ds[`chart-c-pv${i}`][0].push(c);
                if(v < extremes.pv_v[i-1].min) extremes.pv_v[i-1].min = v;
                if(v > extremes.pv_v[i-1].max) extremes.pv_v[i-1].max = v;
                if(c < extremes.pv_c[i-1].min) extremes.pv_c[i-1].min = c;
                if(c > extremes.pv_c[i-1].max) extremes.pv_c[i-1].max = c;
            }
            for(let i=1; i<=3; i++) {
                let v = d[`grid_l${i}_v_mean`], c = d[`grid_l${i}_a_mean`];
                ds[`chart-v-l${i}`][0].push(v); ds[`chart-c-l${i}`][0].push(c);
                if(v < extremes.grid_v[i-1].min) extremes.grid_v[i-1].min = v;
                if(v > extremes.grid_v[i-1].max) extremes.grid_v[i-1].max = v;
                if(c < extremes.grid_c[i-1].min) extremes.grid_c[i-1].min = c;
                if(c > extremes.grid_c[i-1].max) extremes.grid_c[i-1].max = c;

                let ev = d[`eps_l${i}_v_mean`], ec = d[`eps_l${i}_a_mean`];
                if(ev < extremes.eps_v[i-1].min) extremes.eps_v[i-1].min = ev;
                if(ev > extremes.eps_v[i-1].max) extremes.eps_v[i-1].max = ev;
                if(ec < extremes.eps_c[i-1].min) extremes.eps_c[i-1].min = ec;
                if(ec > extremes.eps_c[i-1].max) extremes.eps_c[i-1].max = ec;
            }
        });
        
        const flooredMin = Date.now() - hours * 3600000;

        // Apply global sync and datasets
        Object.keys(charts).forEach(k => {
            if(!charts[k] || !ds[k]) return;
            charts[k].options.scales.x.min = flooredMin;
            charts[k].options.plugins.annotation.annotations = { ...statusAnnotations };
            charts[k].data.labels = [...labels];
            charts[k].data.datasets.forEach((c, i) => c.data = [...(ds[k][i] || [])]);
        });

        // Sync axes Y and Min/Max labels
        const pvVCharts = [1,2,3,4].map(i => charts[`chart-v-pv${i}`]);
        const pvCCharts = [1,2,3,4].map(i => charts[`chart-c-pv${i}`]);
        const gridVCharts = [1,2,3].map(i => charts[`chart-v-grid${i}`]);
        const gridCCharts = [1,2,3].map(i => charts[`chart-c-grid${i}`]);
        
        syncChartScales(pvVCharts, extremes.pv_v, 0);
        syncChartScales(pvCCharts, extremes.pv_c, 0);
        syncChartScales(gridVCharts, extremes.grid_v, 0);
        syncChartScales(gridCCharts, extremes.grid_c, 0);
        const epsVCharts = [1,2,3].map(i => charts[`chart-v-eps${i}`]);
        const epsCCharts = [1,2,3].map(i => charts[`chart-c-eps${i}`]);
        syncChartScales(epsVCharts, extremes.eps_v, 0);
        syncChartScales(epsCCharts, extremes.eps_c, 0);


        for(let i=1; i<=4; i++) {
            updateSparklineAnnotations(charts[`chart-v-pv${i}`], extremes.pv_v[i-1].min, extremes.pv_v[i-1].max, COLORS[`pv${i}`]);
            updateSparklineAnnotations(charts[`chart-c-pv${i}`], extremes.pv_c[i-1].min, extremes.pv_c[i-1].max, COLORS[`pv${i}`]);
        }
        for(let i=1; i<=3; i++) {
            updateSparklineAnnotations(charts[`chart-v-grid${i}`], extremes.grid_v[i-1].min, extremes.grid_v[i-1].max, COLORS[`l${i}`]);
            updateSparklineAnnotations(charts[`chart-c-grid${i}`], extremes.grid_c[i-1].min, extremes.grid_c[i-1].max, COLORS[`l${i}`]);
            updateSparklineAnnotations(charts[`chart-v-eps${i}`], extremes.eps_v[i-1].min, extremes.eps_v[i-1].max, COLORS[`l${i}`]);
            updateSparklineAnnotations(charts[`chart-c-eps${i}`], extremes.eps_c[i-1].min, extremes.eps_c[i-1].max, COLORS[`l${i}`]);
        }
        
        Object.values(charts).forEach(c => { if(c) c.update('none'); });
    } catch(e) {
        console.error("Error fetching historical data:", e);
    }
}

function pushChart(chart, ts, values) {
    if(!chart) return;
    chart.data.labels.push(ts);
    for(let i=0; i<values.length; i++) chart.data.datasets[i].data.push(values[i]);
    chart.update('none');
}

function connectSSE() {
    const es = new EventSource("/stream");
    es.addEventListener("reading", (e) => {
        const d = JSON.parse(e.data);
        const ts = d.ts;
        
        
        updateDOM("sum-pv", d.pv_total_w.toFixed(0));
        updateDOM("sum-pv-val", d.pv_total_w.toFixed(0)); // Header of PV tab
        updateDOM("sum-pv-stat", STATUS_MAP[d.status_code] || "UNKNOWN");
        updateDOM("sum-pv-today", d.pv_today_kwh.toFixed(1));
        updateDOM("sum-pv-total", d.pv_total_kwh.toFixed(0));

        updateDOM("sum-grid", Math.abs(d.meter_total_w).toFixed(0));
        updateDOM("sum-grid-val", Math.abs(d.meter_total_w).toFixed(0)); // Header of Grid tab
        updateDOM("sum-grid-stat", d.meter_total_w >= 0 ? "Exporting" : "Importing");
        updateDOM("sum-grid-today", d.meter_total_w >= 0 ? d.grid_export_today_kwh.toFixed(1) : d.grid_import_today_kwh.toFixed(1));
        // Hardcode "total ever" until we add it, or just show Export for now
        updateDOM("sum-grid-total", d.grid_export_today_kwh.toFixed(0));

        updateDOM("sum-bat", d.bat_soc.toFixed(1));
        
        if (d.bat_nominal_kwh > 0) {
            const bat_kwh = (d.bat_soc / 100) * d.bat_nominal_kwh;
            updateDOM("sum-bat-kwh", bat_kwh.toFixed(1));
            const autonomy = d.load_p > 0 ? (bat_kwh * 1000 / d.load_p).toFixed(1) : "—";
            updateDOM("sum-bat-autonomy", autonomy);
        } else {
            updateDOM("sum-bat-kwh", "—");
            updateDOM("sum-bat-autonomy", "—");
        }
        
        updateDOM("sum-load", d.eps_p.toFixed(0));
        updateDOM("sum-load-today", "—");
        
        // Explicitly ignoring L1/L2/L3 house load splits since we cannot derive them purely from the Modbus data without assumptions
        updateDOM("overview-net-val", d.meter_total_w.toFixed(0));


        
        
        // Update DOM metrics
        updateDOM("meta-model", d.inverter_model);
        updateDOM("meta-serial", d.inverter_serial);
        updateDOM("meta-fw", d.inverter_firmware);
        updateDOM("meta-rated", (d.rated_power_w ? (d.rated_power_w / 1000).toFixed(1) + " kW" : "—"));
        updateDOM("meta-e-today", d.pv_today_kwh.toFixed(1) + " kWh");
        updateDOM("meta-e-total", d.pv_total_kwh.toFixed(1) + " kWh");

        const flooredMin = Date.now() - currentHours * 3600000;
        let statusStr = STATUS_MAP[d.status_code] || "UNKNOWN";
        if (statusStr !== lastStatus && lastStatus !== null) {
            statusAnnotations[`status_${d.ts}`] = buildStatusAnnotation(d.ts, statusStr);
            Object.values(charts).forEach(chart => {
                if(chart) {
                    chart.options.scales.x.min = flooredMin;
                    chart.options.plugins.annotation.annotations = { ...chart.options.plugins.annotation.annotations, ...statusAnnotations };
                }
            });
        } else {
            Object.values(charts).forEach(chart => {
                if(chart) {
                    chart.options.scales.x.min = flooredMin;
                }
            });
        }
        lastStatus = statusStr;
        updateDOM("meta-status", statusStr);
        
        for (let i = 1; i <= 4; i++) {
            let v = d[`pv${i}_v`] || 0, c = d[`pv${i}_a`] || 0;
            updateDOM(`pv${i}-c`, c.toFixed(1)); 
            updateDOM(`pv${i}-v`, v.toFixed(1));
            pushChart(charts[`chart-v-pv${i}`], ts, [v]);
            pushChart(charts[`chart-c-pv${i}`], ts, [c]);
            
            if(v < extremes.pv_v[i-1].min) extremes.pv_v[i-1].min = v;
            if(v > extremes.pv_v[i-1].max) extremes.pv_v[i-1].max = v;
            if(c < extremes.pv_c[i-1].min) extremes.pv_c[i-1].min = c;
            if(c > extremes.pv_c[i-1].max) extremes.pv_c[i-1].max = c;
        }
        for (let i = 1; i <= 3; i++) {
            let v = d[`grid_l${i}_v`] || 0, c = d[`grid_l${i}_a`] || 0;
            updateDOM(`l${i}-c`, c.toFixed(1)); 
            updateDOM(`l${i}-v`, v.toFixed(1));
            pushChart(charts[`chart-v-l${i}`], ts, [v]);
            pushChart(charts[`chart-c-l${i}`], ts, [c]);
            
            if(v < extremes.grid_v[i-1].min) extremes.grid_v[i-1].min = v;
            if(v > extremes.grid_v[i-1].max) extremes.grid_v[i-1].max = v;
            if(c < extremes.grid_c[i-1].min) extremes.grid_c[i-1].min = c;
            if(c > extremes.grid_c[i-1].max) extremes.grid_c[i-1].max = c;
            let ev = d[`eps_l${i}_v`] || 0, ec = d[`eps_l${i}_a`] || 0;
            if(ev < extremes.eps_v[i-1].min) extremes.eps_v[i-1].min = ev;
            if(ev > extremes.eps_v[i-1].max) extremes.eps_v[i-1].max = ev;
            if(ec < extremes.eps_c[i-1].min) extremes.eps_c[i-1].min = ec;
            if(ec > extremes.eps_c[i-1].max) extremes.eps_c[i-1].max = ec;

        }
        
        // Live Sync
        const pvVCharts = [1,2,3,4].map(i => charts[`chart-v-pv${i}`]);
        const pvCCharts = [1,2,3,4].map(i => charts[`chart-c-pv${i}`]);
        const gridVCharts = [1,2,3].map(i => charts[`chart-v-l${i}`]);
        const gridCCharts = [1,2,3].map(i => charts[`chart-c-l${i}`]);
        syncChartScales(pvVCharts, extremes.pv_v, 0);
        syncChartScales(pvCCharts, extremes.pv_c, 0);
        syncChartScales(gridVCharts, extremes.grid_v, 0);
        syncChartScales(gridCCharts, extremes.grid_c, 0);
        const epsVCharts = [1,2,3].map(i => charts[`chart-v-eps${i}`]);
        const epsCCharts = [1,2,3].map(i => charts[`chart-c-eps${i}`]);
        syncChartScales(epsVCharts, extremes.eps_v, 0);
        syncChartScales(epsCCharts, extremes.eps_c, 0);

        
        for(let i=1; i<=4; i++) {
            updateSparklineAnnotations(charts[`chart-v-pv${i}`], extremes.pv_v[i-1].min, extremes.pv_v[i-1].max, COLORS[`pv${i}`]);
            updateSparklineAnnotations(charts[`chart-c-pv${i}`], extremes.pv_c[i-1].min, extremes.pv_c[i-1].max, COLORS[`pv${i}`]);
        }
        for(let i=1; i<=3; i++) {
            updateSparklineAnnotations(charts[`chart-v-l${i}`], extremes.grid_v[i-1].min, extremes.grid_v[i-1].max, COLORS[`l${i}`]);
            updateSparklineAnnotations(charts[`chart-c-l${i}`], extremes.grid_c[i-1].min, extremes.grid_c[i-1].max, COLORS[`l${i}`]);
            updateSparklineAnnotations(charts[`chart-v-eps${i}`], extremes.eps_v[i-1].min, extremes.eps_v[i-1].max, COLORS[`l${i}`]);
            updateSparklineAnnotations(charts[`chart-c-eps${i}`], extremes.eps_c[i-1].min, extremes.eps_c[i-1].max, COLORS[`l${i}`]);
        }
        
        Object.values(charts).forEach(c => { if(c) c.update('none'); });
        
        const sl = document.getElementById("status-label");
        if(sl) sl.innerText = statusStr;

        // --- Cute Flow Diagram Animation ---
        updateDOM("flow-pv", d.pv_total_w.toFixed(0) + " W");
        updateDOM("flow-grid", Math.abs(d.meter_total_w).toFixed(0) + " W");
        updateDOM("flow-bat", Math.abs(d.bat_p).toFixed(0) + " W");
        updateDOM("flow-load", d.load_p.toFixed(0) + " W");

        const lPvInv = document.getElementById("line-pv-inv");
        const lInvGrid = document.getElementById("line-inv-grid");
        const lInvBat = document.getElementById("line-inv-bat");
        const lInvLoad = document.getElementById("line-inv-load");

        if(lPvInv) {
            lPvInv.classList.toggle("active", d.pv_total_w > 10);
        }
        if(lInvGrid) {
            lInvGrid.classList.toggle("active", Math.abs(d.meter_total_w) > 10);
            if (d.meter_total_w > 0) {
                lInvGrid.classList.add("export"); // Forward
                lInvGrid.classList.remove("import");
            } else {
                lInvGrid.classList.add("import"); // Reverse
                lInvGrid.classList.remove("export");
            }
        }
        if(lInvBat) {
            lInvBat.classList.toggle("active", Math.abs(d.bat_p) > 10);
            if (d.bat_p > 0) {
                lInvBat.classList.add("charging"); // Forward (Inverter -> Bat)
                lInvBat.classList.remove("discharging");
            } else {
                lInvBat.classList.add("discharging"); // Reverse (Bat -> Inverter)
                lInvBat.classList.remove("charging");
            }
        }
        if(lInvLoad) {
            lInvLoad.classList.toggle("active", d.load_p > 10);
        }

        // Overview Totals (Row under chart)
        updateDOM("ov-pv-today", d.pv_today_kwh.toFixed(1));
        updateDOM("ov-grid-in-today", d.grid_import_today_kwh.toFixed(1));
        updateDOM("ov-load-today", d.load_today_kwh.toFixed(1));
        updateDOM("ov-bat-in-today", d.bat_charge_today_kwh.toFixed(1));

        // Power net val
        updateDOM("power-net-val", Math.abs(d.meter_total_w).toFixed(0));
        updateDOM("power-direction", d.meter_total_w >= 0 ? "Exporting" : "Importing");
        
        // --- End Flow Diagram ---

        for(let i=1; i<=4; i++) {
            updateDOM(`pv${i}-v`, d[`pv${i}_v`].toFixed(1));
            updateDOM(`pv${i}-a`, d[`pv${i}_a`].toFixed(1));
            updateDOM(`pv${i}-w`, d[`pv${i}_w`].toFixed(0));
        }

        const g1w = d.grid_l1_v * d.grid_l1_a;
        const g2w = d.grid_l2_v * d.grid_l2_a;
        const g3w = d.grid_l3_v * d.grid_l3_a;
        for(let i=1; i<=3; i++) {
            updateDOM(`l${i}-v`, d[`grid_l${i}_v`].toFixed(1));
            updateDOM(`l${i}-c`, d[`grid_l${i}_a`].toFixed(1));
        }
        updateDOM(`l1-w`, g1w.toFixed(0));
        updateDOM(`l2-w`, g2w.toFixed(0));
        updateDOM(`l3-w`, g3w.toFixed(0));

        
        
        
        updateDOM("bat-soc", d.bat_soc.toFixed(1));

        pushChart(charts.overview, ts, [Math.round(d.pv_total_w), Math.round(-d.meter_total_w), Math.round(d.eps_p)]);
        pushChart(charts.pv, ts, [Math.round(d.pv_total_w), Math.round(d.pv1_w), Math.round(d.pv2_w), Math.round(d.pv3_w), Math.round(d.pv4_w)]);
        pushChart(charts.grid, ts, [Math.round(-d.meter_total_w), Math.round(g1w), Math.round(g2w), Math.round(g3w)]);
        const e1w = (d.eps_l1_v || 0) * (d.eps_l1_a || 0);
        const e2w = (d.eps_l2_v || 0) * (d.eps_l2_a || 0);
        const e3w = (d.eps_l3_v || 0) * (d.eps_l3_a || 0);
        for(let i=1; i<=3; i++) {
            updateDOM(`eps${i}-v`, (d[`eps_l${i}_v`] || 0).toFixed(1));
            updateDOM(`eps${i}-a`, (d[`eps_l${i}_a`] || 0).toFixed(1));
        }
        updateDOM("sum-eps-val", Math.abs(d.eps_p).toFixed(0));
        pushChart(charts.eps, ts, [Math.round(d.eps_p), Math.round(e1w), Math.round(e2w), Math.round(e3w)]);
    });
}

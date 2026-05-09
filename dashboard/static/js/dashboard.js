
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
  if (!chart.options.plugins.annotation) chart.options.plugins.annotation = { annotations: {} };
  const anns = chart.options.plugins.annotation.annotations;
  
  anns.minLine = {
      type: 'line', yMin: min, yMax: min, borderColor: cStr, borderWidth: 1, borderDash: [2, 2],
      label: { display: true, content: min.toFixed(1), position: 'end', backgroundColor: bg, color: '#fff', font: {size: 9, weight: '600'}, padding: {x: 4, y: 2}, borderRadius: 4 }
  };
  anns.maxLine = {
      type: 'line', yMin: max, yMax: max, borderColor: cStr, borderWidth: 1, borderDash: [2, 2],
      label: { display: true, content: max.toFixed(1), position: 'start', backgroundColor: bg, color: '#fff', font: {size: 9, weight: '600'}, padding: {x: 4, y: 2}, borderRadius: 4 }
  };
}

const extremes = {
    pv_v: Array.from({length: 4}, () => ({min: Infinity, max: -Infinity})),
    pv_c: Array.from({length: 4}, () => ({min: Infinity, max: -Infinity})),
    grid_v: Array.from({length: 3}, () => ({min: Infinity, max: -Infinity})),
    grid_c: Array.from({length: 3}, () => ({min: Infinity, max: -Infinity})),
    grid_ll: Array.from({length: 3}, () => ({min: Infinity, max: -Infinity})),
    eps_v: Array.from({length: 3}, () => ({min: Infinity, max: -Infinity})),
    eps_c: Array.from({length: 3}, () => ({min: Infinity, max: -Infinity}))
};
let statusAnnotations = {};
let lastStatus = null;


const charts = {};
const maxPoints = 60;
const STATUS_MAP = {
    0: "STANDBY",
    1: "SELF-TEST",
    3: "FAULT",
    4: "UPGRADE",
    5: "NORMAL",    // PV online, battery offline
    6: "NORMAL",    // PV + battery online
    7: "OFF-GRID",  // PV + battery, off-grid
    8: "OFF-GRID",  // battery only, off-grid
    9: "BYPASS",
};

/**
 * Map an inverter status string to a CSS modifier class for the header dot.
 *
 * Classes correspond to CSS rules on .status-dot:
 *   inv-normal  bright green  — PV/battery actively on-grid
 *   inv-bypass  dark green    — power flowing through bypass relay
 *   inv-fault   red           — hardware or protection fault
 *   inv-other   amber         — standby, self-test, upgrade, off-grid, unknown
 *
 * @param {string} str - A value from STATUS_MAP or "UNKNOWN".
 * @returns {string} CSS class name.
 */
function inverterDotClass(str) {
    if (str === "NORMAL")  return "inv-normal";
    if (str === "BYPASS")  return "inv-bypass";
    if (str === "FAULT")   return "inv-fault";
    return "inv-other";
}
const FAULT_MAP = {
    101: "Communication fault (Internal)",
    116: "EEPROM fault",
    119: "GFCI (Ground Fault) damage",
    120: "HCT (Current Sensor) fault",
    121: "Communication failure (Master/Slave)",
    200: "AFCI (Arc Fault) detected",
    201: "Leakage current too high",
    202: "PV voltage high",
    203: "PV insulation resistance low",
    204: "PV terminals reversed",
    300: "AC voltage out of range",
    302: "No AC connection",
    303: "NE (Neutral-Earth) abnormal",
    304: "AC frequency out of range",
    403: "Unbalanced output current",
    405: "Relay fault",
    408: "NTC (Temperature) too high",
    411: "BMS communication fault",
    412: "Temperature sensor connection incorrect",
    417: "EPS output voltage abnormal"
};

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
    pv1: '#3b82f6', pv2: '#8b5cf6', pv3: '#ec4899', load: '#a855f7',
    ll12: v('--wye-l12') || '#a78bfa',
    ll13: v('--wye-l13') || '#34d399',
    ll23: v('--wye-l23') || '#fbbf24',
  };
}
let COLORS = chartPalette();

/** @type {object} Cached CSS colour tokens for the wye canvas draw functions. */
let WYE_CSS = {};

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
  // Refresh the wye CSS token cache so canvas draws pick up the new theme.
  WYE_CSS = {
    cl1:     s.getPropertyValue("--phase-l1").trim(),
    cl2:     s.getPropertyValue("--phase-l2").trim(),
    cl3:     s.getPropertyValue("--phase-l3").trim(),
    cl12:    s.getPropertyValue("--wye-l12").trim(),
    cl13:    s.getPropertyValue("--wye-l13").trim(),
    cl23:    s.getPropertyValue("--wye-l23").trim(),
    neutral: s.getPropertyValue("--wye-neutral").trim(),
    grid,
    text:    tick,
    dim:     s.getPropertyValue("--text-dim").trim(),
  };
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
    // Wye canvases live in a hidden tab at init time; getBoundingClientRect()
    // returns zero until the tab is first shown.  Resize both canvases here.
    if (id === 'grid') {
        resizeWyeCanvas();
        resizeNeutralCanvas();
    }
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

    recolorCharts();   // populate WYE_CSS before first draw
    initWyeDiagram();

    
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
        for(let i=0; i<3; i++) { extremes.pv_v[i] = {min: Infinity, max: -Infinity}; extremes.pv_c[i] = {min: Infinity, max: -Infinity}; }
        for(let i=0; i<3; i++) { extremes.grid_v[i] = {min: Infinity, max: -Infinity}; extremes.grid_c[i] = {min: Infinity, max: -Infinity};
            extremes.grid_ll[i] = {min: Infinity, max: -Infinity};
            extremes.eps_v[i] = {min: Infinity, max: -Infinity};
            extremes.eps_c[i] = {min: Infinity, max: -Infinity}; }
        statusAnnotations = {};
        lastStatus = null;
        
        currentHours = hours;
        loadHistory(hours);
    });
    
    // Auto-create DOM cards for phase arrays matching HEGG template
    const createGroup = (id, label, unit, count, l_prefix, labels) => {
        const el = document.getElementById(id);
        if(!el) return;
        
        const colorMap = {
            'PV':  [COLORS.pv1, COLORS.pv2, COLORS.pv3],
            'L':   [COLORS.l1, COLORS.l2, COLORS.l3],
            'LL':  [COLORS.ll12, COLORS.ll13, COLORS.ll23],
            'eps': [COLORS.l1, COLORS.l2, COLORS.l3]
        };

        let html = '';
        for(let i=1; i<=count; i++) {
            const chartId = `chart-${label.toLowerCase()[0]}-${l_prefix.toLowerCase()}${i}`;
            const valueId = `${l_prefix.toLowerCase()}${i}-${label.toLowerCase()[0]}`;
            const badgeLabel = labels ? labels[i-1] : `${l_prefix}${i}`;
            const color = (colorMap[l_prefix] || [])[i-1] || COLORS.pv1;
            html += `
            <article class="card card--phase card--with-chart">
              <div class="phase-row">
                <div class="phase-badge" style="background: ${color}; color: #fff;">${badgeLabel}</div>
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

    createGroup('pv-v-cards', 'Voltage', 'V', 3, 'PV');
    createGroup('pv-a-cards', 'Current', 'A', 3, 'PV');
    createGroup('grid-v-cards', 'Voltage', 'V', 3, 'L');
    createGroup('grid-a-cards', 'Current', 'A', 3, 'L');
    createGroup('grid-ll-cards', 'Voltage', 'V', 3, 'LL', ['L1\u2013L2', 'L2\u2013L3', 'L1\u2013L3']);
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
        { label: 'PV3', color: COLORS.pv3 }
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
    charts.eps.options.scales.y.min = 0;
    charts.eps.data.datasets[0].stack = 'net';
    charts.eps.data.datasets[0].borderWidth = 3;
    for(let i=1; i<=3; i++) {
        charts.eps.data.datasets[i].stack = 'phases';
        charts.eps.data.datasets[i].fill = true;
    }
    
    charts.freq = createChart('chart-freq', [{ label: 'Grid Freq', color: COLORS.pv1 }], false);
    charts.invTemp = createChart('chart-inv-temp', [{ label: 'Inverter Temp', color: COLORS.l1 }], false);
    charts.bstTemp = createChart('chart-bst-temp', [{ label: 'Boost Temp', color: COLORS.l2 }], false);

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
        const ds = { overview: [[],[],[]], pv: [[],[],[],[]], grid: [[],[],[],[]], eps: [[],[],[],[]], freq: [[]], invTemp: [[]], bstTemp: [[]] };
        
        // Initialize arrays for sparklines
        for(let i=1; i<=3; i++) { ds[`chart-v-pv${i}`] = [[]]; ds[`chart-c-pv${i}`] = [[]]; }
        for(let i=1; i<=3; i++) { ds[`chart-v-l${i}`] = [[]]; ds[`chart-c-l${i}`] = [[]]; }
        const llKeys = ['rs', 'st', 'tr'];
        for(let i=1; i<=3; i++) { ds[`chart-v-ll${i}`] = [[]]; }

        let firstTs = null;

        data.forEach(d => {
            labels.push(d.ts);
            if (!firstTs) firstTs = d.ts;

            
            let statusStr = STATUS_MAP[d.status_code] || "UNKNOWN";
            if (statusStr !== lastStatus && lastStatus !== null) {
                statusAnnotations[`status_${d.ts}`] = buildStatusAnnotation(d.ts, statusStr);
            }
            lastStatus = statusStr;

            ds.overview[0].push(Math.round(d.pv_total_w_mean)); ds.overview[1].push(Math.round(-d.meter_total_w_mean)); ds.overview[2].push(Math.round(d.eps_p_mean));
            ds.pv[0].push(Math.round(d.pv_total_w_mean)); ds.pv[1].push(Math.round(d.pv1_w_mean)); ds.pv[2].push(Math.round(d.pv2_w_mean)); ds.pv[3].push(Math.round(d.pv3_w_mean));
            ds.grid[0].push(Math.round(-d.meter_total_w_mean)); ds.grid[1].push(Math.round(d.grid_l1_v_mean * d.grid_l1_a_mean)); ds.grid[2].push(Math.round(d.grid_l2_v_mean * d.grid_l2_a_mean)); ds.grid[3].push(Math.round(d.grid_l3_v_mean * d.grid_l3_a_mean));
            ds.eps[0].push(Math.round(d.eps_p_mean)); ds.eps[1].push(Math.round(d.eps_l1_v_mean * d.eps_l1_a_mean)); ds.eps[2].push(Math.round(d.eps_l2_v_mean * d.eps_l2_a_mean)); ds.eps[3].push(Math.round(d.eps_l3_v_mean * d.eps_l3_a_mean));
            let freq = d.grid_freq_mean === 0 ? null : d.grid_freq_mean;
            let inv = d.inverter_temp_mean === 0 ? null : d.inverter_temp_mean;
            let bst = d.boost_temp_mean === 0 ? null : d.boost_temp_mean;
            ds.freq[0].push(freq); ds.invTemp[0].push(inv); ds.bstTemp[0].push(bst);
            
            for(let i=1; i<=3; i++) {
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

                let llv = d[[`grid_ll_rs_v_mean`, `grid_ll_st_v_mean`, `grid_ll_tr_v_mean`][i-1]] || 0;
                ds[`chart-v-ll${i}`][0].push(llv);
                if(llv < extremes.grid_ll[i-1].min) extremes.grid_ll[i-1].min = llv;
                if(llv > extremes.grid_ll[i-1].max) extremes.grid_ll[i-1].max = llv;
            }
        });
        
        const flooredMin = Date.now() - hours * 3600000;

        // Apply global sync and datasets
        Object.keys(charts).forEach(k => {
            if(!charts[k] || !ds[k]) return;
            charts[k].options.scales.x.min = flooredMin;
            charts[k].options.plugins.annotation.annotations = Object.assign({}, statusAnnotations);
            charts[k].data.labels = [...labels];
            charts[k].data.datasets.forEach((c, i) => c.data = [...(ds[k][i] || [])]);
        });

        // Sync axes Y and Min/Max labels
        const pvVCharts = [1,2,3,4].map(i => charts[`chart-v-pv${i}`]);
        const pvCCharts = [1,2,3,4].map(i => charts[`chart-c-pv${i}`]);
        const gridVCharts = [1,2,3].map(i => charts[`chart-v-l${i}`]);
        const gridCCharts = [1,2,3].map(i => charts[`chart-c-l${i}`]);
        
        syncChartScales(pvVCharts, extremes.pv_v, 0);
        syncChartScales(pvCCharts, extremes.pv_c, 0);
        syncChartScales(gridVCharts, extremes.grid_v, 0);
        syncChartScales(gridCCharts, extremes.grid_c, 0);
        const gridLLCharts = [1,2,3].map(i => charts[`chart-v-ll${i}`]);
        syncChartScales(gridLLCharts, extremes.grid_ll, 0);
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
            updateSparklineAnnotations(charts[`chart-v-ll${i}`], extremes.grid_ll[i-1].min, extremes.grid_ll[i-1].max, COLORS[`l${i}`]);
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
        updateDOM("meta-temp", (d.inverter_temp !== undefined ? d.inverter_temp.toFixed(1) + " °C" : "—"));
        
        let faultStr = "—";
        if (d.fault_code !== undefined) {
            if (d.fault_code === 0) {
                faultStr = "0 — None";
            } else {
                faultStr = `${d.fault_code} — ${FAULT_MAP[d.fault_code] || "Unknown Fault"}`;
            }
        }
        updateDOM("meta-fault", faultStr);

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

            const llKey = [`grid_ll_rs_v`, `grid_ll_st_v`, `grid_ll_tr_v`][i-1];
            const llv = d[llKey] || 0;
            updateDOM(`ll${i}-v`, llv.toFixed(1));
            pushChart(charts[`chart-v-ll${i}`], ts, [llv]);
            if(llv < extremes.grid_ll[i-1].min) extremes.grid_ll[i-1].min = llv;
            if(llv > extremes.grid_ll[i-1].max) extremes.grid_ll[i-1].max = llv;

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
        const gridLLCharts = [1,2,3].map(i => charts[`chart-v-ll${i}`]);
        syncChartScales(gridLLCharts, extremes.grid_ll, 0);
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
            updateSparklineAnnotations(charts[`chart-v-ll${i}`], extremes.grid_ll[i-1].min, extremes.grid_ll[i-1].max, COLORS[`l${i}`]);
            updateSparklineAnnotations(charts[`chart-v-eps${i}`], extremes.eps_v[i-1].min, extremes.eps_v[i-1].max, COLORS[`l${i}`]);
            updateSparklineAnnotations(charts[`chart-c-eps${i}`], extremes.eps_c[i-1].min, extremes.eps_c[i-1].max, COLORS[`l${i}`]);
        }
        
        Object.values(charts).forEach(c => { if(c) c.update('none'); });
        
        const sl  = document.getElementById("status-label");
        const dot = document.getElementById("status-dot");
        if (sl)  sl.innerText = statusStr;
        if (dot) {
            // Remove all inverter state classes then apply the current one.
            dot.classList.remove("inv-normal", "inv-bypass", "inv-fault", "inv-other");
            dot.classList.add(inverterDotClass(statusStr));
        }

        // --- Cute Flow Diagram Animation ---
        updateDOM("flow-pv", d.pv_total_w.toFixed(0) + " W");
        updateDOM("flow-grid", Math.abs(d.meter_total_w).toFixed(0) + " W");
        updateDOM("flow-bat", Math.abs(d.bat_p).toFixed(0) + " W");
        updateDOM("flow-load", d.eps_p.toFixed(0) + " W");

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
            lInvLoad.classList.toggle("active", d.eps_p > 10);
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

        for(let i=1; i<=3; i++) {
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

        // Update wye diagram with phase-to-neutral voltages.
        // grid_l1/2/3_v are already V_LN values (derived by the driver
        // from V_LL via _ll_to_ln() when Protocol II phase regs are absent).
        // grid_l1/2/3_v = V_LN (derived by driver); grid_ll_rs/st/tr_v = measured V_LL.
        // Pass both so the wye diagram shows measured LL values directly.
        updateWyeDiagram(
          d.grid_l1_v || 0, d.grid_l2_v || 0, d.grid_l3_v || 0,
          d.grid_ll_rs_v || 0, d.grid_ll_st_v || 0, d.grid_ll_tr_v || 0
        );

        updateDOM("bat-soc", d.bat_soc.toFixed(1));

        pushChart(charts.overview, ts, [Math.round(d.pv_total_w), Math.round(-d.meter_total_w), Math.round(d.eps_p)]);
        pushChart(charts.pv, ts, [Math.round(d.pv_total_w), Math.round(d.pv1_w), Math.round(d.pv2_w), Math.round(d.pv3_w)]);
        pushChart(charts.grid, ts, [Math.round(-d.meter_total_w), Math.round(g1w), Math.round(g2w), Math.round(g3w)]);
        const e1w = (d.eps_l1_v || 0) * (d.eps_l1_a || 0);
        const e2w = (d.eps_l2_v || 0) * (d.eps_l2_a || 0);
        const e3w = (d.eps_l3_v || 0) * (d.eps_l3_a || 0);
        for(let i=1; i<=3; i++) {
            updateDOM(`eps${i}-v`, (d[`eps_l${i}_v`] || 0).toFixed(1));
            updateDOM(`eps${i}-c`, (d[`eps_l${i}_a`] || 0).toFixed(1));
        }
        updateDOM("sum-eps-val", Math.abs(d.eps_p).toFixed(0));
        pushChart(charts.eps, ts, [Math.round(d.eps_p), Math.round(e1w), Math.round(e2w), Math.round(e3w)]);
        
        let freq = (d.grid_freq !== undefined && d.grid_freq !== 0) ? d.grid_freq : null;
        let inv = (d.inverter_temp !== undefined && d.inverter_temp !== 0) ? d.inverter_temp : null;
        let bst = (d.boost_temp !== undefined && d.boost_temp !== 0) ? d.boost_temp : null;
        
        updateDOM("val-freq", (freq !== null ? freq.toFixed(2) + " Hz" : "—"));
        updateDOM("val-inv-temp", (inv !== null ? inv.toFixed(1) + " °C" : "—"));
        updateDOM("val-bst-temp", (bst !== null ? bst.toFixed(1) + " °C" : "—"));
        pushChart(charts.freq, ts, [freq]);
        pushChart(charts.invTemp, ts, [inv]);
        pushChart(charts.bstTemp, ts, [bst]);
    });
}

/* ── 3-phase Wye phasor diagram ──────────────────────────────────────────── */

/**
 * Compute the magnitude of the line-to-line voltage between two phases,
 * assuming a 120° separation in the ideal wye arrangement.
 *
 * Cosine rule: |Va − Vb|² = Va² + Vb² − 2·Va·Vb·cos(120°)
 *                         = Va² + Vb² + Va·Vb   (cos 120° = −0.5)
 *
 * @param {number} va - Phase-to-neutral magnitude of the first phase (V).
 * @param {number} vb - Phase-to-neutral magnitude of the second phase (V).
 * @returns {number} Line voltage magnitude in volts.
 */
function lineVoltage(va, vb) {
  return Math.sqrt(va * va + vb * vb + va * vb);
}

/**
 * Compute the complex neutral shift relative to the system ground.
 *
 * In a balanced wye the neutral is the centroid of the three phasor tips
 * and the result is zero.
 * Angles: L1 = 0°, L2 = −120°, L3 = +120°.
 *
 * @param {number} v1 - L1 magnitude (V).
 * @param {number} v2 - L2 magnitude (V).
 * @param {number} v3 - L3 magnitude (V).
 * @returns {{ re: number, im: number }}
 */
function neutralShift(v1, v2, v3) {
  const d120 = (2 * Math.PI) / 3;
  return {
    re: (v1 + v2 * Math.cos(-d120) + v3 * Math.cos(d120)) / 3,
    im: (v2 * Math.sin(-d120) + v3 * Math.sin(d120)) / 3,
  };
}

/**
 * Compute per-phase voltage imbalance (NEMA definition).
 * Returns 100 × maxDeviation / mean.
 *
 * @param {number} v1
 * @param {number} v2
 * @param {number} v3
 * @returns {number} Imbalance factor (%).
 */
function voltageImbalance(v1, v2, v3) {
  const mean = (v1 + v2 + v3) / 3;
  if (mean === 0) return 0;
  return (Math.max(Math.abs(v1 - mean), Math.abs(v2 - mean), Math.abs(v3 - mean)) / mean) * 100;
}

/** @type {HTMLCanvasElement|null} */
let wyeCanvas = null;
/** @type {CanvasRenderingContext2D|null} */
let wyeCtx = null;
/** @type {HTMLCanvasElement|null} */
let neutralCanvas = null;
/** @type {CanvasRenderingContext2D|null} */
let neutralCtx = null;

/**
 * Initialise the wye canvas elements and attach resize listeners.
 * Called once from DOMContentLoaded after recolorCharts() has populated WYE_CSS.
 */
function initWyeDiagram() {
  wyeCanvas = document.getElementById("wye-canvas");
  if (!wyeCanvas) return;
  wyeCtx = wyeCanvas.getContext("2d");
  resizeWyeCanvas();
  window.addEventListener("resize", resizeWyeCanvas);

  neutralCanvas = document.getElementById("wye-neutral-canvas");
  if (neutralCanvas) {
    neutralCtx = neutralCanvas.getContext("2d");
    resizeNeutralCanvas();
    window.addEventListener("resize", resizeNeutralCanvas);
  }
}

/** Resize the main wye canvas pixel buffer to match CSS layout size. */
function resizeWyeCanvas() {
  if (!wyeCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = wyeCanvas.getBoundingClientRect();
  wyeCanvas.width  = rect.width  * dpr;
  wyeCanvas.height = rect.height * dpr;
  wyeCtx.scale(dpr, dpr);
}

/** Resize the mini neutral-offset canvas pixel buffer. */
function resizeNeutralCanvas() {
  if (!neutralCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = neutralCanvas.getBoundingClientRect();
  neutralCanvas.width  = rect.width  * dpr;
  neutralCanvas.height = rect.height * dpr;
  neutralCtx.scale(dpr, dpr);
}

/**
 * Draw the complete 3-phase wye phasor diagram.
 *
 * A 200 V display base is subtracted from each vector magnitude so inter-phase
 * deviations are visible at normal EU voltages (~230 V). IEC EN 50160
 * tolerance bands are drawn at 207 / 230 / 253 V relative to the same base.
 *
 * Chord labels use the directly measured line-to-line voltages (ll12, ll13,
 * ll23) rather than values computed from V_LN so they match the L-L cards.
 *
 * @param {number} v1   - L1 phase-to-neutral RMS voltage (V).
 * @param {number} v2   - L2 phase-to-neutral RMS voltage (V).
 * @param {number} v3   - L3 phase-to-neutral RMS voltage (V).
 * @param {number} ll12 - Measured V_RS (L1–L2) line voltage (V).
 * @param {number} ll13 - Measured V_TR (L1–L3) line voltage (V).
 * @param {number} ll23 - Measured V_ST (L2–L3) line voltage (V).
 */
function drawWyeDiagram(v1, v2, v3, ll12, ll13, ll23) {
  if (!wyeCtx || !wyeCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const W = wyeCanvas.width / dpr, H = wyeCanvas.height / dpr;
  const cx = W / 2, cy = H / 2;
  const BASE = 200, CEIL = 65;
  const dv1 = Math.max(v1 - BASE, 1), dv2 = Math.max(v2 - BASE, 1), dv3 = Math.max(v3 - BASE, 1);
  const scale = (Math.min(W, H) * 0.38) / CEIL;
  const cl1 = WYE_CSS.cl1 || "#60a5fa", cl2 = WYE_CSS.cl2 || "#34d399", cl3 = WYE_CSS.cl3 || "#f59e0b";
  const cl12 = WYE_CSS.cl12 || "#818cf8", cl13 = WYE_CSS.cl13 || "#fb7185", cl23 = WYE_CSS.cl23 || "#a78bfa";
  const cN = WYE_CSS.neutral || "#f472b6", cG = WYE_CSS.grid || "rgba(255,255,255,0.06)";
  const cT = WYE_CSS.text || "#9ca3af", cD = WYE_CSS.dim || "#4b5563";
  const ctx = wyeCtx;
  ctx.clearRect(0, 0, W, H);
  const toXY = (m, deg) => { const r = deg * Math.PI / 180; return { x: cx + m * scale * Math.cos(r), y: cy - m * scale * Math.sin(r) }; };
  const p1 = toXY(dv1, 90), p2 = toXY(dv2, -30), p3 = toXY(dv3, 210);
  const meanR = (dv1 + dv2 + dv3) / 3 * scale;
  for (let f = 0.25; f <= 1.01; f += 0.25) { ctx.beginPath(); ctx.arc(cx, cy, meanR * f, 0, 2 * Math.PI); ctx.strokeStyle = cG; ctx.lineWidth = 1; ctx.setLineDash([]); ctx.stroke(); }
  for (let a = 0; a < 360; a += 60) { const sp = toXY(CEIL, a); ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(sp.x, sp.y); ctx.strokeStyle = cG; ctx.lineWidth = 0.5; ctx.stroke(); }
  const iecRing = (dV, col, dash, lbl, ang) => { const r = dV * scale; ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI); ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.setLineDash(dash); ctx.stroke(); ctx.setLineDash([]); ctx.font = "9px 'JetBrains Mono', monospace"; ctx.fillStyle = col; ctx.textAlign = "center"; ctx.fillText(lbl, cx + (r + 5) * Math.cos(ang), cy - (r + 5) * Math.sin(ang)); };
  iecRing(7,  "rgba(251,146,60,0.55)",  [3, 3], "207 V", Math.PI * 0.25);
  iecRing(53, "rgba(251,146,60,0.55)",  [3, 3], "253 V", Math.PI * 0.25);
  iecRing(30, "rgba(255,255,255,0.30)", [5, 3], "230 V", Math.PI * 0.2);
  ctx.beginPath(); ctx.arc(cx, cy, meanR, 0, 2 * Math.PI); ctx.strokeStyle = cD; ctx.lineWidth = 1; ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]);
  const chord = (pa, pb, col, lbl, ox, oy) => { ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.setLineDash([6, 3]); ctx.stroke(); ctx.setLineDash([]); ctx.font = "bold 9px 'JetBrains Mono', monospace"; ctx.fillStyle = col; ctx.textAlign = "center"; ctx.fillText(lbl, (pa.x + pb.x) / 2 + ox, (pa.y + pb.y) / 2 + oy); };
  // Chord labels use measured V_LL values for accuracy; the geometric chord
  // position is still derived from V_LN phasor tips.
  chord(p1, p2, cl12, "L1\u2013L2 " + (ll12 || lineVoltage(v1, v2)).toFixed(1) + " V",  14, -6);
  chord(p1, p3, cl13, "L1\u2013L3 " + (ll13 || lineVoltage(v1, v3)).toFixed(1) + " V", -14, -6);
  chord(p2, p3, cl23, "L2\u2013L3 " + (ll23 || lineVoltage(v2, v3)).toFixed(1) + " V",   0, 14);
  const vec = (p, col, lbl, mag) => { ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(p.x, p.y); ctx.strokeStyle = col; ctx.lineWidth = 2.5; ctx.stroke(); const a = Math.atan2(cy - p.y, p.x - cx), hs = 8; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - hs * Math.cos(a - 0.35), p.y + hs * Math.sin(a - 0.35)); ctx.lineTo(p.x - hs * Math.cos(a + 0.35), p.y + hs * Math.sin(a + 0.35)); ctx.closePath(); ctx.fillStyle = col; ctx.fill(); ctx.beginPath(); ctx.arc(p.x, p.y, 4, 0, 2 * Math.PI); ctx.fillStyle = col; ctx.fill(); ctx.font = "bold 11px 'Inter', sans-serif"; ctx.fillStyle = col; ctx.textAlign = "center"; ctx.fillText(lbl + " " + mag.toFixed(1) + " V", p.x + (p.x - cx) * 0.18, p.y + (p.y - cy) * 0.18); };
  vec(p1, cl1, "L1", v1); vec(p2, cl2, "L2", v2); vec(p3, cl3, "L3", v3);
  const ns = neutralShift(v1, v2, v3), npx = cx + ns.re * scale, npy = cy - ns.im * scale;
  if (Math.hypot(npx - cx, npy - cy) > 0.5) { ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(npx, npy); ctx.strokeStyle = cN; ctx.lineWidth = 2; ctx.setLineDash([3, 2]); ctx.stroke(); ctx.setLineDash([]); ctx.beginPath(); ctx.arc(npx, npy, 5, 0, 2 * Math.PI); ctx.fillStyle = cN; ctx.fill(); }
  ctx.beginPath(); ctx.arc(cx, cy, 5, 0, 2 * Math.PI); ctx.fillStyle = cT; ctx.fill();
  ctx.font = "10px 'JetBrains Mono', monospace"; ctx.fillStyle = cT; ctx.textAlign = "center";
  ctx.fillText("mean " + ((v1 + v2 + v3) / 3).toFixed(1) + " V", cx, cy - 10);
  ctx.font = "8px 'JetBrains Mono', monospace"; ctx.fillStyle = cD; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.fillText("\u2212" + BASE + " V base", 6, H - 4); ctx.textBaseline = "alphabetic";
}

/**
 * Update all wye DOM stat elements and redraw both canvases.
 *
 * v1/v2/v3 are V_LN values from the driver (grid_l1/2/3_v).
 * ll12/ll13/ll23 are directly measured V_LL from the Growatt meter registers
 * (31106-31108, R=L1, S=L2, T=L3): RS=L1-L2, ST=L2-L3, TR=L1-L3.
 * Using measured LL values avoids round-trip error from V_LN derivation.
 *
 * @param {number} v1   - L1 phase-to-neutral RMS (V).
 * @param {number} v2   - L2 phase-to-neutral RMS (V).
 * @param {number} v3   - L3 phase-to-neutral RMS (V).
 * @param {number} llRS - Measured V_RS = L1–L2 line voltage (V).
 * @param {number} llST - Measured V_ST = L2–L3 line voltage (V).
 * @param {number} llTR - Measured V_TR = L1–L3 line voltage (V).
 */
function updateWyeDiagram(v1, v2, v3, llRS, llST, llTR) {
  if (!v1 || !v2 || !v3) return;
  const IEC_NOM = 230, IEC_LL = 400;
  const set = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
  set("wye-v-l1", v1.toFixed(1)); set("wye-v-l2", v2.toFixed(1)); set("wye-v-l3", v3.toFixed(1));
  const setIdeal = (id, v, nom) => {
    const e = document.getElementById(id); if (!e) return;
    const d = v - nom, p = (d / nom) * 100;
    e.textContent = (d >= 0 ? "+" : "") + d.toFixed(1) + " V vs IEC (" + (p >= 0 ? "+" : "") + p.toFixed(1) + "%)";
    e.className = "wt-ideal " + (d >= 0 ? "wt-ideal--pos" : "wt-ideal--neg");
  };
  setIdeal("wye-ideal-l1", v1, IEC_NOM); setIdeal("wye-ideal-l2", v2, IEC_NOM); setIdeal("wye-ideal-l3", v3, IEC_NOM);
  // Use measured V_LL directly; RS=L1-L2, ST=L2-L3, TR=L1-L3.
  const ll12 = llRS || lineVoltage(v1, v2);
  const ll23 = llST || lineVoltage(v2, v3);
  const ll13 = llTR || lineVoltage(v1, v3);
  set("wye-diff-l12", ll12.toFixed(1)); set("wye-diff-l13", ll13.toFixed(1)); set("wye-diff-l23", ll23.toFixed(1));
  setIdeal("wye-ideal-l12", ll12, IEC_LL); setIdeal("wye-ideal-l13", ll13, IEC_LL); setIdeal("wye-ideal-l23", ll23, IEC_LL);
  const ns = neutralShift(v1, v2, v3), nMag = Math.hypot(ns.re, ns.im);
  set("wye-neutral-mag", nMag.toFixed(2));
  // Compass bearing: clockwise from north (top), always 0–360°.
  // Math.atan2 returns CCW from east; bearing = (90 − math_deg + 360) % 360.
  const mathDeg = Math.atan2(ns.im, ns.re) * 180 / Math.PI;
  const bearing = ((90 - mathDeg) % 360 + 360) % 360;
  set("wye-neutral-ang", bearing.toFixed(1));
  set("wye-imbalance",   voltageImbalance(v1, v2, v3).toFixed(2));
  drawWyeDiagram(v1, v2, v3, ll12, ll13, ll23);
  drawNeutralMini(ns.re, ns.im, nMag);
}

/**
 * Draw the mini neutral-offset polar diagram.
 *
 * The outer ring auto-scales to the smallest 5 V multiple >= 2 * magnitude
 * (floor 5 V). Phase direction labels placed just outside the ring.
 *
 * @param {number} re  - Real part of neutral shift (V).
 * @param {number} im  - Imaginary part of neutral shift (V).
 * @param {number} mag - Magnitude of neutral shift (V).
 */
function drawNeutralMini(re, im, mag) {
  if (!neutralCtx || !neutralCanvas) return;
  const dpr = window.devicePixelRatio || 1;
  const W = neutralCanvas.width / dpr, H = neutralCanvas.height / dpr;
  const cx = W / 2, cy = H / 2;
  const cN = WYE_CSS.neutral || "#f472b6", cG = WYE_CSS.grid || "rgba(255,255,255,0.06)";
  const cT = WYE_CSS.text || "#9ca3af", cD = WYE_CSS.dim || "#4b5563";
  const cl1 = WYE_CSS.cl1 || "#60a5fa", cl2 = WYE_CSS.cl2 || "#34d399", cl3 = WYE_CSS.cl3 || "#f59e0b";
  const ctx = neutralCtx;
  ctx.clearRect(0, 0, W, H);
  const maxRef = Math.max(5, Math.ceil(Math.max(mag * 2, 1) / 5) * 5);
  const R = Math.min(W, H) * 0.36, scale = R / maxRef;
  [0.25, 0.5, 0.75, 1].forEach(f => { ctx.beginPath(); ctx.arc(cx, cy, R * f, 0, 2 * Math.PI); ctx.strokeStyle = cG; ctx.lineWidth = f === 1 ? 1 : 0.75; ctx.setLineDash([]); ctx.stroke(); });
  for (let a = 0; a < 360; a += 30) { const r = a * Math.PI / 180; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + R * Math.cos(r), cy - R * Math.sin(r)); ctx.strokeStyle = cG; ctx.lineWidth = 0.5; ctx.stroke(); }
  ctx.font = "8px 'JetBrains Mono', monospace"; ctx.fillStyle = cD; ctx.textAlign = "left"; ctx.textBaseline = "middle";
  ctx.fillText(maxRef + " V", cx + R * Math.cos(Math.PI / 4) + 3, cy - R * Math.sin(Math.PI / 4)); ctx.textBaseline = "alphabetic";
  [{ l: "L1", a: 90, c: cl1 }, { l: "L2", a: -30, c: cl2 }, { l: "L3", a: 210, c: cl3 }].forEach(({ l, a, c }) => {
    const r = a * Math.PI / 180; ctx.font = "bold 8px 'Inter', sans-serif"; ctx.fillStyle = c; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(l, cx + (R + 11) * Math.cos(r), cy - (R + 11) * Math.sin(r));
  }); ctx.textBaseline = "alphabetic";
  ctx.beginPath(); ctx.arc(cx, cy, 3, 0, 2 * Math.PI); ctx.fillStyle = cT; ctx.fill();
  const vx = cx + re * scale, vy = cy - im * scale;
  if (Math.hypot(vx - cx, vy - cy) > 1.5) {
    // Shaft: offset point → origin (arrowhead points at the balanced centre).
    ctx.beginPath(); ctx.moveTo(vx, vy); ctx.lineTo(cx, cy);
    ctx.strokeStyle = cN; ctx.lineWidth = 2; ctx.setLineDash([]); ctx.stroke();

    // Arrowhead at (cx, cy) — angle from offset point toward centre.
    const a2 = Math.atan2(cy - vy, cx - vx), hs = 6;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx - hs * Math.cos(a2 - 0.4), cy - hs * Math.sin(a2 - 0.4));
    ctx.lineTo(cx - hs * Math.cos(a2 + 0.4), cy - hs * Math.sin(a2 + 0.4));
    ctx.closePath(); ctx.fillStyle = cN; ctx.fill();

    // Red dot at the offset point — "you are here".
    ctx.beginPath(); ctx.arc(vx, vy, 5, 0, 2 * Math.PI);
    ctx.fillStyle = "#ef4444"; ctx.fill();

    // Magnitude label nudged outward from the offset point (away from centre).
    const lx = vx + (vx - cx) * 0.35, ly = vy + (vy - cy) * 0.35;
    ctx.font = "bold 9px 'JetBrains Mono', monospace"; ctx.fillStyle = cN;
    ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    ctx.fillText(mag.toFixed(2) + " V", lx, ly - 4); ctx.textBaseline = "alphabetic";
  } else {
    ctx.font = "9px 'JetBrains Mono', monospace"; ctx.fillStyle = cT; ctx.textAlign = "center"; ctx.fillText("balanced", cx, cy + 18);
  }
}

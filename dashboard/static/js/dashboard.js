
"use strict";

/** @type {object} Current chart colour palette; refreshed on theme change. */
let COLORS = chartPalette();

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


function recolorCharts() {
  COLORS = chartPalette();
  const s    = getComputedStyle(document.documentElement);
  const grid = s.getPropertyValue("--chart-grid").trim() || "rgba(0,0,0,0.06)";
  const tick = s.getPropertyValue("--text-muted").trim() || "#6b7490";
  // Delegate wye colour token refresh to the wye module.
  refreshWyeCSS();
  Chart.defaults.color = tick;
  Object.values(charts).forEach(chart => {
      Object.values(chart.options.scales).forEach(axis => {
          if (axis.ticks) axis.ticks.color = tick;
          if (axis.grid)  axis.grid.color  = grid;
      });
      chart.update("none");
  });
}

/**
 * Handle tab-switch side-effects that are growatt-specific:
 *   - Persist the active tab to localStorage.
 *   - Resize wye canvases when the grid tab becomes visible
 *     (getBoundingClientRect returns zero in hidden tabs).
 */
document.addEventListener("dashboard:tabswitch", ({ detail }) => {
    localStorage.setItem("growatt-tab", detail.id);
    if (detail.id === "grid") {
        resizeWyeCanvas();
        resizeNeutralCanvas();
    }
});



document.addEventListener("DOMContentLoaded", async () => {
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
    initFlowScale();
    initSparklineModal();

    
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
        localStorage.setItem('growatt-range', hours);
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
    charts.grid.data.datasets[0].borderWidth = 2;
    
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
    charts.eps.data.datasets[0].borderWidth = 2;
    for(let i=1; i<=3; i++) {
        charts.eps.data.datasets[i].stack = 'phases';
        charts.eps.data.datasets[i].fill = true;
    }
    
    charts.freq = createChart('chart-freq', [{ label: 'Grid Freq', color: COLORS.pv1 }], false);
    // Fixed Y range: nominal 50 Hz ± 0.25 Hz (EN 50160 nominal tolerance).
    charts.freq.options.scales.y.min = 49.75;
    charts.freq.options.scales.y.max = 50.25;
    charts.freq.options.scales.y.ticks = {
        callback: (v) => v.toFixed(2),
        maxTicksLimit: 6,
    };
    charts.invTemp = createChart('chart-inv-temp', [{ label: 'Inverter Temp', color: COLORS.l1 }], false);
    charts.bstTemp = createChart('chart-bst-temp', [{ label: 'Boost Temp', color: COLORS.l2 }], false);

    const tickClock = () => {
        const el = document.getElementById("header-time");
        if(el) el.innerText = new Date().toLocaleTimeString();
    };
    tickClock();
    setInterval(tickClock, 1000);

    // Restore history range from localStorage; fall back to the select's
    // default value (24 h) if nothing has been saved yet.
    const rangeEl = document.getElementById("history-range");
    const savedRange = localStorage.getItem('growatt-range');
    if (savedRange && rangeEl) {
        rangeEl.value = savedRange;   // update the <select> display
        currentHours = Number.parseInt(savedRange, 10);
    }

    // Restore the last active tab; fall back to 'overview'.
    const savedTab = localStorage.getItem('growatt-tab') || 'overview';
    switchTab(savedTab);

    // Await history so lastStatus is correctly seeded before SSE connects.
    // Connecting SSE before history loads risks lastStatus being set by the
    // first live reading, causing the first real status-change to be missed.
    await loadHistory(currentHours);
    connectSSE();
    recolorCharts();
});

// currentHours is initialised from localStorage in DOMContentLoaded;
// the literal 24 here acts as a safe default before that runs.
let currentHours = 24;



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


function connectSSE() {
    const es = new EventSource("/stream");
    es.addEventListener("reading", (e) => {
        const d = JSON.parse(e.data);
        const ts = d.ts;

        // ── Status indicator ─────────────────────────────────────────────────
        // Update unconditionally and first, before any chart rendering that
        // could throw and prevent this from running.
        const _statusStr = STATUS_MAP[d.status_code] || "UNKNOWN";
        const _sl  = document.getElementById("status-label");
        const _dot = document.getElementById("status-dot");
        if (_sl)  _sl.innerText = _statusStr;
        if (_dot) {
            _dot.classList.remove("inv-normal", "inv-bypass", "inv-fault", "inv-other");
            _dot.classList.add(inverterDotClass(_statusStr));
        }

        updateDOM("sum-pv", d.pv_total_w.toFixed(0));
        updateDOM("sum-pv-val", d.pv_total_w.toFixed(0)); // Header of PV tab
        updateDOM("sum-pv-stat", _statusStr);
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
                    // Render immediately so the marker is visible before the
                    // bulk chart.update() at the end of the SSE handler.
                    chart.update("none");
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
        
        try {
            Object.values(charts).forEach(c => { if(c) c.update('none'); });
        } catch (err) {
            console.warn("chart.update error:", err);
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


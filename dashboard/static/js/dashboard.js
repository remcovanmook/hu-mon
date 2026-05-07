
"use strict";

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
            legend: { display: true },
            tooltip: { padding: 10 }
        }
    };
}

function switchTab(id) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('tab-btn--active'));
    document.querySelectorAll('.tab-panel').forEach(c => c.hidden = true);
    document.getElementById(`tab-btn-${id}`).classList.add('tab-btn--active');
    document.getElementById(`tab-${id}`).hidden = false;
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tab-btn-overview").addEventListener("click", () => switchTab("overview"));
    document.getElementById("tab-btn-pv").addEventListener("click", () => switchTab("pv"));
    document.getElementById("tab-btn-grid").addEventListener("click", () => switchTab("grid"));
    document.getElementById("tab-btn-battery").addEventListener("click", () => switchTab("battery"));

    const toggleBtn = document.getElementById("theme-toggle");
    if (toggleBtn) {
        toggleBtn.addEventListener("click", cycleTheme);
        const savedTheme = document.documentElement.dataset.theme || "light";
        toggleBtn.textContent = THEME_LABELS[savedTheme] ?? savedTheme;
    }
    
    // Auto-create DOM cards for phase arrays
    const createGroup = (id, label, unit, count, l_prefix) => {
        const el = document.getElementById(id);
        if(!el) return;
        for(let i=1; i<=count; i++) {
            el.innerHTML += `<article class="card card--phase"><div class="card-label">${l_prefix} ${i} ${label}</div><div class="phase-value-group"><div class="card-value" id="${l_prefix.toLowerCase()}${i}-${unit.toLowerCase()}">—</div><div class="card-unit">${unit}</div></div></article>`;
        }
    };
    createGroup('pv-cards-v', 'Voltage', 'V', 4, 'PV');
    createGroup('pv-cards-a', 'Current', 'A', 4, 'PV');
    createGroup('pv-cards-w', 'Power', 'W', 4, 'PV');
    createGroup('grid-cards-v', 'Voltage', 'V', 3, 'Grid');
    createGroup('grid-cards-a', 'Current', 'A', 3, 'Grid');
    createGroup('grid-cards-w', 'Power', 'W', 3, 'Grid');

    charts.overview = createChart('chart-power', [
        { label: 'PV (W)', color: COLORS.pv1 },
        { label: 'Grid Net (W)', color: COLORS.net },
        { label: 'Load (W)', color: COLORS.load }
    ]);
    charts.pv = createChart('chart-pv', [
        { label: 'S1 (W)', color: COLORS.pv1 }, { label: 'S2 (W)', color: COLORS.pv2 },
        { label: 'S3 (W)', color: COLORS.pv3 }, { label: 'S4 (W)', color: COLORS.pv4 }
    ]);
    charts.grid = createChart('chart-grid', [
        { label: 'L1 (W)', color: COLORS.l1 }, { label: 'L2 (W)', color: COLORS.l2 }, { label: 'L3 (W)', color: COLORS.l3 }
    ]);
    charts.battery = createChart('chart-battery', [
        { label: 'Battery (W)', color: COLORS.returned }
    ]);

    const tickClock = () => {
        const el = document.getElementById("header-time");
        if(el) el.innerText = new Date().toLocaleTimeString();
    };
    tickClock();
    setInterval(tickClock, 1000);

    loadHistory();
    connectSSE();
    recolorCharts();
});

function createChart(id, series) {
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
            legend: { 
                display: true, 
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
                grid: { display: false },
                ticks: { maxTicksLimit: 6 }
            },
            y: { 
                grid: { color: "rgba(100, 100, 100, 0.1)", borderDash: [5, 5] },
                beginAtZero: true
            }
        }
    };

    return new Chart(ctx, { type: 'line', data: { labels: [], datasets: datasets }, options: opts });
}

function updateDOM(id, val) {
    const el = document.getElementById(id);
    if(el && el.innerText !== String(val)) el.innerText = val;
}

async function loadHistory() {
    try {
        const res = await fetch(`/api/history?hours=24`);
        if(!res.ok) return;
        const data = await res.json();
        if(data.length === 0) return;
        
        const labels = [];
        const ds = { overview: [[],[],[]], pv: [[],[],[],[]], grid: [[],[],[]], battery: [[]] };
        
        data.forEach(d => {
            labels.push(d.ts);
            ds.overview[0].push(d.pv_total_w_mean); ds.overview[1].push(d.meter_total_w_mean); ds.overview[2].push(d.load_p_mean);
            ds.pv[0].push(d.pv1_w_mean); ds.pv[1].push(d.pv2_w_mean); ds.pv[2].push(d.pv3_w_mean); ds.pv[3].push(d.pv4_w_mean);
            ds.grid[0].push(d.grid_l1_v_mean * d.grid_l1_a_mean); ds.grid[1].push(d.grid_l2_v_mean * d.grid_l2_a_mean); ds.grid[2].push(d.grid_l3_v_mean * d.grid_l3_a_mean);
            ds.battery[0].push(d.bat_p_mean);
        });
        
        Object.keys(charts).forEach(k => {
            if(!charts[k]) return;
            charts[k].data.labels = [...labels];
            charts[k].data.datasets.forEach((c, i) => c.data = [...ds[k][i]]);
            charts[k].update('none');
        });
    } catch(e) {}
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
        updateDOM("sum-pv-stat", STATUS_MAP[d.status_code] || "UNKNOWN");
        updateDOM("sum-pv-today", d.pv_today_kwh.toFixed(1));
        updateDOM("sum-pv-total", d.pv_total_kwh.toFixed(0));

        updateDOM("sum-grid", Math.abs(d.meter_total_w).toFixed(0));
        updateDOM("sum-grid-stat", d.meter_total_w >= 0 ? "Exporting" : "Importing");
        updateDOM("sum-grid-today", d.meter_total_w >= 0 ? d.grid_export_today_kwh.toFixed(1) : d.grid_import_today_kwh.toFixed(1));
        // Hardcode "total ever" until we add it, or just show Export for now
        updateDOM("sum-grid-total", d.grid_export_today_kwh.toFixed(0));

        updateDOM("sum-bat", d.bat_soc.toFixed(1));
        
        if (d.bat_nominal_kwh > 0) {
            const bat_kwh = (d.bat_soc / 100.0) * d.bat_nominal_kwh;
            updateDOM("sum-bat-kwh", bat_kwh.toFixed(1));
            const autonomy = d.load_p > 0 ? (bat_kwh * 1000 / d.load_p).toFixed(1) : "—";
            updateDOM("sum-bat-autonomy", autonomy);
        } else {
            updateDOM("sum-bat-kwh", "—");
            updateDOM("sum-bat-autonomy", "—");
        }
        
        updateDOM("sum-load", d.load_p.toFixed(0));
        updateDOM("sum-load-today", d.load_today_kwh.toFixed(1));
        
        // Explicitly ignoring L1/L2/L3 house load splits since we cannot derive them purely from the Modbus data without assumptions
        updateDOM("overview-net-val", d.meter_total_w.toFixed(0));


        
        
        // Update DOM metrics
        updateDOM("meta-model", d.inverter_model);
        updateDOM("meta-serial", d.inverter_serial);
        updateDOM("meta-fw", d.inverter_firmware);
        updateDOM("meta-e-today", d.pv_today_kwh.toFixed(1) + " kWh");
        updateDOM("meta-e-total", d.pv_total_kwh.toFixed(1) + " kWh");

        let statusStr = STATUS_MAP[d.status_code] || "UNKNOWN";
        updateDOM("meta-status", statusStr);
        
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
            updateDOM(`grid${i}-v`, d[`grid_l${i}_v`].toFixed(1));
            updateDOM(`grid${i}-a`, d[`grid_l${i}_a`].toFixed(1));
        }
        updateDOM(`grid1-w`, g1w.toFixed(0));
        updateDOM(`grid2-w`, g2w.toFixed(0));
        updateDOM(`grid3-w`, g3w.toFixed(0));

        updateDOM("bat-v", d.bat_v.toFixed(1));
        updateDOM("bat-a", d.bat_i.toFixed(1));
        updateDOM("bat-w", d.bat_p.toFixed(0));
        updateDOM("bat-soc", d.bat_soc.toFixed(1));

        pushChart(charts.overview, ts, [d.pv_total_w, d.meter_total_w, d.load_p]);
        pushChart(charts.pv, ts, [d.pv1_w, d.pv2_w, d.pv3_w, d.pv4_w]);
        pushChart(charts.grid, ts, [g1w, g2w, g3w]);
        pushChart(charts.battery, ts, [d.bat_p]);
    });
}

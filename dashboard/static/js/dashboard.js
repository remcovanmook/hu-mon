
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

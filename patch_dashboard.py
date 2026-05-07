import re

with open('dashboard/static/js/dashboard.js', 'r') as f:
    js = f.read()

# 1. Sparkline callout bubbles and vertical annotation center
js = js.replace(
'''function buildStatusAnnotation(tsMs, statusStr) {
  return {
    type: "line", scaleID: "x", value: tsMs,
    borderColor: "rgba(139, 92, 246, 0.5)", borderWidth: 1, borderDash: [4, 4],
    label: {
      display: true, content: statusStr, position: "start",
      backgroundColor: "rgba(139, 92, 246, 0.8)", color: "#fff",
      font: { size: 9 }, padding: { x: 4, y: 2 }, rotation: -90, yAdjust: 10
    }
  };
}''',
'''function buildStatusAnnotation(tsMs, statusStr) {
  return {
    type: "line", scaleID: "x", value: tsMs,
    borderColor: "rgba(139, 92, 246, 0.5)", borderWidth: 1, borderDash: [4, 4],
    label: {
      display: true, content: statusStr, position: "center",
      backgroundColor: "rgba(139, 92, 246, 0.8)", color: "#fff",
      font: { size: 9, weight: "600" }, padding: { x: 4, y: 2 }, borderRadius: 4, rotation: -90
    }
  };
}'''
)

js = js.replace(
'''function updateSparklineAnnotations(chart, min, max, color) {
  if(!chart) return;
  const cStr = typeof color === 'string' && color.startsWith('#') ? color + '80' : color;
  chart.options.plugins.annotation.annotations = Object.assign({}, chart.options.plugins.annotation.annotations, {
    minLine: {
      type: 'line', yMin: min, yMax: min, borderColor: cStr, borderWidth: 1, borderDash: [2, 2],
      label: { display: true, content: min.toFixed(1), position: 'end', backgroundColor: 'transparent', color: color, font: {size: 9} }
    },
    maxLine: {
      type: 'line', yMin: max, yMax: max, borderColor: cStr, borderWidth: 1, borderDash: [2, 2],
      label: { display: true, content: max.toFixed(1), position: 'start', backgroundColor: 'transparent', color: color, font: {size: 9} }
    }
  });
}''',
'''function updateSparklineAnnotations(chart, min, max, color) {
  if(!chart) return;
  const cStr = typeof color === 'string' && color.startsWith('#') ? color + '80' : color;
  const bg = typeof color === 'string' && color.startsWith('#') ? color + 'd0' : 'rgba(100,100,100,0.8)';
  chart.options.plugins.annotation.annotations = Object.assign({}, chart.options.plugins.annotation.annotations, {
    minLine: {
      type: 'line', yMin: min, yMax: min, borderColor: cStr, borderWidth: 1, borderDash: [2, 2],
      label: { display: true, content: min.toFixed(1), position: 'end', backgroundColor: bg, color: '#fff', font: {size: 9, weight: '600'}, padding: {x: 4, y: 2}, borderRadius: 4 }
    },
    maxLine: {
      type: 'line', yMin: max, yMax: max, borderColor: cStr, borderWidth: 1, borderDash: [2, 2],
      label: { display: true, content: max.toFixed(1), position: 'start', backgroundColor: bg, color: '#fff', font: {size: 9, weight: '600'}, padding: {x: 4, y: 2}, borderRadius: 4 }
    }
  });
}'''
)

# 2. Add inline styles for phase-badge and card-value
js = js.replace(
'''            html += `
            <article class="card card--phase card--with-chart">
              <div class="phase-row">
                <div class="phase-badge">${l_prefix}${i}</div>
                <div class="phase-value-group">
                  <div class="card-value" id="${valueId}">—</div>
                  <div class="card-unit">${unit}</div>
                </div>
              </div>''',
'''            const color = colorMap[l_prefix][i-1] || COLORS.pv1;
            html += `
            <article class="card card--phase card--with-chart">
              <div class="phase-row">
                <div class="phase-badge" style="background: ${color}; color: #fff;">${l_prefix}${i}</div>
                <div class="phase-value-group">
                  <div class="card-value" id="${valueId}" style="color: ${color}">—</div>
                  <div class="card-unit">${unit}</div>
                </div>
              </div>'''
)

# Remove the duplicated const color = ... later in createGroup since we moved it up
js = js.replace(
'''            const color = colorMap[l_prefix][i-1] || COLORS.pv1;
            
            charts[chartId] = createChart(chartId, [{ label: `${l_prefix}${i} ${label}`, color: color }], false);''',
'''            const color = colorMap[l_prefix][i-1] || COLORS.pv1;
            charts[chartId] = createChart(chartId, [{ label: `${l_prefix}${i} ${label}`, color: color }], false);'''
)


# 3. Clean up the PV Power legend
js = js.replace(
'''    charts.pv = createChart('chart-pv', [
        { label: 'Total PV (W)', color: COLORS.delivered, borderWidth: 2 },
        { label: 'S1 (W)', color: COLORS.pv1 }, { label: 'S2 (W)', color: COLORS.pv2 },
        { label: 'S3 (W)', color: COLORS.pv3 }, { label: 'S4 (W)', color: COLORS.pv4 }
    ]);''',
'''    charts.pv = createChart('chart-pv', [
        { label: 'Total', color: COLORS.delivered, borderWidth: 2 },
        { label: 'PV1', color: COLORS.pv1 }, { label: 'PV2', color: COLORS.pv2 },
        { label: 'PV3', color: COLORS.pv3 }, { label: 'PV4', color: COLORS.pv4 }
    ]);'''
)


# 4. Round values for the main graphs in loadHistory
js = js.replace(
'''            ds.overview[0].push(d.pv_total_w_mean); ds.overview[1].push(-d.meter_total_w_mean); ds.overview[2].push(d.load_p_mean);
            ds.pv[0].push(d.pv_total_w_mean); ds.pv[1].push(d.pv1_w_mean); ds.pv[2].push(d.pv2_w_mean); ds.pv[3].push(d.pv3_w_mean); ds.pv[4].push(d.pv4_w_mean);
            ds.grid[0].push(-d.meter_total_w_mean); ds.grid[1].push(d.grid_l1_v_mean * d.grid_l1_a_mean); ds.grid[2].push(d.grid_l2_v_mean * d.grid_l2_a_mean); ds.grid[3].push(d.grid_l3_v_mean * d.grid_l3_a_mean);
            ds.battery[0].push(d.bat_p_mean);''',
'''            ds.overview[0].push(Math.round(d.pv_total_w_mean)); ds.overview[1].push(Math.round(-d.meter_total_w_mean)); ds.overview[2].push(Math.round(d.load_p_mean));
            ds.pv[0].push(Math.round(d.pv_total_w_mean)); ds.pv[1].push(Math.round(d.pv1_w_mean)); ds.pv[2].push(Math.round(d.pv2_w_mean)); ds.pv[3].push(Math.round(d.pv3_w_mean)); ds.pv[4].push(Math.round(d.pv4_w_mean));
            ds.grid[0].push(Math.round(-d.meter_total_w_mean)); ds.grid[1].push(Math.round(d.grid_l1_v_mean * d.grid_l1_a_mean)); ds.grid[2].push(Math.round(d.grid_l2_v_mean * d.grid_l2_a_mean)); ds.grid[3].push(Math.round(d.grid_l3_v_mean * d.grid_l3_a_mean));
            ds.battery[0].push(Math.round(d.bat_p_mean));'''
)

# 5. Round values for the main graphs in connectSSE
js = js.replace(
'''        pushChart(charts.overview, ts, [d.pv_total_w, -d.meter_total_w, d.load_p]);
        pushChart(charts.pv, ts, [d.pv_total_w, d.pv1_w, d.pv2_w, d.pv3_w, d.pv4_w]);
        pushChart(charts.grid, ts, [-d.meter_total_w, g1w, g2w, g3w]);
        pushChart(charts.battery, ts, [d.bat_p]);''',
'''        pushChart(charts.overview, ts, [Math.round(d.pv_total_w), Math.round(-d.meter_total_w), Math.round(d.load_p)]);
        pushChart(charts.pv, ts, [Math.round(d.pv_total_w), Math.round(d.pv1_w), Math.round(d.pv2_w), Math.round(d.pv3_w), Math.round(d.pv4_w)]);
        pushChart(charts.grid, ts, [Math.round(-d.meter_total_w), Math.round(g1w), Math.round(g2w), Math.round(g3w)]);
        pushChart(charts.battery, ts, [Math.round(d.bat_p)]);'''
)

with open('dashboard/static/js/dashboard.js', 'w') as f:
    f.write(js)

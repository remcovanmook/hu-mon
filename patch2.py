with open("dashboard/static/js/dashboard.js", "r") as f: js = f.read()

js = js.replace('''            for(let i=1; i<=3; i++) {
                let v = d[`grid_l${i}_v_mean`], c = d[`grid_l${i}_a_mean`];
                ds[`chart-v-grid${i}`][0].push(v);
                ds[`chart-c-grid${i}`][0].push(c);
                extremes.grid_v.min = Math.min(extremes.grid_v.min, v); extremes.grid_v.max = Math.max(extremes.grid_v.max, v);
                extremes.grid_c.min = Math.min(extremes.grid_c.min, c); extremes.grid_c.max = Math.max(extremes.grid_c.max, c);
            }''', '''            for(let i=1; i<=3; i++) {
                let v = d[`grid_l${i}_v_mean`], c = d[`grid_l${i}_a_mean`];
                ds[`chart-v-l${i}`][0].push(v);
                ds[`chart-c-l${i}`][0].push(c);
                extremes.grid_v.min = Math.min(extremes.grid_v.min, v); extremes.grid_v.max = Math.max(extremes.grid_v.max, v);
                extremes.grid_c.min = Math.min(extremes.grid_c.min, c); extremes.grid_c.max = Math.max(extremes.grid_c.max, c);
            }''')

js = js.replace('''        for(let i=1; i<=3; i++) {
            charts[`chart-v-grid${i}`].data.labels = labels; charts[`chart-v-grid${i}`].data.datasets[0].data = ds[`chart-v-grid${i}`][0]; charts[`chart-v-grid${i}`].update('none');
            charts[`chart-c-grid${i}`].data.labels = labels; charts[`chart-c-grid${i}`].data.datasets[0].data = ds[`chart-c-grid${i}`][0]; charts[`chart-c-grid${i}`].update('none');
        }''', '''        for(let i=1; i<=3; i++) {
            charts[`chart-v-l${i}`].data.labels = labels; charts[`chart-v-l${i}`].data.datasets[0].data = ds[`chart-v-l${i}`][0]; charts[`chart-v-l${i}`].update('none');
            charts[`chart-c-l${i}`].data.labels = labels; charts[`chart-c-l${i}`].data.datasets[0].data = ds[`chart-c-l${i}`][0]; charts[`chart-c-l${i}`].update('none');
        }''')

js = js.replace('''        const pvCCharts = []; for(let i=1; i<=4; i++) pvCCharts.push(charts[`chart-c-pv${i}`]);
        const gridVCharts = []; for(let i=1; i<=3; i++) gridVCharts.push(charts[`chart-v-grid${i}`]);
        const gridCCharts = []; for(let i=1; i<=3; i++) gridCCharts.push(charts[`chart-c-grid${i}`]);''', '''        const pvCCharts = []; for(let i=1; i<=4; i++) pvCCharts.push(charts[`chart-c-pv${i}`]);
        const gridVCharts = []; for(let i=1; i<=3; i++) gridVCharts.push(charts[`chart-v-l${i}`]);
        const gridCCharts = []; for(let i=1; i<=3; i++) gridCCharts.push(charts[`chart-c-l${i}`]);''')


js = js.replace('''        for(let i=1; i<=4; i++) {
            pushChart(charts[`chart-v-pv${i}`], ts, [d[`pv${i}_v`]]);
            pushChart(charts[`chart-c-pv${i}`], ts, [d[`pv${i}_a`]]);
        }
        for(let i=1; i<=3; i++) {
            pushChart(charts[`chart-v-grid${i}`], ts, [d[`grid_l${i}_v`]]);
            pushChart(charts[`chart-c-grid${i}`], ts, [d[`grid_l${i}_a`]]);
        }''', '''        for(let i=1; i<=4; i++) {
            pushChart(charts[`chart-v-pv${i}`], ts, [d[`pv${i}_v`]]);
            pushChart(charts[`chart-c-pv${i}`], ts, [d[`pv${i}_a`]]);
        }
        for(let i=1; i<=3; i++) {
            pushChart(charts[`chart-v-l${i}`], ts, [d[`grid_l${i}_v`]]);
            pushChart(charts[`chart-c-l${i}`], ts, [d[`grid_l${i}_a`]]);
        }''')

with open("dashboard/static/js/dashboard.js", "w") as f: f.write(js)

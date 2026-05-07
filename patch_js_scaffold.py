import re

js_path = "dashboard/static/js/dashboard.js"
with open(js_path, "r") as f:
    js = f.read()

# Replace the connectSSE updating logic to target the new scaffolding IDs
# I will use a simple regex or just string replace to inject the new DOM IDs.
new_update_logic = """
        updateDOM("sum-pv", d.pv_total_w.toFixed(0));
        updateDOM("sum-pv-stat", STATUS_MAP[d.status_code] || "UNKNOWN");
        // sum-pv-today and sum-pv-total await backend registers

        updateDOM("sum-grid", Math.abs(d.meter_total_w).toFixed(0));
        updateDOM("sum-grid-stat", d.meter_total_w >= 0 ? "Exporting" : "Importing");
        // sum-grid-today and sum-grid-total await backend registers

        updateDOM("sum-bat", d.bat_soc.toFixed(1));
        // sum-bat-kwh awaits capacity configuration
        // sum-bat-autonomy awaits load-based math
        
        updateDOM("sum-load", d.load_p.toFixed(0));
        
        // Per-phase estimation (assuming balanced until we pull smart meter registers)
        const est_l1 = (d.load_p / 3).toFixed(0);
        updateDOM("sum-load-l1", est_l1);
        updateDOM("sum-load-l2", est_l1);
        updateDOM("sum-load-l3", est_l1);
"""

# Find the block inside connectSSE where we used to update summary
js = re.sub(r'updateDOM\("sum-pv", d.pv_total_w.*updateDOM\("overview-net-val", d.meter_total_w.toFixed\(0\)\);', new_update_logic, js, flags=re.DOTALL)

with open(js_path, "w") as f:
    f.write(js)

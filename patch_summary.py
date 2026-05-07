import re

html_path = "dashboard/static/dashboard.html"
with open(html_path, "r") as f:
    html = f.read()

summary = """    <section class="section section--summary" aria-labelledby="summary-heading">
      <h1 id="summary-heading" class="sr-only">Summary</h1>
      <div class="summary-strip">
        <!-- 1. Current Production -->
        <div class="summary-item">
          <div class="summary-item-header">Current Production</div>
          <table class="summary-table">
            <thead><tr><th class="sr-only" scope="col">Value</th><th class="sr-only" scope="col">Status</th></tr></thead>
            <tbody>
              <tr>
                <td class="st-energy"><span id="sum-pv">—</span> W</td>
                <td class="st-delta"><span id="sum-pv-stat">WAITING</span></td>
              </tr>
              <tr>
                <td class="st-energy st-energy--sub">Today: <span id="sum-pv-today">—</span> kWh</td>
                <td class="st-delta" style="color: var(--text-muted)">Ever: <span id="sum-pv-total">—</span> kWh</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 2. Grid Power -->
        <div class="summary-item">
          <div class="summary-item-header">Grid Power</div>
          <table class="summary-table">
            <thead><tr><th class="sr-only" scope="col">Value</th><th class="sr-only" scope="col">Status</th></tr></thead>
            <tbody>
              <tr>
                <td class="st-energy"><span id="sum-grid">—</span> W</td>
                <td class="st-delta"><span id="sum-grid-stat">Importing</span></td>
              </tr>
              <tr>
                <td class="st-energy st-energy--sub">Today: <span id="sum-grid-today">—</span> kWh</td>
                <td class="st-delta" style="color: var(--text-muted)">Ever: <span id="sum-grid-total">—</span> kWh</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 3. Battery -->
        <div class="summary-item">
          <div class="summary-item-header">Battery</div>
          <table class="summary-table">
            <thead><tr><th class="sr-only" scope="col">Value</th><th class="sr-only" scope="col">Status</th></tr></thead>
            <tbody>
              <tr>
                <td class="st-energy"><span id="sum-bat">—</span> %</td>
                <td class="st-delta"><span id="sum-bat-kwh">—</span> kWh</td>
              </tr>
              <tr>
                <td class="st-energy st-energy--sub" colspan="2"><span id="sum-bat-autonomy">—</span> hrs autonomy @ current load</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 4. House Consumption -->
        <div class="summary-item">
          <div class="summary-item-header">House Consumption</div>
          <table class="summary-table">
            <thead><tr><th class="sr-only" scope="col">Value</th><th class="sr-only" scope="col">Phases</th></tr></thead>
            <tbody>
              <tr>
                <td class="st-energy"><span id="sum-load">—</span> W</td>
                <td class="st-delta"></td>
              </tr>
              <tr>
                <td class="st-energy st-energy--sub" colspan="2">
                  L1: <span id="sum-load-l1">—</span> W &nbsp; 
                  L2: <span id="sum-load-l2">—</span> W &nbsp; 
                  L3: <span id="sum-load-l3">—</span> W
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>"""

# Using regex to replace the entire section
new_html = re.sub(r'<section class="section section--summary".*?</section>', summary, html, flags=re.DOTALL)
with open(html_path, "w") as f:
    f.write(new_html)

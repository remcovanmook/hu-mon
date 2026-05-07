import re

with open("dashboard/static/dashboard.html", "r") as f:
    html = f.read()

# 1. Title & Header
html = html.replace('Hegg · Energy Monitor', 'Growatt Dashboard')
html = html.replace('<span class="logo-text">Hegg</span>\n        <span class="logo-sub">Energy Monitor</span>', '<span class="logo-text">Growatt</span>\n        <span class="logo-sub">Dashboard</span>')

# 2. Summary Strip
summary = """      <div class="summary-strip">
        <div class="summary-item">
          <div class="summary-item-header">Production</div>
          <table class="summary-table">
            <tbody>
              <tr><td class="st-energy"><span id="sum-pv">—</span> W</td><td class="st-delta"><span id="sum-pv-stat">WAITING</span></td></tr>
              <tr><td class="st-energy st-energy--sub">Energy Today</td><td class="st-delta"><span id="sum-pv-today">—</span> kWh</td></tr>
            </tbody>
          </table>
        </div>
        <div class="summary-item">
          <div class="summary-item-header">Grid</div>
          <table class="summary-table">
            <tbody>
              <tr><td class="st-energy"><span id="sum-grid">—</span> W</td><td class="st-delta"><span id="sum-grid-stat">Importing</span></td></tr>
              <tr><td class="st-energy st-energy--sub">Net Today</td><td class="st-delta"><span id="sum-grid-today">—</span> kWh</td></tr>
            </tbody>
          </table>
        </div>
        <div class="summary-item">
          <div class="summary-item-header">Battery</div>
          <table class="summary-table">
            <tbody>
              <tr><td class="st-energy"><span id="sum-bat">—</span> %</td><td class="st-delta"><span id="sum-bat-stat">Idle</span></td></tr>
              <tr><td class="st-energy st-energy--sub">Power</td><td class="st-delta"><span id="sum-bat-w">—</span> W</td></tr>
            </tbody>
          </table>
        </div>
        <div class="summary-item">
          <div class="summary-item-header">House Load</div>
          <table class="summary-table">
            <tbody>
              <tr><td class="st-energy"><span id="sum-load">—</span> W</td><td class="st-delta"></td></tr>
              <tr><td class="st-energy st-energy--sub">Usage Today</td><td class="st-delta"><span id="sum-load-today">—</span> kWh</td></tr>
            </tbody>
          </table>
        </div>
      </div>"""
html = re.sub(r'<div class="summary-strip">.*?</div>\s*</section>', summary + '\n    </section>', html, flags=re.DOTALL)

# 3. Tab Bar
tabs = """    <nav class="tab-bar" role="tablist" aria-label="Dashboard view">
      <button class="tab-btn tab-btn--active" id="tab-btn-overview" role="tab" aria-selected="true" aria-controls="tab-overview">Overview</button>
      <button class="tab-btn" id="tab-btn-pv" role="tab" aria-selected="false" aria-controls="tab-pv">PV Power</button>
      <button class="tab-btn" id="tab-btn-grid" role="tab" aria-selected="false" aria-controls="tab-grid">Grid Power</button>
      <button class="tab-btn" id="tab-btn-battery" role="tab" aria-selected="false" aria-controls="tab-battery">Battery Power</button>
    </nav>"""
html = re.sub(r'<nav class="tab-bar".*?</nav>', tabs, html, flags=re.DOTALL)

# 4. Tab Panels
# Replace everything from `<section class="tab-panel` to `</main>`
panels = """    <!-- TAB OVERVIEW -->
    <section class="tab-panel tab-panel--active" id="tab-overview" role="tabpanel" aria-labelledby="tab-btn-overview">
      <div class="dashboard-grid">
        <div class="chart-card" id="power-display">
          <div class="power-card-header">
            <div class="power-card-headline">
              <h2>System Overview</h2>
              <div class="power-card-values">
                <div class="phase-value-group"><div class="card-value" id="overview-net-val">—</div><div class="card-unit">W</div></div>
              </div>
            </div>
          </div>
          <div class="chart-wrapper"><canvas id="chart-power"></canvas></div>
        </div>
      </div>
    </section>

    <!-- TAB PV -->
    <section class="tab-panel" id="tab-pv" role="tabpanel" aria-labelledby="tab-btn-pv" hidden>
      <div class="dashboard-grid">
        <div class="chart-card">
          <div class="power-card-header"><h2>PV Generation</h2></div>
          <div class="chart-wrapper"><canvas id="chart-pv"></canvas></div>
        </div>
        <div class="cards-row cards-row--four" id="pv-cards-v"></div>
        <div class="cards-row cards-row--four" id="pv-cards-a"></div>
        <div class="cards-row cards-row--four" id="pv-cards-w"></div>
      </div>
    </section>

    <!-- TAB GRID -->
    <section class="tab-panel" id="tab-grid" role="tabpanel" aria-labelledby="tab-btn-grid" hidden>
      <div class="dashboard-grid">
        <div class="chart-card">
          <div class="power-card-header"><h2>Grid Power</h2></div>
          <div class="chart-wrapper"><canvas id="chart-grid"></canvas></div>
        </div>
        <div class="cards-row cards-row--three" id="grid-cards-v"></div>
        <div class="cards-row cards-row--three" id="grid-cards-a"></div>
        <div class="cards-row cards-row--three" id="grid-cards-w"></div>
      </div>
    </section>

    <!-- TAB BATTERY -->
    <section class="tab-panel" id="tab-battery" role="tabpanel" aria-labelledby="tab-btn-battery" hidden>
      <div class="dashboard-grid">
        <div class="chart-card">
          <div class="power-card-header"><h2>Battery Power</h2></div>
          <div class="chart-wrapper"><canvas id="chart-battery"></canvas></div>
        </div>
        <div class="cards-row cards-row--four">
            <article class="card"><div class="card-label">Battery Voltage</div><div class="phase-value-group"><div class="card-value" id="bat-v">—</div><div class="card-unit">V</div></div></article>
            <article class="card"><div class="card-label">Battery Current</div><div class="phase-value-group"><div class="card-value" id="bat-a">—</div><div class="card-unit">A</div></div></article>
            <article class="card"><div class="card-label">Battery Power</div><div class="phase-value-group"><div class="card-value" id="bat-w">—</div><div class="card-unit">W</div></div></article>
            <article class="card"><div class="card-label">Battery SOC</div><div class="phase-value-group"><div class="card-value" id="bat-soc">—</div><div class="card-unit">%</div></div></article>
        </div>
      </div>
    </section>
  </main>"""
html = re.sub(r'<section class="tab-panel.*?</main>', panels, html, flags=re.DOTALL)

with open("dashboard/static/dashboard.html", "w") as f:
    f.write(html)

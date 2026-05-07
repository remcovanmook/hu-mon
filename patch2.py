import re

# 1. FIX HTML SUMMARY STRIP
with open('dashboard/static/dashboard.html', 'r') as f:
    html = f.read()

summary_html = """    <section class="summary-strip">
      <!-- 1 -->
      <div class="summary-item">
        <div class="summary-item-header">Current Production</div>
        <table class="summary-table">
          <tbody>
            <tr><td class="st-energy"><span id="sum-pv">—</span> W</td></tr>
            <tr><td class="st-label" id="sum-pv-hint" style="color:var(--text-muted);font-size:0.8rem">WAITING</td></tr>
          </tbody>
        </table>
      </div>
      <!-- 2 -->
      <div class="summary-item">
        <div class="summary-item-header">Grid Power</div>
        <table class="summary-table">
          <tbody>
            <tr><td class="st-energy"><span id="sum-grid">—</span> W</td></tr>
            <tr><td class="st-label" id="sum-grid-hint" style="color:var(--text-muted);font-size:0.8rem">Importing</td></tr>
          </tbody>
        </table>
      </div>
      <!-- 3 -->
      <div class="summary-item">
        <div class="summary-item-header">Battery SOC</div>
        <table class="summary-table">
          <tbody>
            <tr><td class="st-energy"><span id="sum-bat">—</span> %</td></tr>
            <tr><td class="st-label" id="sum-bat-hint" style="color:var(--text-muted);font-size:0.8rem">Idle</td></tr>
          </tbody>
        </table>
      </div>
      <!-- 4 -->
      <div class="summary-item">
        <div class="summary-item-header">House Consumption</div>
        <table class="summary-table">
          <tbody>
            <tr><td class="st-energy" style="color:#a855f7"><span id="sum-load">—</span> W</td></tr>
            <tr><td class="st-label" style="color:var(--text-muted);font-size:0.8rem">Live Load</td></tr>
          </tbody>
        </table>
      </div>
    </section>"""

html = re.sub(r'<section class="summary-strip">.*?</section>', summary_html, html, flags=re.DOTALL)
html = html.replace('?v=5', '?v=6')
with open('dashboard/static/dashboard.html', 'w') as f:
    f.write(html)

# 2. FIX JS THEME TOGGLE
with open('dashboard/static/js/dashboard.js', 'r') as f:
    js = f.read()

theme_logic = """
const THEME_CYCLE  = ["light", "dark", "auto"];
const THEME_LABELS = { light: "☀️ Light", dark: "🌙 Dark", auto: "◐ Auto" };

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("hegg-theme", theme);
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = THEME_LABELS[theme] ?? theme;
}

function cycleTheme() {
  const current = document.documentElement.dataset.theme || "light";
  const next    = THEME_CYCLE[(THEME_CYCLE.indexOf(current) + 1) % THEME_CYCLE.length];
  applyTheme(next);
}

document.addEventListener("DOMContentLoaded", () => {
    const toggleBtn = document.getElementById("theme-toggle");
    if (toggleBtn) {
        toggleBtn.addEventListener("click", cycleTheme);
        const savedTheme = document.documentElement.dataset.theme || "light";
        toggleBtn.textContent = THEME_LABELS[savedTheme] ?? savedTheme;
    }
"""

js = js.replace('document.addEventListener("DOMContentLoaded", () => {', theme_logic)
with open('dashboard/static/js/dashboard.js', 'w') as f:
    f.write(js)

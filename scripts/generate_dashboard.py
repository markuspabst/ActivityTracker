import argparse
import csv
import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

# Reuse the shared data / tracking layer
import tracking
from tracking import (
    read_csv_data,
    get_day_from_csv,
    get_current_week_dates,
    get_weekly_seconds_from_csv,
    DATA_DIR,
    CSV_FILE,
)

OUTPUT_HTML = Path.home() / "ActivityTracker_Dashboard.html"
OUTPUT_JS = Path.home() / "ActivityTracker_Dashboard_Data.js"

# -------- TARGETS --------

DAILY_TARGET = 8 * 3600
WEEKLY_TARGET = 40 * 3600


# ------------------------------------------------------------
# DATA LOAD (reuses tracking module's CSV reader)
# ------------------------------------------------------------

def _last_n_days(n):
    """Get last n days of data, filling missing dates with zeros."""
    csv_data = read_csv_data()
    today = datetime.now().date()
    result = []

    for i in range(n):
        d = (today - timedelta(days=i)).isoformat()
        day = get_day_from_csv(d, csv_data)
        result.append({
            "date": d,
            "active": day["active_seconds"],
            "idle": day["idle_seconds"],
        })

    return list(reversed(result))


# ------------------------------------------------------------
# PRODUCTIVITY SCORE
# ------------------------------------------------------------

def compute_score():
    last7 = _last_n_days(7)
    today = last7[-1]
    active = today["active"]
    idle = today["idle"]

    # Target
    target_ratio = min(active / DAILY_TARGET, 1.2) if DAILY_TARGET else 0
    target_score = min(target_ratio * 100, 100)

    # Consistency
    met_days = sum(1 for r in last7 if r["active"] >= DAILY_TARGET)
    consistency = (met_days / 7) * 100

    # Focus
    total = active + idle
    focus = (active / total * 100) if total else 0

    score = (
        0.5 * target_score +
        0.25 * consistency +
        0.25 * focus
    )

    return {
        "score": round(score, 1),
        "target": round(target_score, 1),
        "consistency": round(consistency, 1),
        "focus": round(focus, 1),
        "met_days": met_days
    }


# ------------------------------------------------------------
# BUILD DATA
# ------------------------------------------------------------

def build_data():
    last7 = _last_n_days(7)
    score = compute_score()

    return {
        "generated": datetime.now().strftime("%H:%M:%S"),
        "last7": [
            {"date": r["date"], "hours": round(r["active"] / 3600, 2)}
            for r in last7
        ],
        "target": DAILY_TARGET / 3600,
        "score": score
    }


def write_data(data):
    with open(OUTPUT_JS, "w") as f:
        f.write("window.DATA = " + json.dumps(data))


# ------------------------------------------------------------
# HTML
# ------------------------------------------------------------

def build_html():
    return f"""
<html>
<head>
<title>Dashboard</title>
<style>
body {{
  background:#111;
  color:#fff;
  font-family:sans-serif;
}}

.card {{
  background:#222;
  padding:20px;
  margin:20px;
  border-radius:10px;
}}

.progress {{
  height:20px;
  background:#333;
}}

.fill {{
  height:100%;
  background:linear-gradient(90deg, red, orange, yellow, green);
}}

</style>
</head>

<body>

<h1>ActivityTracker Dashboard</h1>

<div class="card">
<h2>Productivity Score</h2>
<div id="score"></div>

<div class="progress">
<div id="bar" class="fill"></div>
</div>

<p id="details"></p>
</div>

<script>

// Load data dynamically WITHOUT reload
function loadData() {{
  return new Promise((res, rej) => {{
    const s = document.createElement("script");
    s.src = "ActivityTracker_Dashboard_Data.js?_=" + Date.now();
    s.onload = () => res(window.DATA);
    s.onerror = rej;
    document.body.appendChild(s);
  }});
}}

function updateUI(d) {{
  const s = d.score;

  document.getElementById("score").innerText = s.score + "%";

  document.getElementById("bar").style.width = s.score + "%";

  document.getElementById("details").innerHTML =
    "Target: " + s.target + "%<br>" +
    "Consistency: " + s.consistency + "%<br>" +
    "Focus: " + s.focus + "%";
}}

async function refresh() {{
  const d = await loadData();
  updateUI(d);
}}

refresh();
setInterval(refresh, 10000);

</script>

</body>
</html>
"""


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main(data_only=False):
    """Generate ActivityTracker dashboard."""
    # Ensure tracking module has paths initialised
    tracking.set_data_dir(tracking.get_configured_data_dir())

    data = build_data()
    write_data(data)

    if data_only:
        return

    with open(OUTPUT_HTML, "w") as f:
        f.write(build_html())

    # Prefer the cross-platform webbrowser API; fall back to macOS `open` if needed
    try:
        webbrowser.open(f"file://{OUTPUT_HTML}")
    except Exception:
        subprocess.run(["open", str(OUTPUT_HTML)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate ActivityTracker dashboard.")
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Generate data only, don't open browser"
    )
    args = parser.parse_args()
    main(data_only=args.data_only)
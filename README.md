# ActivityTracker

Lightweight macOS menu bar app that tracks active vs. idle working time, with
crash-safe session recovery, daily/weekly targets, a productivity dashboard,
localization, and a fully automated versioning + build pipeline.

The app runs as a **menu bar-only app (no Dock icon)** via `LSUIElement`.

---

## 1. Overview

ActivityTracker measures how much of your day is *active* vs. *idle* and logs it
to a CSV you own. It is designed for:

- tracking active / idle / total time per day
- persistent daily logging (CSV is the source of truth)
- crash-safe recovery from an unclean shutdown (JSON state file)
- configurable daily and weekly targets
- configurable storage location
- autostart on login (macOS LaunchAgent)
- an HTML productivity dashboard
- English and German localization (auto-detected from the system locale)

---

## 2. Architecture

| Component | Responsibility | Where |
|-----------|----------------|-------|
| Menu UI | Displays metrics, targets, and settings | `activity_tracker_menu.py` (`ActivityTrackerApp`) |
| Idle detection | Reads macOS `HIDIdleTime` via `ioreg` | `get_idle_time()` |
| Runtime engine | Computes active/idle/total session metrics every 5 s | `calculate_current_session()`, `update()` |
| CSV storage | Long-term daily persistence (pandas read/write) | `read_csv_data()` / `write_csv_data()` |
| State file | Crash-safe recovery of unsaved time | `read_state()` / `recover_previous_session_if_needed()` |
| Config | User preferences, validated with pydantic | `AppConfig`, `load_config()` / `save_config()` |
| LaunchAgent | Autostart via `launchctl` | `install_autostart()` / `uninstall_autostart()` |
| i18n | Locale-aware UI strings | `i18n.py`, `locales/*.json` |
| Dashboard | HTML productivity report | `scripts/generate_dashboard.py` |

### Timing constants (`activity_tracker_menu.py`)

| Constant | Value | Meaning |
|----------|-------|---------|
| `IDLE_THRESHOLD` | 300 s | Considered idle after 5 minutes of no input |
| `UPDATE_INTERVAL` | 5 s | UI + state refresh interval |
| `WRITE_INTERVAL` | 3600 s | CSV auto-save interval (also saved on quit / force-save / folder change) |
| `DEFAULT_TARGET_SECONDS` | 8 h | Default daily target |
| `DEFAULT_WEEKLY_TARGET_SECONDS` | 40 h | Default weekly target |

---

## 3. Features

### 3.1 Tracking
- Active, idle, and total time for the current day
- Live menu bar title with a status icon (🟢 target met · 🟡 below target · 🔴 idle)
- Daily and weekly overtime/undertime vs. target

### 3.2 Persistence
- **CSV** — source of truth, one row per day (`activity_tracker_log.csv`)
- **JSON state** — recovery snapshot (`activity_tracker_state.json`)
- **JSON config** — user settings (`activity_tracker_config.json`)

By default these live under `~/Library/Application Support/ActivityTracker`
(resolved via `platformdirs`). The data folder is configurable from the Settings menu.

### 3.3 Recovery
On launch, if the previous session ended uncleanly (state marked `dirty`), the app:
- detects the unfinished session,
- restores the unsaved time delta into the CSV,
- avoids double-counting already-saved time,
- ignores offline time beyond what was recorded.

### 3.4 Settings menu
- **Data folder** — select / open / reset to default
- **Daily target** — 6 h / 8 h / 10 h presets or a custom slider (4–12 h)
- **Weekly target** — 30 h / 40 h / 50 h presets or a custom slider (20–60 h)
- **Autostart** — enable/disable login autostart; open the LaunchAgent file
- **Version / build date**
- **Force save** and **Quit**

### 3.5 Dashboard
The *Enterprise Dashboard* menu item generates an HTML report
(`~/ActivityTracker_Dashboard.html`) showing the last 7 days and a productivity
score (target attainment, consistency, focus). While open, it auto-refreshes its
data every 10 seconds.

---

## 4. Requirements

- **macOS** (uses `rumps`, AppKit, `ioreg`, and `launchctl`)
- **Python 3.14**

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Key libraries: `rumps` + `pyobjc` (menu bar / native dialogs), `platformdirs`
(storage paths), `pandas` (CSV handling), `pydantic` (config validation),
`tenacity` (launchctl retry), `typer` (dashboard CLI), `py2app` (packaging).

---

## 5. Running

### From source
```bash
python3 activity_tracker_menu.py
```

### Generate the dashboard manually
```bash
python3 scripts/generate_dashboard.py            # build + open in browser
python3 scripts/generate_dashboard.py --data-only # refresh data only
```

---

## 6. Building the macOS app

Packaged with `py2app`. The VS Code tasks (`.vscode/tasks.json`) wrap the full
pipeline; the default **Build and Run App** task runs:

1. **Bump Version** — `scripts/bump_version.py` increments the build counter and
   timestamp in `version.json`
2. **Clean** — removes `build/` and `dist/`
3. **Build App** — `python setup.py py2app`
4. **Open App** — launches `dist/ActivityTracker.app`

Or from the command line:

```bash
python scripts/bump_version.py
rm -rf build dist
python setup.py py2app
open dist/ActivityTracker.app
```

Autostart requires the packaged `.app` (the LaunchAgent points at the bundled
executable), so build and run the `.app` before enabling it.

---

## 7. Localization

UI strings live in `locales/*.json` (`en`, `de`). The active locale is taken from
`config.locale` if set, otherwise auto-detected from the system locale. To add a
language, copy `locales/en.json` to `locales/<lang>.json` and translate the values.

---

## 8. Project layout

```
activity_tracker_menu.py     # main menu bar app
i18n.py                      # localization loader
locales/                     # en.json, de.json
scripts/
  generate_dashboard.py      # HTML productivity dashboard
  bump_version.py            # version/build bumper
setup.py                     # py2app build config
version.json                 # source of truth for app version
requirements.txt
```

# ActivityTracker

Lightweight macOS menu bar app that tracks active vs. idle working time, with crash-safe session recovery, daily/weekly targets, a productivity dashboard, localization, and a fully automated versioning + build pipeline.

The app runs as a **menu bar-only app (no Dock icon)** via `LSUIElement`.

---

## 1. Getting Started

### Prerequisites

-   **macOS**
-   **Python 3.14**

### Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/your-username/ActivityTracker.git
    cd ActivityTracker
    ```

2.  **Create a virtual environment and install dependencies:**

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

### Running the App

-   **From source:**

    ```bash
    python3 app.py
    ```

-   **Build the macOS app:**

    ```bash
    python scripts/bump_version.py
    rm -rf build dist
    python setup.py py2app
    open dist/ActivityTracker.app
    ```

---

## 2. Features

-   **Time Tracking:** Tracks active, idle, and total time per day, with segments loaded on startup for continuous tracking.
-   **Live Menu Bar:** Shows a status icon (🟢 target met, 🟡 below target, 🔴 idle) and live time display with session start time and accumulating active time.
-   **Daily & Weekly Targets:** Set and monitor daily and weekly work goals. The status icon will turn green if either goal is met.
-   **Persistence:**
    -   **CSV:** Stores detailed time segments in `segments-{year}.csv` and daily summaries in `daily-{year}.csv` (rotated annually).
    -   **JSON State:** Ensures crash-safe recovery of ongoing sessions with `activity_tracker_state.json`.
    -   **JSON Config:** Saves user settings and preferences in `activity_tracker_config.json`.
-   **Midnight-safe:** Sessions reset at midnight, providing clean counters for each new day.
-   **Accurate Segment End Times:** `end_time` for segments reflects the last moment of activity, preventing idle time after activity from being counted into active duration.
-   **Robust Session Recovery:** Recovers ongoing tracking sessions after abnormal termination, and loads all previously saved segments for the current day on clean restarts.
-   **Customizable Data Folder:** Change the storage location from the Settings menu.
-   **Autostart:** Automatically starts on login.
-   **Productivity Dashboard:** Generates an HTML report with productivity insights.
-   **Localization:** Supports English and German, with auto-detection from the system locale.

---

## 3. Architecture

| Component | Responsibility | Where |
|---|---|---|
| App Controller | Core application logic, event loop, save scheduling | `app.py` (`ActivityTrackerApp`) |
| Session Tracker | Pure data model: computes active/idle/total, tracks idle transitions, detects midnight rollover | `tracking.py` (`SessionTracker`) |
| Data Models | `TimeSegment` and `Day` dataclasses for representing tracking data | `models.py` (`TimeSegment`, `Day`) |
| Tray Icon | Generates the tray icon image and determines its color based on work goals | `tray_icon.py` |
| Menu UI | Displays metrics, targets, and settings | `activity_tracker_menu.py` (`AppMenu`) |
| Idle detection | Native Quartz idle API (falls back to `ioreg`) | `platform_layer/*.py` (`get_idle_time()`) |
| CSV Persistence | Long-term daily persistence of segments and summaries in CSV files (`segments-{year}.csv`, `daily-{year}.csv`) | `persistence.py` (`PersistenceManager`) |
| State file | Crash-safe recovery of ongoing unsaved session data | `tracking.py` (`write_state()`, `recover_from_crash()`) |
| Config | User preferences, cached validated values | `tracking.py` (`AppConfig`, `load_config()` / `save_config()`) |
| LaunchAgent | Autostart via `launchctl` | `platform_layer/*.py` (`install_autostart()` / `uninstall_autostart()`) |
| i18n | Locale-aware UI strings | `i18n.py`, `locales/*.json` |
| Dashboard | HTML productivity report | `scripts/generate_dashboard.py` |

### Data flow (per tick, every 5 s)

```
[UI TICK (every 5s)]
  ┌─────────────────────────────────┐
  │ `AppController.update()`        │
  ├─ `platform_layer.get_idle_time()`
  ├─→ `SessionTracker.on_tick(idle_time, idle_threshold)`
  │    (Updates `self.session.days` and `self.current_segment`)
  │
  ├─ `SessionTracker.save_all_days()` (if `write_interval` met)
  │    (Triggers `PersistenceManager.save_segments()` and `save_daily_summary()`)
  │      → `segments-{year}.csv`, `daily-{year}.csv`
  │
  ├─ `SessionTracker.write_state(dirty=True)`
  │    → `activity_tracker_state.json` (stores last segment info for crash recovery)
  │
  └─→ `AppController.update_ui()`
       ├─ (Reads from `self.session.days` for current day's active/idle)
       ├─ (Calls `PersistenceManager.read_daily_summary_for_day()` for past days in week)
       └─→ `AppMenu.update_ui()` (updates tray icon and menu entries)
```

### Timing Constants

| Constant | Default | Meaning |
|---|---|---|
| Tick interval (hard-coded) | 5 s | UI + state refresh interval |
| `DEFAULT_SAVE_INTERVAL_SECONDS` | 3600 s | CSV auto-save interval (user-configurable) |
| `DEFAULT_IDLE_THRESHOLD` | 300 s | Considered idle after 5 min of no input (user-configurable) |

### CSV structure

**`segments-{year}.csv` (e.g., `segments-2026.csv`)**
Each row represents a continuous time segment (active or idle):

| Column | Description |
|---|---|
| `date` | Calendar date (YYYY-MM-DD) |
| `state` | Segment type (`active` or `idle`) |
| `start` | Segment start time (HH:MM) |
| `end` | Segment end time (HH:MM) |
| `duration_min` | Duration of the segment in minutes |

**`daily-{year}.csv` (e.g., `daily-2026.csv`)**
Each row stores the aggregated summary for one day:

| Column | Description |
|---|---|
| `date` | Calendar date (YYYY-MM-DD) |
| `active_min` | Total active minutes for the day |
| `idle_min` | Total idle minutes for the day |
| `session_start` | Start time of the first active segment for the day (HH:MM) |
| `session_end` | End time of the last active segment for the day (HH:MM) |

---

## 4. Running Tests

```bash
python3 -m pytest tests/ -v
```

The test suite covers idle detection, idle transitions, midnight rollover, per-day session reset, delta consistency, `last_active_time` tracking, pre-activity idle exclusion, and multi-break scenarios.

---

## 5. Contributing

Contributions are welcome! Please follow these steps to contribute:

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/your-feature-name`).
3.  Make your changes and commit them (`git commit -m 'Add some feature'`).
4.  Push to the branch (`git push origin feature/your-feature-name`).
5.  Open a pull request.

---

## 6. License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
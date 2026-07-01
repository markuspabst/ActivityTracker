# ActivityTracker

Lightweight macOS menu bar app that tracks active vs. idle working time, with crash-safe session recovery, daily/weekly targets, a productivity dashboard, localization, and a fully automated versioning + build pipeline.

The app runs as a **menu bar-only app (no Dock icon)** via `LSUIElement`.

---

## 1. Getting Started

### Prerequisites

- **macOS**
- **Python 3.14**

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

-   **Time Tracking:** Tracks active, idle, and total time per day. Each day's tracking starts fresh after the first keyboard/mouse activity.
-   **Live Menu Bar:** Shows a status icon (🔊 target met, 🟡 below target, 🔴 idle) and live time display.
-   **Daily & Weekly Targets:** Set and monitor daily and weekly work goals.
-   **Persistence:**
    -   **CSV:** Stores daily logs with per-day start/end times in `activity_tracker_log.csv`.
    -   **JSON State:** Ensures crash-safe recovery with `activity_tracker_state.json`.
    -   **JSON Config:** Saves user settings in `activity_tracker_config.json`.
-   **Midnight-safe:** Session resets at midnight — each day gets its own `start_time` and clean counters, even if the app runs continuously.
-   **End Time from Last Activity:** The CSV `end_time` reflects the last moment of activity, not the save timestamp — idle time after the last activity is excluded.
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
| Menu UI | Displays metrics, targets, and settings | `activity_tracker_menu.py` (`AppMenu`) |
| Idle detection | Native Quartz idle API (falls back to `ioreg`) | `platform_layer/*.py` (`get_idle_time()`) |
| CSV storage | Long-term daily persistence (stdlib `csv`) | `tracking.py` (`read_csv_data()` / `add_delta_to_csv()`) |
| State file | Crash-safe recovery of unsaved time | `tracking.py` (`read_state()` / `recover_previous_session_if_needed()`) |
| Config | User preferences, cached validated values | `tracking.py` (`AppConfig`, `load_config()` / `save_config()`) |
| LaunchAgent | Autostart via `launchctl` | `platform_layer/*.py` (`install_autostart()` / `uninstall_autostart()`) |
| i18n | Locale-aware UI strings | `i18n.py`, `locales/*.json` |
| Dashboard | HTML productivity report | `scripts/generate_dashboard.py` |

### Data flow (per tick, every 5 s)

```
platform_layer.get_idle_time()  ─┐
                                 ├─→  SessionTracker.calculate_current_session()
SessionTracker.on_tick(is_idle)  ─┘    →  active / idle / total / is_idle
                                          │
                                          ├─→  app._do_save_delta()  →  CSV (every WRITE_INTERVAL)
                                          │
                                          └─→  menu.update_ui()      →  tray icon & tooltip
```

### Timing Constants

| Constant | Default | Meaning |
|---|---|---|
| Tick interval (hard-coded) | 5 s | UI + state refresh interval |
| `DEFAULT_SAVE_INTERVAL_SECONDS` | 3600 s | CSV auto-save interval (user-configurable) |
| `DEFAULT_IDLE_THRESHOLD` | 300 s | Considered idle after 5 min of no input (user-configurable) |

### CSV structure (`activity_tracker_log.csv`)

Each row stores the aggregate for one date:

| Column | Description |
|---|---|
| `date` | Calendar date (ISO‑8601) |
| `start_time` | First activity of that day |
| `end_time` | Last moment of activity (not save time) |
| `total_seconds` | Total elapsed time (active + idle) |
| `active_seconds` | Time with keyboard/mouse input |
| `idle_seconds` | Time idle (idle before first activity is excluded) |
| `total_hours` / `active_hours` / `idle_hours` | Same as seconds, in decimal hours |

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
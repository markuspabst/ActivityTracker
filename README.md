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
    python3 activity_tracker_menu.py
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

-   **Time Tracking:** Tracks active, idle, and total time per day.
-   **Live Menu Bar:** Shows a status icon (ð target met, ð below target, ð´ idle) and live updates.
-   **Daily & Weekly Targets:** Set and monitor daily and weekly work goals.
-   **Persistence:**
    -   **CSV:** Stores daily logs in `activity_tracker_log.csv`.
    -   **JSON State:** Ensures crash-safe recovery with `activity_tracker_state.json`.
    -   **JSON Config:** Saves user settings in `activity_tracker_config.json`.
-   **Customizable Data Folder:** Change the storage location from the Settings menu.
-   **Autostart:** Automatically starts on login.
-   **Productivity Dashboard:** Generates an HTML report with productivity insights.
-   **Localization:** Supports English and German, with auto-detection from the system locale.

---

## 3. Architecture

| Component | Responsibility | Where |
|---|---|---|
| Menu UI | Displays metrics, targets, and settings | `activity_tracker_menu.py` (`ActivityTrackerApp`) |
| Idle detection | Native Quartz idle API (falls back to `ioreg`) | `get_idle_time()` |
| Runtime engine | Computes active/idle/total session metrics every 5 s | `calculate_current_session()`, `update()` |
| CSV storage | Long-term daily persistence (stdlib `csv`) | `read_csv_data()` / `write_csv_data()` |
| State file | Crash-safe recovery of unsaved time| `read_state()` / `recover_previous_session_if_needed()` |
| Config | User preferences, cached validated values | `AppConfig`, `load_config()` / `save_config()` |
| LaunchAgent | Autostart via `launchctl` | `install_autostart()` / `uninstall_autostart()` |
| i18n | Locale-aware UI strings | `i18n.py`, `locales/*.json` |
| Dashboard | HTML productivity report | `scripts/generate_dashboard.py` |

### Timing Constants

| Constant | Default Value | Meaning |
|---|---|---|
| `UPDATE_INTERVAL` | 5s | UI + state refresh interval |
| `WRITE_INTERVAL` | 3600s | CSV auto-save interval |
| `DEFAULT_IDLE_THRESHOLD` | 300s | Idle after 5 min of no input (user-configurable) |

---

## 4. Contributing

Contributions are welcome! Please follow these steps to contribute:

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/your-feature-name`).
3.  Make your changes and commit them (`git commit -m 'Add some feature'`).
4.  Push to the branch (`git push origin feature/your-feature-name`).
5.  Open a pull request.

---

## 5. License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

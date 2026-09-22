# ActivityTracker

A lightweight system tray application that tracks your active and idle time using CSV-only persistence.

![License](https://img.shields.io/github/license/markuspabst/ActivityTracker)
![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![macOS](https://img.shields.io/badge/platform-macos-lightgray)
![macOS 27](https://img.shields.io/badge/macOS-27+-success.svg)
![Tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/markuspabst/ActivityTracker/main/tests/badge.json)

## Features

- **Time Tracking**: Tracks active (working) and idle time with minute precision
- **Live Menu Bar**: Shows status icon and live active/idle time display with visual indicators
- **Weekly Statistics**: Aggregates time across the week with progress bars
- **Daily Report**: A report submenu shows the last seven active days with start
  time, last active time, active time, idle time, and a productivity score
- **CSV-Only Persistence**: All time data stored in `activities-{year}.csv` files; a tiny `state.json` keeps only the last-write timestamp for crash recovery
- **Sleep Detection**: System sleep/suspend intervals are classified as idle time
- **Crash Recovery**: An open segment left by an abnormal shutdown is finalized to the last saved write time on next launch
- **Save-Failure Resilience**: On a disk-write failure, data is retained in memory, the user is alerted once, and saving retries on the next interval
- **Daily & Weekly Targets**: Set and monitor work goals with configurable presets
- **Automatic CSV Optimization**: Consecutive same-state segments are merged automatically on every save, keeping the log compact with no manual action
- **Idle Threshold**: Configurable idle detection period (default: 5 minutes)
- **Save Interval**: Configurable data persistence interval
- **Language Support**: Multi-language (English, German)
- **Automatic Startup**: Optional autostart on system login
- **Version Display**: Shows the current version in the general settings menu
- **macOS 27+ Compatible**: Fixed crashes on macOS 27+ by dispatching all pystray menu operations to the main thread using `Foundation.performSelectorOnMainThread_withObject_waitUntilDone_`

## Quick Links

- [Quick Start](#quick-start) - Get up and running in minutes
- [Configuration](#configuration) - Customize targets, thresholds, and behavior
- [Testing](#testing) - Run the test suite

## Architecture

### Data Flow

```
[App ticks every 10 seconds]
  ┌──────────────────────────────────┐
  │ ActivityTrackerApp.update()      │
  ├─ platform_layer.get_idle_time()  │
  ├─ SessionTracker.on_tick()        │
  │   (Updates session.days & current_segment)
  │
  ├─ SessionTracker.save_all_days()  │ (if save_interval met)
  │   └─ PersistenceManager.save_segments()
  │       → activities-{year}.csv
  │
  └─ AppMenu.update_ui()             │ (dispatches to main thread on macOS)
      ├─ Read from session.days for active/idle
      └─ Icon updates                │ (main thread required on macOS 27+)
```

### File Structure

```
~/.config/ActivityTracker/
├── activities-{year}.csv          # Segment data (one row per active/idle segment)
├── state.json                     # Runtime metadata (last successful write time)
└── activity_tracker_config.json   # User settings
```

### CSV Format

**`activities-{year}.csv`** - Detailed time segments (the single source of
truth for all aggregates):

| Column | Description |
|--------|-------------|
| date | Calendar date (YYYY-MM-DD) |
| state | active or idle |
| start | Start time (HH:MM:SS) |
| end | End time (HH:MM:SS) or empty for ongoing |
| duration_min | Duration in minutes (integer, floored) |
| duration_seconds | Duration in seconds (for precision) |

Per-day and per-week active/idle totals (`get_minutes_for_date`,
`get_weekly_minutes`) are derived directly from the segment log, so there is no
separate daily-summary file. The day's `active_min + idle_min` always matches
the sum of its segment durations. Days with no activity contribute zero.

## Quick Start

### Prerequisites
- Python 3.9 or higher
- macOS 10.15+ (native support); Linux/Windows support via `platform_layer/`

### Installation

```bash
# Clone and install
git clone https://github.com/markuspabst/ActivityTracker.git
cd ActivityTracker
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[macos,dev]"
```

### Running

```bash
# Run the application
python3 -m activitytracker
```

The app will appear in your system tray with a yellow indicator. Click the icon to view your progress or adjust settings.

### Building (macOS)

To create a standalone macOS application:

```bash
briefcase build macOS
# App will be in ./build/activitytracker/macos/app/ActivityTracker.app

# Optional: create a distributable DMG
briefcase package macOS
# DMG will be in ./dist/
```

The release workflow uses ad-hoc signing. For public distribution on other
Macs, configure a Developer ID certificate and notarization.

### Versioning

The application version is managed directly in `pyproject.toml`:

```toml
[project]
version = "1.0.4"
```

The version is incremented automatically when creating a release.

To publish a GitHub release from VS Code:

1. Commit all current changes.
2. Open **Terminal → Run Task...**.
3. Select **Release: Create GitHub Release**.
4. Choose `patch`, `minor`, or `major` when prompted.

The task increments `[project].version` in `pyproject.toml`, commits the change,
builds the macOS app, packages the DMG, creates a `v<version>` tag, and pushes it.
The GitHub Actions workflow then creates the release automatically with the
macOS DMG and a zipped `.app` bundle. GitHub's automatic source archives are
also available. It requires
the repository remote to be named `origin` and the GitHub account to have push access.

## macOS 27 Compatibility

ActivityTracker includes a fix for macOS 27's stricter threading requirements. All pystray menu bar icon operations are now dispatched to the main thread using Foundation's `performSelectorOnMainThread_withObject_waitUntilDone_`. This prevents crashes that occurred when background threads tried to call AppKit methods like `NSStatusItem.setMenu_`.

## Configuration

Access via system tray icon → Settings:

- **Daily Target**: Default 8 hours (480 minutes)
- **Weekly Target**: Default 40 hours (2400 minutes)  
- **Idle Threshold**: Default 5 minutes (300 seconds)
- **Save Interval**: Default 1 hour (3600 seconds)
- **Language**: English or German

## CSV Optimization

The activity log is optimized automatically: after every successful save, consecutive
same-state segments whose gaps are within the idle threshold are merged into a
single segment. This runs on the same cadence as the save interval, so the on-disk
data stays compact without any manual action. (The `optimize_csv` routine is also
available programmatically if a one-off merge is ever needed.)

## Testing

```bash
# Run all tests
pytest tests/ -v

# Specific test files
pytest tests/test_tracking.py -v      # Session tracking & persistence
pytest tests/test_requirements.py -v  # Feature requirements
pytest tests/test_scenarios.py -v     # Integration scenarios
```

### Component Overview

| Component | Responsibility |
|-----------|---------------|
| `activitytracker/app.py` | Main application controller, event loop, save scheduling |
| `activitytracker/tracking.py` | SessionTracker: active/idle detection, sleep-gap detection, midnight rollover, orphan finalization, segment management |
| `activitytracker/persistence.py` | CSV I/O, weekly aggregation, segment merging, data persistence resilience |
| `activitytracker/models.py` | TimeSegment and Day dataclasses |
| `activitytracker/activity_tracker_menu.py` | System tray menu UI (macOS 27+: all operations dispatch to main thread) |
| `activitytracker/platform_layer/` | Native idle detection and platform helpers |
| `activitytracker/tray_icon.py` | Icon generation helper functions |
| `activitytracker/i18n.py` | Internationalization support (EN, DE) |
| `activitytracker/single_instance.py` | Single-instance lock to prevent duplicate apps |

## Data Persistence

| Requirement | Description | Implementation |
|-------------|-------------|----------------|
| **Data Resilience** | On a disk-write failure, data is retained in memory, user is alerted once, and saving retries on the next interval | Implemented in `activitytracker/app.py` and `activitytracker/persistence.py` |

## License

MIT License

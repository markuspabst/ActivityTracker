# ActivityTracker

A lightweight system tray application that tracks your active and idle time using CSV-only persistence.

## Features

- **Time Tracking**: Tracks active (working) and idle time with minute precision
- **Live Menu Bar**: Shows status icon and live active/idle time display
- **Weekly Statistics**: Aggregates time across the week
- **CSV-Only Persistence**: All time data stored in `activities-{year}.csv` files; a tiny `state.json` keeps only the last-write timestamp for crash recovery
- **Sleep Detection**: System sleep/suspend intervals are classified as idle time
- **Crash Recovery**: An open segment left by an abnormal shutdown is finalized to the last saved write time on next launch
- **Save-Failure Resilience**: On a disk-write failure, data is retained in memory, the user is alerted once, and saving retries on the next interval
- **Daily & Weekly Targets**: Set and monitor work goals
- **Automatic CSV Optimization**: Consecutive same-state segments are merged automatically on every save, keeping the log compact with no manual action
- **Idle Threshold**: Configurable idle detection period (default: 5 minutes)
- **Save Interval**: Configurable data persistence interval
- **Language Support**: Multi-language (English, German)

## Architecture

### Data Flow

```
[App ticks every 5 seconds]
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
  └─ AppController.update_ui()
      ├─ Read from session.days for active/idle
      └─ AppMenu.update_ui()
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

## Installation

```bash
# Clone and install
git clone https://github.com/markuspabst/ActivityTracker.git
cd ActivityTracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run
python3 app.py
```

## Configuration

Access via system tray icon → Settings:

- **Daily Target**: Default 8 hours (480 minutes)
- **Weekly Target**: Default 40 hours (2400 minutes)  
- **Idle Threshold**: Default 5 minutes (300 seconds)
- **Save Interval**: Default 1 hour (3600 seconds)

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

## Component Overview

| Component | Responsibility |
|-----------|---------------|
| `app.py` | Main application controller, event loop, save scheduling |
| `tracking.py` | SessionTracker: active/idle detection, sleep-gap detection, midnight rollover, orphan finalization, segment management |
| `persistence.py` | CSV I/O, weekly aggregation, segment merging |
| `models.py` | TimeSegment and Day dataclasses |
| `activity_tracker_menu.py` | System tray menu UI |
| `platform_layer/` | Native idle detection |
| `locales/` | Translation files (EN, DE) |

## Requirements

- Python 3.9+
- platformdirs
- pystray, Pillow (system tray icon)
- On macOS: pyobjc (`pyobjc-core`, `pyobjc-framework-Cocoa`, `pyobjc-framework-Quartz`) for native idle detection, dialogs, and autostart

## License

MIT License

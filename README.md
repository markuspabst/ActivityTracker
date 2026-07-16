# ActivityTracker

A lightweight system tray application that tracks your active and idle time using CSV-only persistence.

## Features

- **Time Tracking**: Tracks active (working) and idle time with minute precision
- **Live Menu Bar**: Shows status icon and live active/idle time display
- **Weekly Statistics**: Aggregates time across the week
- **CSV-Only Persistence**: All data stored in `activities-{year}.csv` files (no JSON state files)
- **Daily & Weekly Targets**: Set and monitor work goals
- **Manual Optimization**: Merge consecutive same-state segments via Settings menu
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
  │   ├─ PersistenceManager.save_segments()
  │   │   → activities-{year}.csv
  │   └─ (No daily summary CSV - stats calculated on read)
  │
  └─ AppController.update_ui()
      ├─ Read from session.days for active/idle
      └─ AppMenu.update_ui()
```

### File Structure

```
~/.config/ActivityTracker/
├── activities-{year}.csv          # Segment data (one per year)
└── activity_tracker_config.json   # User settings
```

### CSV Format

**`activities-{year}.csv`** - Detailed time segments:

| Column | Description |
|--------|-------------|
| date | Calendar date (YYYY-MM-DD) |
| state | active or idle |
| start | Start time (HH:MM:SS) |
| end | End time (HH:MM:SS) or empty for ongoing |
| duration_min | Duration in minutes (integer, floored) |
| duration_seconds | Duration in seconds (for precision) |

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

### Manual Optimization

Settings → **Optimize CSV**

Merges consecutive same-state segments with gaps < 50% of idle threshold.

### Auto-Optimization

Automatically triggers after saves when:
- More than 15 segments exist for the current day
- 24+ hours have passed since last optimization

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
| `tracking.py` | SessionTracker: active/idle detection, midnight rollover, segment management |
| `persistence.py` | CSV I/O, weekly aggregation, segment merging |
| `models.py` | TimeSegment and Day dataclasses |
| `activity_tracker_menu.py` | System tray menu UI |
| `platform_layer/` | Native idle detection |
| `locales/` | Translation files (EN, DE) |

## Requirements

- Python 3.9+
- platformdirs
- i18n

## License

MIT License

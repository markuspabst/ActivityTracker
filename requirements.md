# ActivityTracker Dependencies

This document lists the runtime and development dependencies for ActivityTracker.

## Runtime Dependencies

| Package | Description |
|---------|-------------|
| `pystray` | System tray icon support (menu-bar app) |
| `pillow` | Image processing for tray icons |
| `platformdirs` | Platform-specific directory detection |

## macOS-Specific Dependencies (for native menu-bar app)

| Package | Description |
|---------|-------------|
| `pyobjc-core` | Core PyObjC bindings for Cocoa |
| `pyobjc-framework-Cocoa` | PyObjC Cocoa framework bindings |
| `pyobjc-framework-Quartz` | PyObjC Quartz framework bindings (idle detection) |
| `std-nslog` | Captures stdout/stderr in macOS app logs |

## Development Dependencies

| Package | Description |
|---------|-------------|
| `pytest` | Testing framework |
| `pytest-cov` | Coverage reporting for pytest |
| `coverage` | Code coverage measurement |

## System Requirements

- **Python**: 3.9 or higher (tested with 3.13)
- **macOS**: Native support with native menu-bar experience (tested on macOS 27)
- **Linux/Windows**: Partial support via `platform_layer/`

## Installing Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Non-Functional Requirements

| ID | Description | Implementation |
|----|-------------|----------------|
| NFR-5.2 | **Data Resilience**: On a disk-write failure, data is retained in memory, user is alerted once, and saving retries on the next interval | Implemented in `activitytracker/app.py` and `activitytracker/persistence.py` |

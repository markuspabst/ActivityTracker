# ActivityTracker Dependencies

This document lists the runtime and development dependencies for ActivityTracker.

## Runtime Dependencies

| Package | Version | Description |
|---------|---------|-------------|
| `pyobjc-core` | 12.2.2 | Core PyObjC bindings for Cocoa |
| `pyobjc-framework-Cocoa` | 12.2.2 | PyObjC Cocoa framework bindings |
| `pyobjc-framework-Quartz` | 12.2.2 | PyObjC Quartz framework bindings |
| `pystray` | 0.19.5 | System tray icon support |
| `pillow` | 12.3.0 | Image processing for tray icons |
| `platformdirs` | 4.11.11 | Platform-specific directory detection |
| `python-dateutil` | 2.9.0.post0 | Date parsing and manipulation |
| `pytz` | 2026.3.post1 | Timezone definitions |
| `pandas` | 3.0.6 | Data processing for CSV operations |
| `requests` | 2.34.2 | HTTP library (optional, for future features) |
| `altgraph` | 0.17.5 | Graph library (py2app dependency) |
| `macholib` | 1.16.4 | Mach-O binary analysis (py2app dependency) |
| `modulegraph` | 0.19.7 | Module dependency analysis (py2app dependency) |
| `py2app` | 0.28.10 | Create macOS applications from Python scripts |
| `Pygments` | 2.21.0 | Syntax highlighting |
| `numpy` | 2.5.3 | Numerical computing (pandas dependency) |
| `typing_extensions` | 4.16.0 | Backported typing features |
| `tzdata` | 2026.4 | Timezone data |
| `certifi` | 2026.7.22 | SSL certificate bundle |
| `charset-normalizer` | 3.5.1 | Character encoding detection |
| `idna` | 3.20 | Internationalized domain names |
| `urllib3` | 2.8.0 | HTTP client library |

## Development Dependencies

| Package | Version | Description |
|---------|---------|-------------|
| `pytest` | 9.1.1 | Testing framework |
| `pytest-cov` | 7.1.0 | Coverage reporting for pytest |
| `coverage` | 7.16.1 | Code coverage measurement |
| `iniconfig` | 2.3.0 | INI file parser (pytest dependency) |
| `packaging` | 26.3 | Version parsing utilities |
| `pluggy` | 1.6.0 | Plugin system (pytest dependency) |
| `tomli` | 2.4.1 | TOML parser |
| `exceptiongroup` | 1.3.1 | Exception handling backport |

## System Requirements

- **Python**: 3.9 or higher (tested with 3.13.15)
- **macOS**: Native support with native menu-bar experience
- **Linux/Windows**: Partial support via `platform_layer/`

## Installing Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Building (macOS)

To create a standalone macOS application:

```bash
python3 setup.py py2app
```

The built app will be in `./dist/ActivityTracker.app`.

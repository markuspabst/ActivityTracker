# ActivityTracker

Lightweight macOS Menu Bar Application to track active vs idle working time with enterprise-grade architecture, recovery, versioning, and automated build pipeline.

---

# 1. Overview

ActivityTracker is a macOS menu bar app designed for:

- tracking active vs idle usage time
- persistent daily logging (CSV)
- crash-safe recovery (JSON state)
- configurable storage location
- enterprise-grade autostart (LaunchAgent)
- fully automated versioning and build process

The application runs as a **menu bar-only app (no Dock icon)** using `LSUIElement`.

---

# 2. Architecture

## 2.1 High-Level Architecture

## 2.2 Components

| Component | Responsibility |
|----------|---------------|
| Menu UI | Displays metrics + settings |
| Idle Detection | Uses macOS HIDIdleTime |
| Runtime Engine | Computes session metrics |
| CSV Storage | Long-term persistence |
| State File | Crash-safe recovery |
| Config | User preferences |
| LaunchAgent | Autostart |

---

# 3. Features

## 3.1 Tracking

- Active time
- Idle time
- Total time
- Session tracking

---

## 3.2 Persistence

- CSV = source of truth
- JSON state = recovery
- JSON config = settings

---

## 3.3 Recovery

- detects unfinished sessions
- restores unsaved delta
- avoids duplication
- ignores offline time

---

## 3.4 Settings Menu



# ActivityTracker Requirements — v2

A macOS menu-bar application that logs working time based on computer usage. Time is classified as **Active** or **Idle**; locked-screen and system-sleep time count as Idle. The app tracks daily and weekly progress against configurable targets and persists data to local CSV files.

## Functional Requirements

### FR-1 Time Tracking
- **FR-1.1** The application shall continuously track working time and classify it into two states: **Active** and **Idle**.
  - *Tested by: `test_session_tracker_tick`*
- **FR-1.2** The application shall classify time as **Active** when user input (keyboard/mouse/trackpad) is detected.
  - *Tested by: `test_session_tracker_tick`*
- **FR-1.3** The application shall classify time as **Idle** when no user input has occurred for a configurable inactivity threshold (see FR-4.2).
  - *Tested by: `test_session_tracker_tick`*
- **FR-1.4** The application shall classify time as **Idle** whenever the screen is locked, regardless of the inactivity threshold.
  - *Tested by: `test_set_locked_true_creates_idle_segment`*
- **FR-1.5** The application shall classify the entire duration of a **system sleep** interval as **Idle**, consistent with locked-screen handling (FR-1.4).
  - *Status: **implemented** — `SessionTracker.on_tick` detects a tick gap far larger than the poll interval (`SLEEP_GAP_THRESHOLD_SECONDS = 60`) and records that interval as Idle via `_insert_sleep_gap` (split at day boundaries). The detector only fires when the system appears active afterward, so a genuine idle stretch is not overwritten. Tested by: `test_on_tick_records_sleep_gap_as_idle`, `test_on_tick_no_false_sleep_gap_for_normal_interval`.*

### FR-2 Session Management
- **FR-2.1** The application shall track each day as a continuous sequence of segments, each classified as **Active** or **Idle** (per FR-1). Locked-screen and system-sleep intervals shall always be recorded as Idle.
- **FR-2.2** The **session start** for a day shall be the start timestamp of the first Active segment of that day (local time); the **session end** shall be the end timestamp of the last Active segment of that day.
  - *Tested by: `test_day_session_start_and_end`*
- **FR-2.3** Idle time shall be counted only within the daily working window (between session start and session end); time outside this window is untracked.
- **FR-2.4** All segments (Active and Idle) shall be bounded by the calendar day. Any segment open at the day boundary shall be closed at the **last second of the day (`23:59:59`, second resolution)** and a new segment of the same state shall be opened at **`00:00:00`** for the new day. No segment shall span more than one date. (See FR-3.8/FR-3.9 for the exact representation.)
- **FR-2.5** The application shall reload segment data for the current day from the local log at startup so tracking continues without data loss.
  - *Status: implemented partially — `SessionTracker.load_current_day_segments()` repopulates the current day from the activities log. Full cross-day crash recovery of unsaved segments is **not** implemented.*
- **FR-2.6** At application startup, any segment left open (end_time is empty) by a previous run shall be treated as **ongoing** and continue tracking from the last saved state.
  - *Status: **implemented** — `SessionTracker.load_current_day_segments` finalizes any open segment from a previous run to the last known write time (persisted via `PersistenceManager.save_last_segment_write` / `read_last_segment_write`); if no write time is known it is conservatively closed at its own start. The orphan is finalized, not resumed as the current segment. Tested by: `test_session_tracker_load_finalizes_orphaned_open_segment`.*

### FR-3 Data Persistence
- **FR-3.1** All tracked time data shall be saved to local CSV files.
  - *Tested by: `test_persistence_manager_save_and_read`*
- **FR-3.2** The application shall maintain a **segment-level log** (one row per Active/Idle segment) using the schema: `date (YYYY-MM-DD), state, start (HH:MM:SS), end (HH:MM:SS), duration_min, duration_seconds`.
- **FR-3.3** Per-day and per-week active/idle totals (the daily summary) shall be **derived from the segment-level log** (no separate file), using the schema: `date (YYYY-MM-DD), active_min, idle_min`. They are computed by summing each day's segment durations (`active_min + idle_min` equals the day's segment total).
- **FR-3.4** Data shall be saved automatically at user-configurable intervals (see FR-4.3).
- **FR-3.5** Data shall be saved automatically when the application is quit.
- **FR-3.6** CSV files shall be **UTF-8** encoded, **comma-delimited**, and include a **header row**. The segment log shall be written to its own file, rotated **per calendar year** (e.g., `activities-2026.csv`).
- **FR-3.7** Days with no recorded activity shall contribute **zero** active/idle minutes to the derived daily summary (no explicit row is stored).
- **FR-3.8** Segment start/end shall be stored at second resolution (HH:MM:SS). Segments are bounded by the calendar day: any segment open at the day boundary is closed at the **last second of the day (`23:59:59`)** and a new segment of the same state is opened at **`00:00:00`** of the new day (see `SessionTracker.on_tick`, tracking.py:119-128). No segment shall span more than one date. The sum of segment durations for a day shall equal `active_min + idle_min` with no gaps or overlaps. Durations are **floored** to whole minutes consistently (not rounded half up).
- **FR-3.9** The day-boundary close is represented by the segment ending at `23:59:59` (last second of the day); a consumer of the CSV shall treat an end time at or after midnight as belonging to the prior day. (The original spec's literal `24:00` sentinel is not used by the implementation.)

### FR-4 Configuration
- **FR-4.1** The user shall be able to set **daily** and **weekly** targets for active time.
  - *Tested by: `test_fr_4_configuration`*
- **FR-4.2** The user shall be able to configure the inactivity duration that qualifies as **idle**.
- **FR-4.3** The user shall be able to configure the auto-save interval.
- **FR-4.4** The user shall be able to specify the directory where the data files are stored.

### FR-5 User Interface (Menu Bar)
- **FR-5.1** The application shall provide a macOS menu bar (status bar) icon.
- **FR-5.2** The icon shall indicate current status (e.g., **active**, **idle**, **target met**) via visual state.
- **FR-5.3** The menu shall display **daily** statistics for the current day, including:
  - (a) the **session start time** (per FR-2.2);
  - (b) the current **Active time vs. daily target** (per FR-4.1);
  - (c) the accumulated **Idle time**.
- **FR-5.4** The menu shall display **weekly** statistics for the current week (**week starts Monday 00:00 local time**), including:
  - (a) the current **Active time vs. weekly target** (per FR-4.1);
  - (b) the accumulated **weekly Idle time**.
- **FR-5.5** The menu shall provide actions to: (a) force an immediate save, (b) open the data file folder, (c) quit the application.
- **FR-5.6** All time values displayed in the UI shall use the `hh:mm` format, with **session start time shown on a 24-hour clock** (e.g., `08:30`) and **durations shown with uncapped hours** (e.g., `40:00` for 40 hours).

### FR-6 Autostart
- **FR-6.1** The user shall be able to configure the application to launch automatically on system startup (macOS Login Items).
  - *Tested by: `test_fr_6_autostart`*

### FR-7 Permissions (macOS)
- **FR-7.1** The application shall request the macOS **Accessibility / Input Monitoring** permission required for global input detection.
- **FR-7.2** If permission is denied, the application shall notify the user and disable tracking gracefully (no crash, no silent failure).

### FR-8 Localization
- **FR-8.1** The application shall support multiple user-facing languages.
  - *Tested by: `test_fr_4_1_language_settings`*
- **FR-8.2** All visible UI text, status messages, and notifications shall be provided through a localization mechanism that allows additional languages to be added without code changes.

## Non-Functional Requirements

### NFR-1 Platform Support
- **NFR-1.1** The application shall run on **macOS** with a native menu-bar experience.

### NFR-2 Performance
- **NFR-2.1** The application shall have minimal impact on system performance (low CPU/memory footprint during idle polling).

### NFR-3 Reliability
- **NFR-3.1** The application shall be stable, avoiding crashes and data loss under normal and abnormal shutdown conditions.

### NFR-4 Privacy
- **NFR-4.1** The application shall record only input *timing* (Active/Idle state). It shall not capture keystroke content, mouse coordinates, or application usage.

### NFR-5 Data Integrity
- **NFR-5.1** The application shall enforce a single running instance.
- **NFR-5.2** On save failure (disk full, unwritable directory, directory deleted mid-session), the application shall retain data in memory, alert the user, and retry without data loss.
  - *Status: **implemented** — `PersistenceManager.save_segments` raises `PersistenceWriteError` on write failure; `ActivityTrackerApp` catches it in `update`/`quit_app`/`force_save`/`optimize_csv`, retains data in memory, alerts the user once per failure episode (SAVE_ERROR_TITLE/SAVE_ERROR_MSG), and clears the alert on the next successful save (retry). Tested by: `test_save_all_days_propagates_write_error_and_retains_memory`.*

## Assumptions
- **A-1 (DST):** Daylight Saving Time transitions are *not handled explicitly*. DST switches occur on weekends outside normal working hours, so their impact on daily/weekly duration calculations is considered negligible. All times are recorded in local wall-clock time.

---

### Changelog vs. v1
- **Removed** old FR-2.1 (start-threshold); dropped proposed FR-4.5 → resolves C-1.
- **Reworked FR-2**: segment-stream model, derived session start/end, Option-A idle bounding, unconditional 24:00 midnight cut, plus new **FR-2.6** (finalize orphaned segment at startup, last-Active timestamp).
- **Added** FR-3.6 (UTF-8/header/per-year rotation), FR-3.7 (omit empty days), FR-3.8, FR-3.9 → resolves C-2, C-3.
- **Added** FR-7 (permissions), FR-8 (localization), NFR-4 (privacy), NFR-5 (integrity) → closes top gaps.
- **Fixed** FR-5.3(a) reference (FR-2.1 → FR-2.2).

### Doc reconciliation (v2, post-implementation)
- **FR-2.4 / FR-3.8 / FR-3.9**: the literal `24:00` day-boundary sentinel is **not** used by the implementation; segments are closed at `23:59:59` and a new one opened at `00:00:00` (second resolution). Spec reworded to match.
- **FR-3.2**: schema now includes `duration_seconds` (precision column the code writes).
- **FR-3.8**: rounding clarified as **floor** (whole minutes), not "round half up".
- **FR-1.5, FR-2.6, NFR-5.2**: now **implemented** (sleep→idle gap detection, last-Active orphan finalization at startup, and write-failure alert/retry). FR-2.5 remains partially implemented (reload yes; full cross-day unsaved-segment recovery still out of scope).
- **Tested-by references** updated to actual test names (`test_session_tracker_tick`, `test_set_locked_true_creates_idle_segment`, `test_day_session_start_and_end`, `test_persistence_manager_save_and_read`).
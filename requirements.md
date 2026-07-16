# ActivityTracker Requirements — v2

A macOS menu-bar application that logs working time based on computer usage. Time is classified as **Active** or **Idle**; locked-screen and system-sleep time count as Idle. The app tracks daily and weekly progress against configurable targets and persists data to local CSV files.

## Functional Requirements

### FR-1 Time Tracking
- **FR-1.1** The application shall continuously track working time and classify it into two states: **Active** and **Idle**.
  - *Tested by: `test_fr_1_1_time_tracking`*
- **FR-1.2** The application shall classify time as **Active** when user input (keyboard/mouse/trackpad) is detected.
  - *Tested by: `test_fr_1_2_active_time`*
- **FR-1.3** The application shall classify time as **Idle** when no user input has occurred for a configurable inactivity threshold (see FR-4.2).
  - *Tested by: `test_fr_1_3_idle_time`*
- **FR-1.4** The application shall classify time as **Idle** whenever the screen is locked, regardless of the inactivity threshold.
  - *Tested by: `test_fr_1_4_locked_screen_is_idle`*
- **FR-1.5** The application shall classify the entire duration of a **system sleep** interval as **Idle**, consistent with locked-screen handling (FR-1.4).

### FR-2 Session Management
- **FR-2.1** The application shall track each day as a continuous sequence of segments, each classified as **Active** or **Idle** (per FR-1). Locked-screen and system-sleep intervals shall always be recorded as Idle.
- **FR-2.2** The **session start** for a day shall be the start timestamp of the first Active segment of that day (local time); the **session end** shall be the end timestamp of the last Active segment of that day.
  - *Tested by: `test_fr_2_2_session_start_and_end`*
- **FR-2.3** Idle time shall be counted only within the daily working window (between session start and session end); time outside this window is untracked.
- **FR-2.4** All segments (Active and Idle) shall be bounded by the calendar day. Any segment open at the day boundary shall be closed at end-of-day, modeled and written as **24:00 (local time)** in the HH:MM log; a new segment of the same state shall be opened at **00:00 (local time)** for the new day. No segment shall span more than one date.
- **FR-2.5** The application shall recover unsaved segment data from a previous run if it did not shut down correctly.
- **FR-2.6** At application startup, any segment left open by a previous run (abnormal shutdown, crash, or forced quit) shall be finalized. Its end timestamp shall be set to the last known Active timestamp prior to shutdown; the intervening gap shall remain untracked. If the orphaned segment crosses a day boundary, the FR-2.4 midnight cut shall apply before finalization.

### FR-3 Data Persistence
- **FR-3.1** All tracked time data shall be saved to local CSV files.
  - *Tested by: `test_fr_3_data_persistence`*
- **FR-3.2** The application shall maintain a **segment-level log** (one row per Active/Idle segment) using the schema: `date (YYYY-MM-DD), state, start (HH:MM), end (HH:MM), duration_min`.
- **FR-3.3** The application shall maintain a **daily-summary log** (one row per day) in a **separate file**, using the schema: `date (YYYY-MM-DD), active_min, idle_min, session_start (HH:MM), session_end (HH:MM)`.
- **FR-3.4** Data shall be saved automatically at user-configurable intervals (see FR-4.3).
- **FR-3.5** Data shall be saved automatically when the application is quit.
- **FR-3.6** CSV files shall be **UTF-8** encoded, **comma-delimited**, and include a **header row**. Each log type shall be written to its own file, rotated **per calendar year** (e.g., `segments-2026.csv`, `daily-2026.csv`).
- **FR-3.7** Days with no recorded activity shall be **omitted** (no zero row) from both logs.
- **FR-3.8** Segment start/end shall be stored at minute resolution (HH:MM). The day-boundary close shall be written as **24:00** and the next segment opened at **00:00**, so that segment durations are continuous across midnight. The sum of segment durations for a day shall equal `active_min + idle_min` with no gaps or overlaps. Rounding shall be applied consistently (round half up).
- **FR-3.9** The value `24:00` shall appear only as a segment end (day-boundary close) and shall be interpreted as `00:00` of the following day by any consumer of the CSV (dashboard, import, analysis).

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

## Assumptions
- **A-1 (DST):** Daylight Saving Time transitions are *not handled explicitly*. DST switches occur on weekends outside normal working hours, so their impact on daily/weekly duration calculations is considered negligible. All times are recorded in local wall-clock time.

---

### Changelog vs. v1
- **Removed** old FR-2.1 (start-threshold); dropped proposed FR-4.5 → resolves C-1.
- **Reworked FR-2**: segment-stream model, derived session start/end, Option-A idle bounding, unconditional 24:00 midnight cut, plus new **FR-2.6** (finalize orphaned segment at startup, last-Active timestamp).
- **Added** FR-3.6 (UTF-8/header/per-year rotation), FR-3.7 (omit empty days), FR-3.8, FR-3.9 → resolves C-2, C-3.
- **Added** FR-7 (permissions), FR-8 (localization), NFR-4 (privacy), NFR-5 (integrity) → closes top gaps.
- **Fixed** FR-5.3(a) reference (FR-2.1 → FR-2.2).
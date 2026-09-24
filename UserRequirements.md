# ActivityTracker UserRequirements — v2

A macOS menu-bar application that logs working time based on computer usage. Time is classified as **Active** or **Idle**; a locked screen forces Idle, while system-sleep intervals are inferred heuristically from polling gaps (see FR-1.5). The app tracks daily and weekly progress against configurable targets and persists data to local CSV files.

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
  - *Status: **partially implemented** — `SessionTracker.on_tick` infers sleep from a gap greater than 60 seconds, but records the gap as Idle only when the OS reports the user as active at wake (`idle_time <= idle_threshold`). If the user is still idle at wake, the gap may instead be assigned to the state that was active before the gap. There is no native sleep/wake event integration. Tested by: `test_on_tick_records_sleep_gap_as_idle`, `test_on_tick_no_false_sleep_gap_for_normal_interval`.*

### FR-2 Session Management
- **FR-2.1** The application shall track each day as a continuous sequence of segments, each classified as **Active** or **Idle** (per FR-1). Locked-screen and system-sleep intervals shall always be recorded as Idle.
- **FR-2.2** The **session start** for a day shall be the start timestamp of the first Active segment of that day (local time); the **session end** shall be the end timestamp of the last Active segment of that day.
  - *Tested by: `test_day_session_start_and_end`*
- **FR-2.3** Idle time shall be counted only within the daily working window (between session start and session end); time outside this window is untracked.
  - *Status: **implemented** — `PersistenceManager._filter_idle_boundary_segments` drops Idle segments ending at or before the first Active start and Idle segments starting at or after the last Active end. Idle intervals between Active intervals (e.g. a lunch break) are preserved. Tested by: `test_filter_idle_boundary_segments_filters_before_first_active`, `test_filter_idle_boundary_segments_filters_after_last_active`, `test_save_segments_does_not_write_short_idle_rows`.*
- **FR-2.4** All segments (Active and Idle) shall be bounded by the calendar day. Any segment open at the day boundary shall be closed at the **last second of the day (`23:59:59`, second resolution)** and a new segment of the same state shall be opened at **`00:00:00`** for the new day. No segment shall span more than one date. (See FR-3.8/FR-3.9 for the exact representation.)
- **FR-2.5** The application shall reload segment data for the current day from the local log at startup so tracking continues without data loss.
  - *Status: implemented partially — `SessionTracker.load_current_day_segments()` repopulates the current day from the activities log. Full cross-day crash recovery of unsaved segments is **not** implemented.*
- **FR-2.6** At application startup, any segment left open (end_time is empty) by a previous run shall be finalized at the last known successful write time so time during the unobserved shutdown interval is not credited. If no write time is available, it shall be closed at its start time.
  - *Status: **implemented** — `SessionTracker.load_current_day_segments` finalizes orphaned open segments using the timestamp persisted by `PersistenceManager.save_last_segment_write` / `read_last_segment_write`; without a timestamp it closes them at their start. In-process optimization reloads preserve the live segment rather than treating it as an orphan. Tested by: `test_session_tracker_load_finalizes_orphaned_open_segment`, `test_optimize_csv_preserves_live_segment_continuity`.*

### FR-3 Data Persistence
- **FR-3.1** All tracked time data shall be saved to local CSV files.
  - *Tested by: `test_persistence_manager_save_and_read`*
- **FR-3.2** The application shall maintain a **segment-level log** using the schema: `date (YYYY-MM-DD), state, start (HH:MM:SS), end (HH:MM:SS), duration_min, duration_seconds`. Rows are persisted/optimized segments; consecutive same-state intervals within the configured merge threshold may be combined, and idle intervals outside the active working window are filtered.
- **FR-3.3** Per-day and per-week active/idle totals shall be **derived from the segment-level log** (no separate summary file). Exact seconds are summed per state per day and each state total is rounded to the nearest whole minute, with half minutes rounded up. Older rows without usable `duration_seconds` may fall back to `duration_min`; days without records return zero.
- **FR-3.4** Data shall be saved automatically at user-configurable intervals (see FR-4.3).
- **FR-3.5** Data shall be saved automatically when the application is quit.
- **FR-3.6** CSV files shall be **UTF-8** encoded, **comma-delimited**, and include a **header row**. The segment log shall be written to its own file, rotated **per calendar year** (e.g., `activities-2026.csv`).
- **FR-3.7** Days with no recorded activity shall contribute **zero** active/idle minutes to the derived daily summary (no explicit row is stored).
- **FR-3.8** Segment start/end shall be stored at second resolution (`HH:MM:SS`) and segments shall not span calendar dates. A segment open at the day boundary is closed at `23:59:59`; a segment of the same state begins at `00:00:00` on the next day. The daily stream shall contain no artificial gaps or overlaps. Per-state daily totals are rounded to the nearest whole minute after summing exact seconds, with half minutes rounded up.
  - *Implementation note: because segment durations use end-minus-start arithmetic, the current `23:59:59`/`00:00:00` representation leaves one second uncounted at each midnight boundary. This is a known deviation from the no-gaps requirement.*
- **FR-3.9** Each CSV row's `date` identifies the calendar day of its segment start. Consumers shall use this field to assign a segment to a day; the implementation does not use a `24:00` sentinel, and segments are split at midnight.
- **FR-3.10** The application shall automatically compact the segment log after every successful save. Consecutive same-state segments separated by a gap no larger than the configured idle threshold shall be merged into a single row; a short Idle gap between Active intervals may be absorbed into the surrounding Active interval. Compaction shall never merge across a calendar-day boundary and shall never create a row with `end` earlier than `start`, even if the existing file contains overlapping rows. Compaction shall not interrupt the currently tracked segment.
  - *Status: **implemented** — `ActivityTrackerApp.optimize_csv` (automatic; runs after each successful save) and `PersistenceManager.merge_segments_to_save`. Tested by: `test_optimize_csv_merges_and_reports`, `test_merge_segments_to_save_merges_same_day_small_gap`, `test_merge_segments_to_save_keeps_large_gap`, `test_merge_segments_to_save_does_not_cross_midnight`, `test_merge_segments_to_save_handles_overlap_no_negative_duration`, `test_optimize_csv_preserves_live_segment_continuity`.*
- **FR-3.11** Reading the segment log shall tolerate malformed or legacy rows. Rows missing `date`, `state`, or `start`, and rows with unparseable times or durations, shall be skipped individually without aborting the read or discarding valid rows. Rows written before the `duration_seconds` column existed shall fall back to `duration_min`.
  - *Status: **implemented** — `PersistenceManager._day_totals_for_year`, `read_segments_for_day`, and `save_segments` all skip unusable rows and migrate `duration_min` to `duration_seconds`. Tested by: `test_readers_tolerate_missing_state_column`, `test_readers_skip_malformed_rows_but_keep_valid_ones`, `test_save_segments_skips_rows_missing_date_or_start`, `test_read_segments_skips_malformed_rows`, `test_save_segments_legacy_migration_adds_duration_seconds`, `test_optimize_csv_skips_missing_column_rows`.*

### FR-4 Configuration
- **FR-4.1** The user shall be able to set **daily** and **weekly** targets for active time.
  - *Tested by: `test_set_target`, `test_set_weekly_target`*
- **FR-4.2** The user shall be able to configure the inactivity duration that qualifies as **idle**.
  - *Tested by: `test_set_idle_threshold`*
- **FR-4.3** The user shall be able to configure the auto-save interval.
  - *Tested by: `test_set_save_interval`*
- **FR-4.4** The user shall be able to specify the directory where the data files are stored.
  - *Tested by: `test_select_data_folder`, `test_reset_data_folder`*
- **FR-4.5** Configuration shall persist across restarts in a local JSON file (`activity_tracker_config.json`), storing at least the daily target, weekly target, idle threshold, save interval, locale, and data directory. A missing or unreadable configuration shall fall back to defaults instead of failing.
  - *Tested by: `test_save_and_load_config_roundtrip`, `test_load_config_missing_returns_empty`, `test_load_config_invalid_json_returns_empty`, `test_set_data_dir_persist_survives_reload`.*

### FR-5 User Interface (Menu Bar)
- **FR-5.1** The application shall provide a macOS menu bar (status bar) icon.
- **FR-5.2** The icon shall indicate current status via visual state: **red** while idle, **green** when the daily or weekly target is met, **yellow** otherwise. The menu title shall additionally show a text indicator (`⏸️` idle, `✅` daily target met, `🟢` at least halfway to the weekly target, `⏱️` otherwise) followed by today's active time in `hh:mm`.
- **FR-5.3** The menu shall display **daily** statistics for the current day, including:
  - (a) the **session start time** (per FR-2.2);
  - (b) the current **Active time vs. daily target** (per FR-4.1), rendered as a progress bar with `current │bar│ target`;
  - (c) the accumulated **Idle time**.
- **FR-5.4** The menu shall display **weekly** statistics for the current week (**week starts Monday 00:00 local time**), including:
  - (a) the current **Active time vs. weekly target** (per FR-4.1), rendered as a progress bar with `current │bar│ target`;
  - (b) the accumulated **weekly Idle time**.
- **FR-5.5** The menu shall provide actions to: (a) force an immediate save, (b) open the data file folder, (c) quit the application.
- **FR-5.6** All time values displayed in the UI shall use the `hh:mm` format, with **session start time shown on a 24-hour clock** (e.g., `08:30`) and **durations shown with uncapped hours** (e.g., `40:00` for 40 hours).
- **FR-5.7** The menu shall provide a **report** listing daily statistics for the current day and the six preceding days. Each entry shall show the date, first Active start, last Active end, total Active time, total Idle time, and productivity (Active / (Active + Idle)). Days with no Active segments shall be omitted; if no day has activity the report shall say so.
  - *Status: **implemented** — `AppMenu._generate_report_menu`. Tested by: `test_report_menu_day_includes_statistics`, `test_report_menu_omits_days_without_activity`, `test_report_menu_shows_no_activity_message_when_empty`.*
- **FR-5.8** The menu shall display the application version (and bundle build date when available) in a read-only item.
  - *Status: **implemented** — `AppMenu._generate_general_settings_menu` via `PlatformABC.get_bundle_version` / `get_bundle_build_date`. Tested by: `test_general_settings_menu_shows_version`.*
- **FR-5.9** The menu shall expose settings for daily target, weekly target, idle threshold, and save interval. Each shall offer preset choices and a custom numeric entry, and shall visually mark the currently active value.
  - *Status: **implemented** — `AppMenu._create_daily_settings_submenu`, with native slider dialogs where supported. Tested by: `test_set_target`, `test_set_weekly_target`, `test_set_idle_threshold`, `test_set_save_interval`.*

### FR-6 Autostart
- **FR-6.1** The user shall be able to configure the application to launch automatically on system startup (macOS Login Items).
  - *Status: **implemented on macOS** using a per-user `launchd` LaunchAgent. `tests/test_platform_macos.py::test_launch_agent_plist_is_written` covers plist creation; `test_fr_6_autostart` is only a placeholder, not a functional test.*

### FR-7 Permissions (macOS)
- **FR-7.1** The application shall request the macOS **Accessibility / Input Monitoring** permission required for global input detection.
  - *Status: **not implemented** — the app does not currently perform a permission check or show a permission-specific request.*
- **FR-7.2** If permission is denied, the application shall notify the user and disable tracking gracefully (no crash, no silent failure).
  - *Status: **not implemented** — idle-time API failures fall back to `0.0`, which is interpreted as active time; there is no permission-specific notification or tracking disablement.*

### FR-8 Localization
- **FR-8.1** The application shall support multiple user-facing languages.
  - *Tested by: `test_set_language`*
- **FR-8.2** All visible UI text, status messages, and notifications shall be provided through a localization mechanism that allows additional languages to be added without code changes.
  - *Status: **implemented** — user-facing strings live in per-language JSON files (`locales/en.json`, `locales/de.json`) loaded by `activitytracker/i18n.py`. Adding a language requires only a new translation file.*
- **FR-8.3** The language shall be selectable at runtime without restarting the application. With no explicit choice the application shall follow the system locale, falling back to English when no translation is available.
  - *Status: **implemented** — `AppMenu` language menu calls `ActivityTrackerApp.set_language`; `i18n._get_system_locale` probes environment variables, the stdlib locale, then the platform API. Tested by: `test_set_language`.*

## Non-Functional Requirements

### NFR-1 Platform Support
- **NFR-1.1** The application shall run on **macOS** with a native menu-bar experience.
- **NFR-1.2** The application shall be a **menu-bar only** application: it shall not show a Dock icon or a main window. The macOS bundle declares `LSUIElement = true`.
- **NFR-1.3** The application shall run on macOS 10.15 or later.

### NFR-2 Performance
- **NFR-2.1** The application shall have minimal impact on system performance (low CPU/memory footprint during idle polling).
  - *Status: **implemented** — polling runs on a background thread with a 10-second interval; idle-time readings and tray icons are cached (`MacOSPlatform.IDLE_CACHE_TTL`, `tray_icon.create_icon` LRU cache).*
- **NFR-2.2** Per-day and per-week totals shown in the UI shall be derived from cached per-year aggregates rather than re-parsing the CSV on every UI update. The cache shall be invalidated when the log is rewritten and bounded so only recent years are retained.
  - *Status: **implemented** — `PersistenceManager._day_totals_for_year` / `_cache_year_totals` (bounded by `MAX_CACHED_YEARS`), invalidated by `save_segments` and `optimize_csv`. Tested by: `test_totals_cache_is_bounded_to_recent_years`.*

### NFR-3 Reliability
- **NFR-3.1** The application shall be stable, avoiding crashes and data loss under normal and abnormal shutdown conditions.
  - *Status: **partially implemented** — corrupted log rows are skipped (FR-3.11) and read failures return empty results instead of raising, but several fallbacks still report zero activity rather than raising a user-visible error.*
- **NFR-3.2** Tracking and automatic saving shall continue while the screen is locked; the sampled state is forced to Idle for the locked interval and resumes normally on unlock.
  - *Status: **implemented** — `ActivityTrackerApp._update_loop` keeps polling and saving while locked; `SessionTracker.set_locked` forces Idle. Tested by: `test_update_loop_continues_saving_while_screen_is_locked`, `test_set_locked_true_creates_idle_segment`.*

### NFR-4 Privacy
- **NFR-4.1** The application shall record only input *timing* (Active/Idle state). It shall not capture keystroke content, mouse coordinates, or application usage.

### NFR-5 Data Integrity
- **NFR-5.1** The application shall enforce a single running instance.
  - *Status: **implemented** — `SingleInstanceLock` takes an exclusive `fcntl` lock on a runtime lock file; a second launch shows an alert and exits. Tested by: `test_second_instance_is_blocked`, `test_acquire_and_release`.*
- **NFR-5.2** On save failure (disk full, unwritable directory, directory deleted mid-session), the application shall retain data in memory, alert the user, and retry without data loss.
  - *Status: **partially implemented** — `PersistenceManager.save_segments` raises `PersistenceWriteError` on write failure and `SessionTracker.save_all_days` restores open segments for retry. Automatic failures alert once per failure episode; user-initiated saves always alert. Data-folder changes are cancelled if saving the current session fails. However, quitting after a save failure still stops the app, so unsaved in-memory data cannot be retried after exit. Tested by: `test_save_all_days_propagates_write_error_and_retains_memory`, `test_force_save_reports_persistence_failure`, `test_select_data_folder_aborts_if_save_fails`, `test_reset_data_folder_aborts_if_save_fails`.*
- **NFR-5.3** An unreadable, truncated, or manually edited log file shall not crash the application or lose unrelated valid rows. Reads return what is usable; writes preserve existing valid rows and only skip entries that cannot be identified.
  - *Status: **implemented** — see FR-3.11. Tested by: `test_readers_survive_unreadable_log_file`, `test_read_segments_for_day_path_is_a_directory`, `test_save_segments_skips_rows_missing_date_or_start`.*

## Assumptions
- **A-1 (DST):** Daylight Saving Time transitions are *not handled explicitly*. DST switches occur on weekends outside normal working hours, so their impact on daily/weekly duration calculations is considered negligible. All times are recorded in local wall-clock time.

---

### Changelog vs. v1
- **Removed** old FR-2.1 (start-threshold); dropped the proposed v1 FR-4.5 → resolves C-1. (A different FR-4.5, covering configuration persistence, was added later under "Requirements added from implemented behaviour".)
- **Reworked FR-2**: segment-stream model, derived session start/end, idle boundary filtering, second-resolution midnight split, plus new **FR-2.6** (finalize orphaned segments at startup using the last successful write time).
- **Added** FR-3.6 (UTF-8/header/per-year rotation), FR-3.7 (omit empty days), FR-3.8, FR-3.9 → resolves C-2, C-3.
- **Added** FR-7 (permissions), FR-8 (localization), NFR-4 (privacy), NFR-5 (integrity) → closes top gaps.
- **Fixed** FR-5.3(a) reference (FR-2.1 → FR-2.2).

### Doc reconciliation (v2, post-implementation)
- **FR-2.4 / FR-3.8 / FR-3.9**: the literal `24:00` day-boundary sentinel is **not** used by the implementation; segments are closed at `23:59:59` and a new one opened at `00:00:00` (second resolution). Spec reworded to match.
- **FR-3.2**: schema now includes `duration_seconds` (precision column the code writes).
- **FR-3.8**: rounding clarified as nearest whole minute, with half minutes rounded up; the one-second midnight boundary gap is documented.
- **FR-1.5** is partially implemented (heuristic sleep-gap detection); **FR-2.6** and **NFR-5.2** are implemented (orphan finalization at startup and write-failure retention/alert/retry). FR-2.5 remains partially implemented (current-day reload; full cross-day unsaved-segment recovery is not implemented).
- **Tested-by references** updated to actual test names (`test_session_tracker_tick`, `test_set_locked_true_creates_idle_segment`, `test_day_session_start_and_end`, `test_persistence_manager_save_and_read`).

### Requirements added from implemented behaviour
Requirements below document behaviour that already exists in the code but was not covered by the original spec.
- **FR-3.10** automatic log compaction after each successful save.
- **FR-3.11** malformed/legacy row tolerance and `duration_min` fallback.
- **FR-4.5** JSON configuration persistence with safe defaults.
- **FR-5.2 / FR-5.3 / FR-5.4** precise status-icon and progress-bar presentation.
- **FR-5.7** seven-day report menu.
- **FR-5.8** version display.
- **FR-5.9** settings presets, custom entry, and active-value marking.
- **FR-8.3** runtime language switching and system-locale detection.
- **NFR-1.2 / NFR-1.3** menu-bar-only bundle and macOS 10.15 minimum.
- **NFR-2.1 / NFR-2.2** polling/caching performance measures.
- **NFR-3.2** tracking continues while the screen is locked.
- **NFR-5.1 / NFR-5.3** single-instance lock and corrupt-log resilience (statuses added).

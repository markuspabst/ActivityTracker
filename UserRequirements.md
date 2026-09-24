# ActivityTracker User Requirements

A macOS menu-bar app that classifies computer-use time as **Active** or **Idle**, tracks daily and weekly targets, and stores segment data in CSV files. A locked screen forces Idle; sleep detection is heuristic (FR-1.5).

## Functional Requirements

### FR-1 Time Tracking
- **FR-1.1** The application shall continuously track working time and classify it into two states: **Active** and **Idle**.
- **FR-1.2** The application shall classify time as **Active** when user input (keyboard/mouse/trackpad) is detected.
- **FR-1.3** The application shall classify time as **Idle** when no user input has occurred for a configurable inactivity threshold (see FR-4.2).
- **FR-1.4** The application shall classify time as **Idle** whenever the screen is locked, regardless of the inactivity threshold.
- **FR-1.5** The application shall classify the entire duration of a **system sleep** interval as **Idle**, consistent with locked-screen handling (FR-1.4).
  - *Partial: sleep is inferred from polling gaps >60 seconds and recorded as Idle only if the user is active at wake. There is no native sleep/wake event integration.*

### FR-2 Session Management
- **FR-2.1** The application shall track each day as a continuous sequence of segments, each classified as **Active** or **Idle** (per FR-1). Locked-screen and system-sleep intervals shall always be recorded as Idle.
- **FR-2.2** The **session start** for a day shall be the start timestamp of the first Active segment of that day (local time); the **session end** shall be the end timestamp of the last Active segment of that day.
- **FR-2.3** Idle time shall be counted only within the daily working window (between session start and session end); time outside this window is untracked.
  - *Implemented: boundary Idle segments are filtered; Idle intervals between Active periods are kept.*
- **FR-2.4** Segments shall be assigned to a day by their start date and cover only that day's interval. The end boundary is exclusive; see FR-3.8.
- **FR-2.5** The application shall reload segment data for the current day from the local log at startup so tracking continues without data loss.
  - *Partial: today's saved data is reloaded; unsaved data from earlier days is not recovered.*
- **FR-2.6** At application startup, any segment left open (end_time is empty) by a previous run shall be finalized at the last known successful write time so time during the unobserved shutdown interval is not credited. If no write time is available, it shall be closed at its start time.
  - *Implemented. In-process optimization reloads preserve the live segment.*

### FR-3 Data Persistence
- **FR-3.1** All tracked time data shall be saved to local CSV files.
- **FR-3.2** The application shall maintain a **segment-level log** with this schema: `date (YYYY-MM-DD), state, start (HH:MM:SS), end (HH:MM:SS), duration_min, duration_seconds`.
- **FR-3.3** Per-day and per-week active/idle totals shall be **derived from the segment-level log** (no separate summary file). Exact seconds are summed per state per day and each state total is rounded to the nearest whole minute, with half minutes rounded up. Older rows without usable `duration_seconds` may fall back to `duration_min`; days without records return zero.
- **FR-3.4** Data shall be saved automatically at user-configurable intervals (see FR-4.3).
- **FR-3.5** Data shall be saved automatically when the application is quit.
- **FR-3.6** CSV files shall be **UTF-8** encoded, **comma-delimited**, and include a **header row**. The segment log shall be written to its own file, rotated **per calendar year** (e.g., `activities-2026.csv`).
- **FR-3.7** Days with no recorded activity shall contribute **zero** active/idle minutes to the derived daily summary (no explicit row is stored).
- **FR-3.8** Segment timestamps shall use second resolution (`HH:MM:SS`) and represent half-open intervals `[start, end)`. At midnight, the prior day's segment ends at the exclusive boundary `00:00:00` on the next date, where the same state may begin its next segment. The day stream shall have no artificial gaps or overlaps.
- **FR-3.9** Each CSV row's `date` identifies the calendar day of its segment start. Consumers shall use this field to assign a segment to a day; the implementation does not use a `24:00` sentinel, and segments are split at midnight.
- **FR-3.10** The application shall automatically compact the segment log after every successful save. Consecutive same-state segments separated by a gap no larger than the configured idle threshold shall be merged into a single row; a short Idle gap between Active intervals may be absorbed into the surrounding Active interval. Compaction shall never merge across a calendar-day boundary and shall never create a row with `end` earlier than `start`, even if the existing file contains overlapping rows. Compaction shall not interrupt the currently tracked segment.
  - *Implemented after successful saves; compaction preserves the live segment.*
- **FR-3.11** Reading the segment log shall tolerate malformed and legacy rows without aborting or discarding valid rows. Rows missing required fields or with unparseable timestamps shall be skipped. Invalid or absent `duration_seconds` shall fall back to `duration_min`, then zero if neither parses.
  - *Implemented: unusable rows are skipped; invalid `duration_seconds` falls back to `duration_min`, then zero if neither parses.*

### FR-4 Configuration
- **FR-4.1** The user shall be able to set **daily** and **weekly** targets for active time.
- **FR-4.2** The user shall be able to configure the inactivity duration that qualifies as **idle**.
- **FR-4.3** The user shall be able to configure the auto-save interval.
- **FR-4.4** The user shall be able to specify the directory where the data files are stored.
- **FR-4.5** Configuration shall persist across restarts in a local JSON file (`activity_tracker_config.json`), storing at least the daily target, weekly target, idle threshold, save interval, locale, and data directory. A missing or unreadable configuration shall fall back to defaults instead of failing.
  - *Implemented in `activity_tracker_config.json`; missing or invalid files fall back to defaults.*

### FR-5 User Interface (Menu Bar)
- **FR-5.1** The application shall provide a macOS menu bar (status bar) icon.
- **FR-5.2** The icon shall be **red** while idle, **green** when either target is met, and **yellow** otherwise. The menu title shall show an idle, daily-target, halfway-weekly-target, or default indicator followed by today's active time.
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
  - *Implemented.*
- **FR-5.8** The menu shall display the application version in a read-only item.
  - *Implemented; bundled version is used when available, otherwise the package version.*
- **FR-5.9** The menu shall expose settings for daily target, weekly target, idle threshold, and save interval. Each shall offer preset choices and a custom numeric entry, and shall visually mark the currently active value.
  - *Implemented; custom dialogs are available on macOS.*

### FR-6 Autostart
- **FR-6.1** The user shall be able to configure the application to launch automatically on system startup (macOS Login Items).
  - *Implemented on macOS with a per-user `launchd` LaunchAgent.*

### FR-7 Idle Detection Reliability
- **FR-7.1** If the primary OS idle-time API fails or returns an invalid value, the application shall try a secondary OS-provided source. If neither gives a valid sample, detection shall be marked unavailable.
  - *Implemented on macOS using Quartz with an `ioreg` fallback; other platforms without a detector report unavailable.*
- **FR-7.2** When idle detection is unavailable, the application shall notify the user, stop accumulating time at the last valid sample, and resume when detection recovers. It shall not count unknown time as Active.
  - *Implemented; the warning is shown once per failure episode and unobserved time is excluded.*

### FR-8 Localization
- **FR-8.1** The application shall support multiple user-facing languages.
- **FR-8.2** All visible UI text, status messages, and notifications shall be provided through a localization mechanism that allows additional languages to be added without code changes.
  - *Implemented with per-language JSON translation files.*
- **FR-8.3** The language shall be selectable at runtime without restarting the application. With no explicit choice the application shall follow the system locale, falling back to English when no translation is available.
  - *Implemented.*

## Non-Functional Requirements

### NFR-1 Platform Support
- **NFR-1.1** The application shall run on **macOS** with a native menu-bar experience.
- **NFR-1.2** The application shall be a **menu-bar only** application: it shall not show a Dock icon or a main window.

### NFR-2 Performance
- **NFR-2.1** The application shall have minimal impact on system performance (low CPU/memory footprint during idle polling).
- **NFR-2.2** Per-day and per-week totals shall use cached per-year aggregates, invalidated after log rewrites and bounded to recent years.
  - *Implemented.*

### NFR-3 Reliability
- **NFR-3.1** The application shall be stable and avoid crashes or data loss during normal use and abnormal shutdowns.
  - *Partial: save failures during quit cannot be retried after the application exits; see NFR-5.2.*
- **NFR-3.2** Tracking and automatic saving shall continue while the screen is locked. The tracked state shall be Idle until unlock.

### NFR-4 Privacy
- **NFR-4.1** The application shall record only input *timing* (Active/Idle state). It shall not capture keystroke content, mouse coordinates, or application usage.

### NFR-5 Data Integrity
- **NFR-5.1** The application shall enforce a single running instance.
  - *Implemented with an exclusive runtime lock file.*
- **NFR-5.2** On save failure (disk full, unwritable directory, directory deleted mid-session), the application shall retain data in memory, alert the user, and retry without data loss.
  - *Partial: failed saves retain data and retry while the app is running; automatic failures alert once per episode, manual saves always alert, and folder changes abort. Quitting after a save failure still exits, so in-memory data cannot then be retried.*
- **NFR-5.3** An unreadable, truncated, or manually edited log file shall not crash the application or lose unrelated valid rows. Reads return what is usable; writes preserve existing valid rows and only skip entries that cannot be identified.
  - *Implemented; see FR-3.11.*

## Assumptions
- **A-1 (DST):** Daylight Saving Time transitions are *not handled explicitly*. DST switches occur on weekends outside normal working hours, so their impact on daily/weekly duration calculations is considered negligible. All times are recorded in local wall-clock time.

## Test References

References point to automated tests under `tests/`. “Not covered” means no direct automated test currently exists.

| Requirement | Test reference |
|---|---|
| FR-1.1 | `test_tracking.py::test_session_tracker_tick` |
| FR-1.2 | `test_tracking.py::test_session_tracker_tick` |
| FR-1.3 | `test_tracking.py::test_session_tracker_tick` |
| FR-1.4 | `test_tracking_config.py::test_set_locked_true_creates_idle_segment` |
| FR-1.5 | `test_tracking.py::test_on_tick_records_sleep_gap_as_idle`, `test_on_tick_no_false_sleep_gap_for_normal_interval` |
| FR-2.1 | `test_tracking.py::test_daily_logging_complete_segment`, `test_tracking_config.py::test_set_locked_true_creates_idle_segment` |
| FR-2.2 | `test_models.py::test_day_session_start_and_end` |
| FR-2.3 | `test_persistence_csv.py::test_filter_idle_boundary_segments_filters_before_first_active`, `test_filter_idle_boundary_segments_filters_after_last_active`, `test_filter_idle_boundary_segments_preserves_between_active` |
| FR-2.4 | `test_tracking.py::test_session_tracker_midnight_rollover`, `test_midnight_rollover_splits_before_state_transition` |
| FR-2.5 | `test_tracking.py::test_session_tracker_load_current_day_segments_clean_start` |
| FR-2.6 | `test_tracking.py::test_session_tracker_load_finalizes_orphaned_open_segment`, `test_session_tracker_load_orphaned_segment_when_last_write_is_none` |
| FR-3.1 | `test_tracking.py::test_persistence_manager_save_and_read` |
| FR-3.2 | `test_persistence_csv.py::test_save_segments_writes_header_and_rows`, `test_save_segments_splits_by_year` |
| FR-3.3 | `test_persistence_csv.py::test_get_minutes_for_date_aggregates_exact_seconds_before_rounding`, `test_get_weekly_minutes_sums_days_from_activities_log` |
| FR-3.4 | `test_app.py::test_update_triggers_save_when_interval_elapsed` |
| FR-3.5 | `test_tracking_config.py::test_finalize_session_sets_end_time_and_saves` |
| FR-3.6 | `test_persistence_csv.py::test_save_segments_writes_header_and_rows`, `test_save_segments_splits_by_year` |
| FR-3.7 | `test_persistence_csv.py::test_get_minutes_for_date_missing_file`, `test_get_weekly_minutes_missing_file` |
| FR-3.8 | `test_tracking.py::test_midnight_rollover_splits_before_state_transition`, `test_persistence_csv.py::test_read_segments_roundtrips_exclusive_midnight_end`, `test_app.py::test_optimize_csv_preserves_exclusive_midnight_end` |
| FR-3.9 | `test_persistence_csv.py::test_save_segments_splits_by_year`, `test_read_segments_only_target_day` |
| FR-3.10 | `test_app.py::test_optimize_csv_merges_and_reports`, `test_merge_segments_to_save_does_not_cross_midnight`, `test_optimize_csv_preserves_live_segment_continuity` |
| FR-3.11 | `test_persistence_csv.py::test_readers_tolerate_missing_state_column`, `test_readers_skip_malformed_rows_but_keep_valid_ones`, `test_save_segments_skips_rows_missing_date_or_start` |
| FR-4.1 | `test_app.py::test_set_target`, `test_set_weekly_target` |
| FR-4.2 | `test_app.py::test_set_idle_threshold` |
| FR-4.3 | `test_app.py::test_set_save_interval`, `test_app.py::test_update_triggers_save_when_interval_elapsed` |
| FR-4.4 | `test_app.py::test_select_data_folder`, `test_reset_data_folder` |
| FR-4.5 | `test_tracking_config.py::test_save_and_load_config_roundtrip`, `test_load_config_missing_returns_empty`, `test_load_config_invalid_json_returns_empty` |
| FR-5.1 | `test_app.py::test_app_menu_creates_status_icon`, `test_tray_icon.py::test_create_icon_returns_rgba_image` (native macOS integration not covered) |
| FR-5.2 | `test_tray_icon.py::test_get_status_icon_idle`, `test_get_status_icon_active_daily_goal_met`, `test_get_status_icon_active_weekly_goal_met`, `test_get_status_icon_active_neither_goal_met` |
| FR-5.3 | `test_app.py::test_update_ui_computes_and_calls_menu` |
| FR-5.4 | `test_tracking.py::test_weekly_logging_multiple_days`, `test_weekly_logging_with_ongoing_segment_today` |
| FR-5.5 | `test_app.py::test_force_save`, `test_select_data_folder`, `test_quit_app`, `test_open_data_folder_menu_action_uses_configured_directory` |
| FR-5.6 | `test_tracking.py::test_format_hours` |
| FR-5.7 | `test_app.py::test_report_menu_day_includes_statistics`, `test_report_menu_omits_days_without_activity`, `test_report_menu_shows_no_activity_message_when_empty` |
| FR-5.8 | `test_app.py::test_general_settings_menu_shows_version` |
| FR-5.9 | `test_app.py::test_set_target`, `test_set_weekly_target`, `test_set_idle_threshold`, `test_set_save_interval` |
| FR-6.1 | `test_platform_macos.py::test_launch_agent_plist_is_written` |
| FR-7.1 | `test_platform_macos.py::test_get_idle_time_uses_ioreg_when_quartz_fails`, `test_get_idle_time_returns_none_when_all_sources_fail` |
| FR-7.2 | `test_app.py::test_idle_detection_failure_pauses_and_alerts_once_then_resumes`, `test_tracking.py::test_pause_tracking_closes_at_last_valid_sample_and_resumes_cleanly` |
| FR-8.1 | `test_i18n.py::test_available_locales_includes_en_and_de`, `test_set_locale_german` |
| FR-8.2 | `test_i18n.py::test_set_locale_english_and_translate`, `test_set_locale_german` |
| FR-8.3 | `test_app.py::test_set_language`, `test_i18n.py::test_get_system_locale_from_env`, `test_get_system_locale_default_when_unset`, `test_get_system_locale_via_platform`, `test_set_locale_falls_back_to_english_for_unknown` |
| NFR-1.1 | Not covered by an automated macOS integration test |
| NFR-1.2 | Not covered by an automated bundle-configuration test |
| NFR-1.3 | `test_requirements.py::test_macos_bundle_minimum_version_is_10_15` (configuration only; OS compatibility not run on macOS 10.15) |
| NFR-2.1 | Not covered by an automated performance benchmark |
| NFR-2.2 | `test_persistence_csv.py::test_totals_cache_is_bounded_to_recent_years` |
| NFR-3.1 | `test_tracking.py::test_failed_save_keeps_current_segment_open_and_tracking_advances`, `test_session_tracker_load_finalizes_orphaned_open_segment` |
| NFR-3.2 | `test_app.py::test_update_loop_continues_saving_while_screen_is_locked`, `test_tracking_config.py::test_set_locked_true_creates_idle_segment` |
| NFR-4.1 | Not covered by an automated privacy test |
| NFR-5.1 | `test_single_instance.py::test_second_instance_is_blocked`, `test_acquire_and_release` |
| NFR-5.2 | `test_tracking.py::test_save_all_days_propagates_write_error_and_retains_memory`, `test_finalize_session_keeps_live_segment_open_when_save_fails`, `test_app.py::test_force_save_reports_persistence_failure`, `test_quit_app_stays_running_if_final_save_fails`, `test_select_data_folder_aborts_if_save_fails`, `test_reset_data_folder_aborts_if_save_fails` |
| NFR-5.3 | `test_persistence_csv.py::test_readers_survive_unreadable_log_file`, `test_read_segments_skips_malformed_rows`, `test_save_segments_skips_rows_missing_date_or_start` |

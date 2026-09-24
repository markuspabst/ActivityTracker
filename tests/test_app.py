"""Tests for the application controller (app.py).

The platform and persistence/config side effects are mocked so the controller
logic can be exercised without a real UI, filesystem config dir, or platform APIs.
"""

from datetime import datetime, date, timedelta
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from activitytracker import app as app_module
from activitytracker import i18n
from activitytracker import tracking
from activitytracker.models import TimeSegment, Day
from activitytracker.app import ActivityTrackerApp


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "get_platform", lambda: MagicMock())
    monkeypatch.setattr(app_module, "get_configured_data_dir", lambda: str(tmp_path))

    recorded = {}

    def fake_set_config_value(key, value):
        recorded[key] = value

    monkeypatch.setattr(app_module, "set_config_value", fake_set_config_value)

    data_dir_calls = []

    def fake_set_data_dir(path, *args, **kwargs):
        data_dir_calls.append(path)

    monkeypatch.setattr(app_module, "set_data_dir", fake_set_data_dir)

    instance = ActivityTrackerApp()
    instance._recorded = recorded
    instance._data_dir_calls = data_dir_calls
    # menu is only created in run(); tests that need it set it explicitly
    instance.menu = MagicMock()
    return instance


# ------------------------------------------------------------
# Construction
# ------------------------------------------------------------

def test_app_constructs(app):
    assert isinstance(app, ActivityTrackerApp)
    assert isinstance(app.target_work_seconds, int)
    assert isinstance(app.weekly_target_seconds, int)
    assert isinstance(app.idle_threshold, int)
    assert isinstance(app.write_interval, int)


# ------------------------------------------------------------
# Config setters
# ------------------------------------------------------------

def test_set_target(app):
    app.set_target(3600)
    assert app.target_work_seconds == 3600
    assert app._recorded["target_seconds"] == 3600


def test_set_weekly_target(app):
    app.set_weekly_target(40 * 3600)
    assert app.weekly_target_seconds == 40 * 3600
    assert app._recorded["weekly_target_seconds"] == 40 * 3600


def test_set_idle_threshold(app):
    app.set_idle_threshold(120)
    assert app.idle_threshold == 120
    assert app._recorded["idle_threshold_seconds"] == 120


def test_set_save_interval(app):
    app.set_save_interval(120)
    assert app.write_interval == 120
    assert app._recorded["save_interval_seconds"] == 120


def test_set_language(app):
    app.set_language("de")
    assert app._recorded["locale"] == "de"
    assert i18n._lang == "de"


# ------------------------------------------------------------
# Save / update / quit
# ------------------------------------------------------------

def test_force_save(app):
    app.session.save_all_days = MagicMock()
    assert app.force_save() is True
    app.session.save_all_days.assert_called_once()


def test_force_save_reports_persistence_failure(app):
    from activitytracker.persistence import PersistenceWriteError

    # A previous automatic failure may already have shown the episode alert;
    # a manual save attempt must still tell the user this save failed.
    app._save_failure_shown = True
    app.session.save_all_days = MagicMock(side_effect=PersistenceWriteError("disk full"))

    assert app.force_save() is False
    app.platform.show_alert.assert_called_once()


def test_quit_app(app):
    app.session.finalize_session = MagicMock()
    app.menu.stop = MagicMock()
    app.quit_app()
    app.session.finalize_session.assert_called_once()
    app.menu.stop.assert_called_once()
    assert app._running is False


def test_quit_app_stays_running_if_final_save_fails(app):
    from activitytracker.persistence import PersistenceWriteError

    app._running = True
    app._stop_event = MagicMock()
    app.session.finalize_session = MagicMock(side_effect=PersistenceWriteError("disk full"))
    app.menu.stop = MagicMock()

    app.quit_app()

    assert app._running is True
    app._stop_event.set.assert_not_called()
    app.menu.stop.assert_not_called()
    app.platform.show_alert.assert_called_once()


def test_app_menu_creates_status_icon(monkeypatch):
    from activitytracker import activity_tracker_menu as menu_module

    icon_image = object()
    icon_instance = object()
    menu_instance = object()
    icon_factory = MagicMock(return_value=icon_instance)
    menu_factory = MagicMock(return_value=menu_instance)
    monkeypatch.setattr(menu_module, "Icon", icon_factory)
    monkeypatch.setattr(menu_module, "Menu", menu_factory)
    monkeypatch.setattr(menu_module, "create_icon", MagicMock(return_value=icon_image))
    monkeypatch.setattr(menu_module, "get_platform", lambda: MagicMock())
    monkeypatch.setattr(menu_module, "run_on_main_thread", lambda callback, *args: callback(*args))

    menu = menu_module.AppMenu(MagicMock())

    menu_factory.assert_called_once_with(menu._generate_menu_items)
    icon_factory.assert_called_once_with("ActivityTracker", icon_image, "ActivityTracker", menu_instance)
    assert menu.icon is icon_instance


def test_open_data_folder_menu_action_uses_configured_directory(monkeypatch):
    from activitytracker import activity_tracker_menu as menu_module

    i18n.set_locale("en")
    platform = MagicMock()
    monkeypatch.setattr(menu_module, "get_platform", lambda: platform)
    monkeypatch.setattr(menu_module, "run_on_main_thread", lambda callback, *args: callback(*args))
    app = MagicMock()
    app.pm.get_data_dir.return_value = "/tmp/activity-data"

    menu = menu_module.AppMenu(app)
    settings = menu._create_global_settings_submenu()
    folder_entry = next(item for item in settings.items if item.text == i18n.t("DATA_FOLDER"))
    open_folder = next(item for item in folder_entry.submenu.items if item.text == i18n.t("OPEN_DATA_FOLDER"))
    open_folder._action()

    platform.open_file_manager.assert_called_once_with("/tmp/activity-data")


def test_update_loop_continues_saving_while_screen_is_locked(app):
    app._running = True
    app._stop_event = MagicMock()
    app._stop_event.wait.side_effect = [False, True]
    app.platform.is_screen_locked.return_value = True
    app.session.set_locked = MagicMock()
    app.update = MagicMock()

    app._update_loop()

    app.session.set_locked.assert_called_once_with(True)
    app.update.assert_called_once()


def test_update_ui_computes_and_calls_menu(app, monkeypatch):
    D = datetime(2026, 7, 15, 12, 0, 0)
    monkeypatch.setattr(app_module, "datetime", MagicMock(wraps=datetime))
    app_module.datetime.now.return_value = D
    monkeypatch.setattr(tracking, "datetime", MagicMock(wraps=datetime))
    tracking.datetime.now.return_value = D

    today = D.date()
    day = Day(today)
    seg = TimeSegment("active", datetime(2026, 7, 15, 9, 0, 0), datetime(2026, 7, 15, 10, 0, 0))
    day.segments.append(seg)
    app.session.days[today] = day
    app.session.current_segment = seg

    app.pm = MagicMock()
    app.pm.get_weekly_minutes.return_value = (0, 0)
    app.pm.get_minutes_for_date.return_value = (60, 0)
    app.menu.update_ui = MagicMock()

    app.update_ui()

    app.menu.update_ui.assert_called_once()
    args = app.menu.update_ui.call_args[0]
    is_idle, active_today = args[0], args[1]
    assert is_idle is False
    assert active_today == 3600


# ------------------------------------------------------------
# Data folder management
# ------------------------------------------------------------

def test_select_data_folder(app, monkeypatch):
    app.platform.choose_folder_dialog.return_value = "/selected/folder"
    app.force_save = MagicMock()
    app.update_ui = MagicMock()
    app.session.load_current_day_segments = MagicMock()
    clear_last_segment_write = MagicMock()
    monkeypatch.setattr(app_module.PersistenceManager, "clear_last_segment_write", clear_last_segment_write)
    app.select_data_folder()
    app.force_save.assert_called_once()
    assert app._data_dir_calls == ["/selected/folder"]
    clear_last_segment_write.assert_called_once()
    app.session.load_current_day_segments.assert_called_once()
    app.update_ui.assert_called_once()


def test_select_data_folder_aborts_if_save_fails(app, monkeypatch):
    app.platform.choose_folder_dialog.return_value = "/selected/folder"
    app.force_save = MagicMock(return_value=False)
    app._reload_from_current_data_folder = MagicMock()
    clear_last_segment_write = MagicMock()
    monkeypatch.setattr(app_module.PersistenceManager, "clear_last_segment_write", clear_last_segment_write)

    app.select_data_folder()

    app.force_save.assert_called_once()
    assert app._data_dir_calls == []
    clear_last_segment_write.assert_not_called()
    app._reload_from_current_data_folder.assert_not_called()


def test_reset_data_folder(app, monkeypatch):
    app.force_save = MagicMock()
    app.update_ui = MagicMock()
    app.session.load_current_day_segments = MagicMock()
    clear_last_segment_write = MagicMock()
    monkeypatch.setattr(app_module.PersistenceManager, "clear_last_segment_write", clear_last_segment_write)
    mock_reset = MagicMock()
    monkeypatch.setattr(app_module, "reset_data_dir_to_default", mock_reset)
    app.reset_data_folder()
    app.force_save.assert_called_once()
    mock_reset.assert_called_once()
    clear_last_segment_write.assert_called_once()
    app.session.load_current_day_segments.assert_called_once()
    app.update_ui.assert_called_once()


def test_reset_data_folder_aborts_if_save_fails(app, monkeypatch):
    app.force_save = MagicMock(return_value=False)
    app._reload_from_current_data_folder = MagicMock()
    clear_last_segment_write = MagicMock()
    monkeypatch.setattr(app_module.PersistenceManager, "clear_last_segment_write", clear_last_segment_write)
    mock_reset = MagicMock()
    monkeypatch.setattr(app_module, "reset_data_dir_to_default", mock_reset)

    app.reset_data_folder()

    app.force_save.assert_called_once()
    mock_reset.assert_not_called()
    clear_last_segment_write.assert_not_called()
    app._reload_from_current_data_folder.assert_not_called()


def test_select_data_folder_cancelled(app):
    app.platform.choose_folder_dialog.return_value = None
    app.select_data_folder()
    # No folder chosen -> early return, set_data_dir never called
    assert app._data_dir_calls == []


def test_update_calls_tick_and_ui(app):
    app.platform.get_idle_time.return_value = 0
    app.session.on_tick = MagicMock()
    app.update_ui = MagicMock()
    app.update()
    app.session.on_tick.assert_called_once_with(0, app.idle_threshold)
    app.update_ui.assert_called_once()


def test_idle_detection_failure_pauses_and_alerts_once_then_resumes(app):
    app.platform.get_idle_time.side_effect = [None, None, 0]
    app.session.pause_tracking = MagicMock()
    app.session.on_tick = MagicMock()
    app.update_ui = MagicMock()

    app.update()
    app.update()

    assert app.session.pause_tracking.call_count == 2
    app.session.on_tick.assert_not_called()
    app.platform.show_alert.assert_called_once_with(
        i18n.t("IDLE_DETECTION_ERROR_TITLE"),
        i18n.t("IDLE_DETECTION_ERROR_MSG"),
    )

    app.update()

    app.session.on_tick.assert_called_once_with(0, app.idle_threshold)
    assert app._idle_detection_failure_shown is False


def test_update_triggers_save_when_interval_elapsed(app):
    app.platform.get_idle_time.return_value = 0
    app.session.on_tick = MagicMock()
    app.update_ui = MagicMock()
    app.session.save_all_days = MagicMock()
    app.write_interval = 0
    app.last_write_time = 0.0  # force elapsed
    app.update()
    app.session.save_all_days.assert_called_once()
    assert app.last_write_time > 0


# ------------------------------------------------------------
# optimize_csv
# ------------------------------------------------------------

@pytest.fixture
def optimize_ready(app, tmp_path, monkeypatch):
    i18n.set_locale("en")
    D = datetime(2026, 7, 15, 12, 0, 0)
    monkeypatch.setattr(app_module, "datetime", MagicMock(wraps=datetime))
    app_module.datetime.now.return_value = D
    monkeypatch.setattr(tracking, "datetime", MagicMock(wraps=datetime))
    tracking.datetime.now.return_value = D
    # idle threshold used inside optimize_csv
    monkeypatch.setattr(tracking, "get_config_value", lambda k, d=None: 300)
    return D


def test_optimize_csv_no_file(app, optimize_ready):
    app.optimize_csv()
    # Alert about missing file
    titles = [c.args[0] for c in app.platform.show_alert.call_args_list]
    assert any("OPTIMIZE_ERROR_NO_FILE" in str(t) or t == i18n.t("OPTIMIZE_ERROR_NO_FILE") for t in titles)


def test_optimize_csv_empty_file(app, tmp_path, optimize_ready):
    # Create the file with only a header (no segments)
    path = app.pm.get_log_file_path("activities", optimize_ready.year)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("date,state,start,end,duration_min,duration_seconds\n")
    app.optimize_csv()
    titles = [c.args[0] for c in app.platform.show_alert.call_args_list]
    assert any(t == i18n.t("OPTIMIZE_EMPTY") for t in titles)


@pytest.mark.parametrize("silent", [True, False])
def test_optimize_csv_handles_read_oserror(app, optimize_ready, silent):
    path = app.pm.get_log_file_path("activities", optimize_ready.year)
    path.mkdir()

    # An existing directory at the CSV path makes open(..., "r") raise
    # IsADirectoryError. Optimization must not propagate it to the updater.
    app.optimize_csv(silent=silent)

    assert path.is_dir()
    if silent:
        app.platform.show_alert.assert_not_called()
    else:
        app.platform.show_alert.assert_called_once_with(
            i18n.t("OPTIMIZE_READ_ERROR"),
            i18n.t("OPTIMIZE_READ_ERROR_MSG"),
        )


def test_optimize_csv_serializes_with_other_csv_transactions(app, optimize_ready):
    today = optimize_ready.date()
    day = Day(today, [TimeSegment(
        "active",
        datetime.combine(today, datetime.min.time()) + timedelta(hours=9),
        datetime.combine(today, datetime.min.time()) + timedelta(hours=10),
    )])
    app.pm.save_segments({today: day})
    started = threading.Event()
    finished = threading.Event()

    def optimize():
        started.set()
        app.optimize_csv(silent=True)
        finished.set()

    with app.pm.csv_transaction():
        worker = threading.Thread(target=optimize)
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.05)

    worker.join(timeout=2)
    assert not worker.is_alive()
    assert finished.is_set()


def test_optimize_csv_merges_and_reports(app, tmp_path, optimize_ready):
    from activitytracker.persistence import PersistenceManager
    pm = PersistenceManager(lambda: str(tmp_path))
    D = optimize_ready
    day = Day(D.date())
    # Two consecutive active segments with a tiny gap -> should merge to 1
    day.segments.append(TimeSegment(
        "active", datetime(2026, 7, 15, 9, 0, 0), datetime(2026, 7, 15, 9, 30, 0)))
    day.segments.append(TimeSegment(
        "active", datetime(2026, 7, 15, 9, 31, 0), datetime(2026, 7, 15, 10, 0, 0)))
    pm.save_segments({D.date(): day})

    # Point the app's pm at the same dir and re-save via the app's real pm
    app.pm = pm
    app.optimize_csv()

    # Success alert shown
    titles = [c.args[0] for c in app.platform.show_alert.call_args_list]
    assert any(t == i18n.t("OPTIMIZE_SUCCESS") for t in titles)

    # File now contains a single merged active segment
    segs = pm.read_segments_for_day(D.date())
    assert len(segs) == 1
    assert segs[0].end_time == datetime(2026, 7, 15, 10, 0, 0)


def test_optimize_csv_preserves_exclusive_midnight_end(app, tmp_path, optimize_ready):
    from activitytracker.persistence import PersistenceManager

    pm = PersistenceManager(lambda: str(tmp_path))
    today = optimize_ready.date()
    previous_day = today - timedelta(days=1)
    segment = TimeSegment(
        "active",
        datetime.combine(today, datetime.min.time()) - timedelta(seconds=2),
        datetime.combine(today, datetime.min.time()),
    )
    pm.save_segments({previous_day: Day(previous_day, [segment])})
    app.pm = pm
    app.session.pm = pm

    app.optimize_csv(silent=True)

    saved = pm.read_segments_for_day(previous_day)
    assert len(saved) == 1
    assert saved[0].end_time == datetime.combine(today, datetime.min.time())
    assert saved[0].duration_seconds == 2


def test_optimize_csv_preserves_live_segment_continuity(app, optimize_ready):
    now = datetime.combine(datetime.now().date(), datetime.min.time()) + timedelta(hours=12)
    tracking.datetime.now.return_value = now
    today = now.date()
    initial_segment = TimeSegment("active", now - timedelta(minutes=5))
    app.session.days = {today: Day(today, [initial_segment])}
    app.session.current_segment = initial_segment

    # A normal save closes rows on disk but leaves the live segment open in memory.
    app.session.save_all_days()
    live_segment = app.session.current_segment
    assert live_segment is not None and live_segment.end_time is None

    app.optimize_csv(silent=True)

    assert app.session.current_segment is live_segment
    assert live_segment.end_time is None

    # The next poll should continue this segment instead of starting a new one.
    tracking.datetime.now.return_value = now + timedelta(seconds=10)
    app.session.on_tick(idle_time=0, idle_threshold=app.idle_threshold)
    assert app.session.current_segment is live_segment
    assert live_segment.end_time is None


def test_optimize_csv_skips_malformed_rows(app, tmp_path, optimize_ready):
    from activitytracker.persistence import PersistenceManager
    pm = PersistenceManager(lambda: str(tmp_path))
    D = optimize_ready
    # Write a CSV with one malformed row (bad start) and one valid segment
    path = pm.get_log_file_path("activities", D.year)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("date,state,start,end,duration_min,duration_seconds\n")
        f.write("2026-07-15,active,badtime,10:00:00,60,3600\n")
        f.write("2026-07-15,idle,11:00:00,11:15:00,15,900\n")
        f.write("2026-07-15,unknown,12:00:00,13:00:00,60,3600\n")

    app.pm = pm
    app.optimize_csv()

    titles = [c.args[0] for c in app.platform.show_alert.call_args_list]
    # Still succeeds (valid rows were processed); malformed row skipped
    assert any(t == i18n.t("OPTIMIZE_SUCCESS") for t in titles)
    segs = pm.read_segments_for_day(D.date())
    assert len(segs) == 1  # the idle segment; malformed active row dropped
    assert segs[0].state == "idle"


# ------------------------------------------------------------
# Regression: HIGH #1 - merge must not cross a calendar-day boundary
# ------------------------------------------------------------

def test_merge_segments_to_save_does_not_cross_midnight():
    from activitytracker.persistence import PersistenceManager
    # Two active segments with a tiny gap BUT on different days
    seg1 = TimeSegment("active", datetime(2026, 7, 15, 23, 59, 50), datetime(2026, 7, 15, 23, 59, 59))
    seg2 = TimeSegment("active", datetime(2026, 7, 16, 0, 0, 20), datetime(2026, 7, 16, 0, 1, 0))
    merged = PersistenceManager.merge_segments_to_save([seg1, seg2], idle_threshold=300)
    # Must stay as two segments (different calendar days)
    assert len(merged) == 2


def test_merge_segments_to_save_merges_same_day_small_gap():
    from activitytracker.persistence import PersistenceManager
    # Two active segments same day, tiny gap -> merge into one
    seg1 = TimeSegment("active", datetime(2026, 7, 15, 9, 0, 0), datetime(2026, 7, 15, 9, 30, 0))
    seg2 = TimeSegment("active", datetime(2026, 7, 15, 9, 31, 0), datetime(2026, 7, 15, 10, 0, 0))
    merged = PersistenceManager.merge_segments_to_save([seg1, seg2], idle_threshold=300)
    assert len(merged) == 1


def test_merge_segments_to_save_handles_overlap_no_negative_duration():
    from activitytracker.persistence import PersistenceManager
    # Overlapping active segments (seg2 starts before seg1 ends) — e.g. from a
    # corrupt/legacy/manually-edited CSV. The merge must NOT create a segment
    # with end_time < start_time (negative duration); it should keep the later
    # end and drop the overlapping portion.
    seg1 = TimeSegment("active", datetime(2026, 7, 15, 9, 0, 0), datetime(2026, 7, 15, 10, 0, 0))
    seg2 = TimeSegment("active", datetime(2026, 7, 15, 9, 30, 0), datetime(2026, 7, 15, 9, 45, 0))
    merged = PersistenceManager.merge_segments_to_save([seg1, seg2], idle_threshold=300)
    assert len(merged) == 1
    # end_time must be >= start_time (no negative-duration segment)
    assert merged[0].end_time >= merged[0].start_time
    assert merged[0].end_time == datetime(2026, 7, 15, 10, 0, 0)


def test_merge_segments_to_save_overlap_extends_to_later_end():
    from activitytracker.persistence import PersistenceManager
    # seg2 overlaps seg1 but extends past it -> result keeps the later end.
    seg1 = TimeSegment("active", datetime(2026, 7, 15, 9, 0, 0), datetime(2026, 7, 15, 9, 30, 0))
    seg2 = TimeSegment("active", datetime(2026, 7, 15, 9, 15, 0), datetime(2026, 7, 15, 10, 30, 0))
    merged = PersistenceManager.merge_segments_to_save([seg1, seg2], idle_threshold=300)
    assert len(merged) == 1
    assert merged[0].start_time == datetime(2026, 7, 15, 9, 0, 0)
    assert merged[0].end_time == datetime(2026, 7, 15, 10, 30, 0)
    assert merged[0].end_time >= merged[0].start_time


# ------------------------------------------------------------
# Automatic optimization (runs after every successful save)
# ------------------------------------------------------------

def test_update_optimizes_csv_after_save(app):
    app.write_interval = 0
    app.last_write_time = 0.0  # force the save branch
    app.session.on_tick = MagicMock()
    app.session.save_all_days = MagicMock()
    app.optimize_csv = MagicMock()
    app.update()
    app.optimize_csv.assert_called_once_with(silent=True)


def test_force_save_optimizes_csv(app):
    app.session.save_all_days = MagicMock()
    app.optimize_csv = MagicMock()
    app.force_save()
    app.optimize_csv.assert_called_once_with(silent=True)



# ------------------------------------------------------------
# Regression: MEDIUM #2 - optimize_csv must tolerate missing columns
# ------------------------------------------------------------

def test_optimize_csv_skips_missing_column_rows(app, tmp_path, optimize_ready):
    from activitytracker.persistence import PersistenceManager
    pm = PersistenceManager(lambda: str(tmp_path))
    D = optimize_ready
    # Row missing the 'state' column entirely -> would raise KeyError/AttributeError
    # if not caught. Also include a valid idle segment.
    path = pm.get_log_file_path("activities", D.year)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("date,start,end,duration_min,duration_seconds\n")  # no 'state'
        f.write("2026-07-15,11:00:00,11:15:00,15,900\n")
        f.write("2026-07-15,active,12:00:00,12:30:00,30,1800\n")  # missing 'state' col here too
    app.pm = pm
    # Must not raise
    app.optimize_csv()
    titles = [c.args[0] for c in app.platform.show_alert.call_args_list]
    assert any(t == i18n.t("OPTIMIZE_EMPTY") or t == i18n.t("OPTIMIZE_SUCCESS") for t in titles)


# ------------------------------------------------------------
# Regression: MEDIUM #4 - ZeroDivisionError when weekly target is 0
# ------------------------------------------------------------

def test_update_ui_with_zero_weekly_target_does_not_crash():
    from activitytracker.activity_tracker_menu import AppMenu
    fake_app = MagicMock()
    fake_app.session.days = {}
    fake_app.target_work_seconds = 8 * 3600
    fake_app.weekly_target_seconds = 0  # the trigger condition
    menu = AppMenu(fake_app)
    # Should not raise ZeroDivisionError
    menu.update_ui(is_idle=False, active_today=0, active_week=0, weekly_target=0, weekly_idle_week=0)
    # Status indicator should fall through to the default branch
    assert menu._last_status_icon is not None


def test_report_menu_omits_days_without_activity(tmp_path):
    from activitytracker.activity_tracker_menu import AppMenu
    from activitytracker.persistence import PersistenceManager
    from activitytracker.tracking import SessionTracker

    pm = PersistenceManager(lambda: str(tmp_path))
    session = SessionTracker(pm)
    yesterday = date.today() - timedelta(days=1)
    session.days[yesterday] = Day(
        yesterday,
        [TimeSegment("active", datetime.combine(yesterday, datetime.min.time()),
                      datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=2))],
    )
    pm.save_segments(session.days)

    fake_app = MagicMock()
    fake_app.pm = pm
    fake_app.session = session
    fake_app.target_work_seconds = 8 * 3600
    fake_app.weekly_target_seconds = 40 * 3600

    menu = AppMenu(fake_app)
    report = menu._generate_report_menu()
    labels = [item.text for item in report.items]

    assert len(labels) == 1
    assert yesterday.strftime("%Y-%m-%d") in labels[0]


def test_report_menu_day_includes_statistics(tmp_path):
    from activitytracker.activity_tracker_menu import AppMenu
    from activitytracker.persistence import PersistenceManager
    from activitytracker.tracking import SessionTracker

    pm = PersistenceManager(lambda: str(tmp_path))
    session = SessionTracker(pm)
    yesterday = date.today() - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time()) + timedelta(hours=9)
    session.days[yesterday] = Day(
        yesterday,
        [
            TimeSegment("active", start, start + timedelta(hours=2)),
            TimeSegment("idle", start + timedelta(hours=2), start + timedelta(hours=3)),
            TimeSegment("active", start + timedelta(hours=3), start + timedelta(hours=4)),
        ],
    )
    pm.save_segments(session.days)

    fake_app = MagicMock()
    fake_app.pm = pm
    fake_app.session = session
    fake_app.target_work_seconds = 8 * 3600
    fake_app.weekly_target_seconds = 40 * 3600

    menu = AppMenu(fake_app)
    report = menu._generate_report_menu()
    day_menu = report.items[0].submenu
    labels = [item.text for item in day_menu.items]

    assert any(i18n.t("REPORT_START", value="09:00") in text for text in labels)
    assert any(i18n.t("REPORT_LAST_ACTIVE", value="13:00") in text for text in labels)
    assert any(i18n.t("REPORT_ACTIVE", value="03:00") in text for text in labels)
    assert any(i18n.t("REPORT_IDLE", value="01:00") in text for text in labels)
    assert any(i18n.t("REPORT_PRODUCTIVITY", value="75%") in text for text in labels)


def test_general_settings_menu_shows_version(tmp_path):
    from activitytracker.activity_tracker_menu import AppMenu
    from activitytracker.persistence import PersistenceManager
    from activitytracker.tracking import SessionTracker

    pm = PersistenceManager(lambda: str(tmp_path))
    fake_app = MagicMock()
    fake_app.pm = pm
    fake_app.session = SessionTracker(pm)
    fake_app.target_work_seconds = 8 * 3600
    fake_app.weekly_target_seconds = 40 * 3600
    fake_app.idle_threshold = 300
    fake_app.write_interval = 3600

    menu = AppMenu(fake_app)
    menu.platform.get_bundle_version = MagicMock(return_value="1.0.4")
    general = menu._generate_general_settings_menu()

    assert any(i18n.t("VERSION", value="1.0.4") in item.text for item in general.items)


def test_report_menu_shows_no_activity_message_when_empty(tmp_path):
    from activitytracker.activity_tracker_menu import AppMenu
    from activitytracker.persistence import PersistenceManager
    from activitytracker.tracking import SessionTracker

    pm = PersistenceManager(lambda: str(tmp_path))
    fake_app = MagicMock()
    fake_app.pm = pm
    fake_app.session = SessionTracker(pm)
    fake_app.target_work_seconds = 8 * 3600
    fake_app.weekly_target_seconds = 40 * 3600

    menu = AppMenu(fake_app)
    report = menu._generate_report_menu()

    assert [item.text for item in report.items] == [i18n.t("REPORT_NO_DATA")]


# ------------------------------------------------------------
# Regression: MEDIUM #5 - optimize_csv keeps aggregates consistent with the
# activities log (no separate daily-summary file anymore).
# ------------------------------------------------------------

def test_optimize_csv_keeps_aggregates_consistent(app, tmp_path, optimize_ready):
    from activitytracker.persistence import PersistenceManager
    pm = PersistenceManager(lambda: str(tmp_path))
    D = optimize_ready
    day = Day(D.date())
    # Two consecutive active segments with a tiny gap -> merge to 1
    day.segments.append(TimeSegment("active", datetime(2026, 7, 15, 9, 0, 0), datetime(2026, 7, 15, 9, 30, 0)))
    day.segments.append(TimeSegment("active", datetime(2026, 7, 15, 9, 31, 0), datetime(2026, 7, 15, 10, 0, 0)))
    pm.save_segments({D.date(): day})
    pre_summary = pm.get_minutes_for_date(D.date())

    app.pm = pm
    app.session.pm = pm
    app.optimize_csv()

    # Aggregate must be preserved (merging the 1-minute gap can shift the
    # floored minute total by 1, which is expected).
    post_summary = pm.get_minutes_for_date(D.date())
    assert post_summary[0] in (pre_summary[0], pre_summary[0] + 1)
    # And the activities log now has a single merged segment
    segs = pm.read_segments_for_day(D.date())
    assert len(segs) == 1
    # No separate daily-summary file is written.
    assert not os.path.exists(pm.get_log_file_path("daily", D.year))


def test_optimize_csv_preserves_live_segment(app, tmp_path, optimize_ready):
    from activitytracker.persistence import PersistenceManager
    pm = PersistenceManager(lambda: str(tmp_path))
    D = optimize_ready
    # Simulate an in-memory ongoing (unsaved) active segment for "today"
    today = D.date()
    app.session.days[today] = Day(today, segments=[
        TimeSegment("active", datetime(2026, 7, 15, 9, 0, 0)),
    ])
    app.session.current_segment = app.session.days[today].segments[-1]
    app.pm = pm
    app.optimize_csv()
    # The live/ongoing segment must survive: current_segment is still set
    assert app.session.current_segment is not None
    assert app.session.current_segment.state == "active"

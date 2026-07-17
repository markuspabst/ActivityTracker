"""Tests for the application controller (app.py).

The platform and persistence/config side effects are mocked so the controller
logic can be exercised without a real UI, filesystem config dir, or platform APIs.
"""

from datetime import datetime, date
from unittest.mock import MagicMock, patch

import pytest

import app as app_module
import i18n
import tracking
from models import TimeSegment, Day
from app import ActivityTrackerApp


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "get_platform", lambda: MagicMock())
    monkeypatch.setattr(app_module, "get_configured_data_dir", lambda: str(tmp_path))

    recorded = {}

    def fake_set_config_value(key, value):
        recorded[key] = value

    monkeypatch.setattr(app_module, "set_config_value", fake_set_config_value)

    data_dir_calls = []

    def fake_set_data_dir(path):
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
    app.force_save()
    app.session.save_all_days.assert_called_once()


def test_quit_app(app):
    app.session.finalize_session = MagicMock()
    app.menu.stop = MagicMock()
    app.quit_app()
    app.session.finalize_session.assert_called_once()
    app.menu.stop.assert_called_once()
    assert app._running is False


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
    # These are module-level names referenced by the method, not instance attrs
    mock_persist = MagicMock()
    monkeypatch.setattr(app_module, "persist_data_dir", mock_persist)
    app.select_data_folder()
    assert app._data_dir_calls == ["/selected/folder"]
    mock_persist.assert_called_once_with("/selected/folder")


def test_reset_data_folder(app, monkeypatch):
    app.session.save_all_days = MagicMock()  # from force_save
    mock_reset = MagicMock()
    monkeypatch.setattr(app_module, "reset_data_dir_to_default", mock_reset)
    app.reset_data_folder()
    app.session.save_all_days.assert_called_once()
    mock_reset.assert_called_once()


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


def test_optimize_csv_merges_and_reports(app, tmp_path, optimize_ready):
    from persistence import PersistenceManager
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


def test_optimize_csv_skips_malformed_rows(app, tmp_path, optimize_ready):
    from persistence import PersistenceManager
    pm = PersistenceManager(lambda: str(tmp_path))
    D = optimize_ready
    # Write a CSV with one malformed row (bad start) and one valid segment
    path = pm.get_log_file_path("activities", D.year)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("date,state,start,end,duration_min,duration_seconds\n")
        f.write("2026-07-15,active,badtime,10:00:00,60,3600\n")
        f.write("2026-07-15,idle,11:00:00,11:15:00,15,900\n")

    app.pm = pm
    app.optimize_csv()

    titles = [c.args[0] for c in app.platform.show_alert.call_args_list]
    # Still succeeds (valid rows were processed); malformed row skipped
    assert any(t == i18n.t("OPTIMIZE_SUCCESS") for t in titles)
    segs = pm.read_segments_for_day(D.date())
    assert len(segs) == 1  # the idle segment; malformed active row dropped
    assert segs[0].state == "idle"

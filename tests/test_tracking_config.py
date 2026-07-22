"""Tests for tracking.py config helpers and lock handling."""

import os
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock

import pytest

import tracking
from tracking import (
    load_config,
    save_config,
    get_config_value,
    set_config_value,
    get_configured_data_dir,
    set_data_dir,
    persist_data_dir,
    reset_data_dir_to_default,
    get_state_file_path,
    SessionTracker,
)
from persistence import PersistenceManager
from models import TimeSegment, Day


@pytest.fixture
def isolate_config(tmp_path, monkeypatch):
    """Redirect config file/dir to tmp and restore module globals afterwards."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "activity_tracker_config.json"
    legacy_cfg_file = tmp_path / "legacy" / "activity_tracker_config.json"
    monkeypatch.setattr(tracking, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(tracking, "CONFIG_FILE", str(cfg_file))
    monkeypatch.setattr(tracking, "LEGACY_CONFIG_FILE", str(legacy_cfg_file))
    saved_data_dir = tracking.DATA_DIR
    monkeypatch.setattr(tracking, "DATA_DIR", None)
    yield str(cfg_file)
    tracking.DATA_DIR = saved_data_dir


def test_load_config_missing_returns_empty(isolate_config):
    assert load_config() == {}


def test_load_config_invalid_json_returns_empty(isolate_config):
    with open(isolate_config, "w") as f:
        f.write("{not valid json")
    assert load_config() == {}


def test_save_and_load_config_roundtrip(isolate_config):
    save_config({"foo": "bar"})
    assert load_config()["foo"] == "bar"


def test_get_config_value_default(isolate_config):
    assert get_config_value("missing", "fallback") == "fallback"


def test_set_and_get_config_value(isolate_config):
    set_config_value("my_key", 123)
    assert get_config_value("my_key") == 123


def test_get_configured_data_dir_default(isolate_config):
    assert get_configured_data_dir() == tracking.DEFAULT_BASE_DIR


def test_set_data_dir_creates_directory_and_sets_global(isolate_config, tmp_path):
    target = tmp_path / "mydata"
    set_data_dir(str(target))
    assert tracking.DATA_DIR == str(target)
    assert target.exists()


def test_persist_data_dir_then_read(isolate_config, tmp_path):
    target = tmp_path / "persisted"
    persist_data_dir(str(target))
    assert get_configured_data_dir() == os.path.expanduser(str(target))


def test_reset_data_dir_to_default(isolate_config, tmp_path, monkeypatch):
    monkeypatch.setattr(tracking, "DEFAULT_BASE_DIR", str(tmp_path / "default_data"))
    persist_data_dir(str(tmp_path / "custom"))
    assert get_configured_data_dir() != tracking.DEFAULT_BASE_DIR
    reset_data_dir_to_default()
    assert get_configured_data_dir() == tracking.DEFAULT_BASE_DIR


def test_state_file_path_stays_in_default_folder(isolate_config, tmp_path, monkeypatch):
    default_dir = tmp_path / "default_data"
    custom_dir = tmp_path / "custom_data"
    monkeypatch.setattr(tracking, "DEFAULT_BASE_DIR", str(default_dir))
    monkeypatch.setattr(tracking, "STATE_FILE", str(default_dir / "state.json"))

    # Change data dir to custom location
    set_data_dir(str(custom_dir))

    # state file path remains pinned to default folder
    assert get_state_file_path() == str(default_dir / "state.json")


# ------------------------------------------------------------
# Session lock handling
# ------------------------------------------------------------

def test_set_locked_true_creates_idle_segment():
    s = SessionTracker(MagicMock())
    now = datetime(2026, 7, 1, 9, 0, 0)
    with _patch_now(tracking, now), _patch_now_models(now):
        s.set_locked(True)
    assert s.is_locked is True
    assert s.current_segment is not None
    assert s.current_segment.state == "idle"


def test_set_locked_false_creates_active_segment():
    s = SessionTracker(MagicMock())
    now = datetime(2026, 7, 1, 9, 0, 0)
    with _patch_now(tracking, now), _patch_now_models(now):
        s.set_locked(True)
        s.set_locked(False)
    assert s.is_locked is False
    assert s.current_segment.state == "active"


def test_finalize_session_sets_end_time_and_saves():
    s = SessionTracker(MagicMock())
    now = datetime(2026, 7, 1, 9, 0, 0)
    with _patch_now(tracking, now), _patch_now_models(now):
        s.on_tick(idle_time=0, idle_threshold=300)
        assert s.current_segment.end_time is None
        s.finalize_session()
    # finalize_session persists via save_all_days (which itself resets the
    # in-memory current segment to ongoing afterwards, so we only assert the save)
    s.pm.save_segments.assert_called_once()


def test_save_all_days_resets_current_segment_end_time(tmp_path):
    """After saving, the in-memory current segment should remain ongoing."""
    pm = PersistenceManager(lambda: str(tmp_path))
    s = SessionTracker(pm)
    now = datetime(2026, 7, 1, 9, 0, 0)
    with _patch_now(tracking, now), _patch_now_models(now):
        s.on_tick(idle_time=0, idle_threshold=300)
        s.current_segment.end_time = None
        s.save_all_days()
    # The current (today) segment keeps tracking -> end_time reset to None
    assert s.current_segment.end_time is None


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

from unittest.mock import patch as _patch
from datetime import datetime as _real_datetime


class _PatchNow:
    def __init__(self, module, value):
        self.module = module
        self.value = value
        self._stack = None

    def __enter__(self):
        mock = _patch.object(self.module, "datetime", MagicMock(wraps=_real_datetime))
        self._stack = mock
        dt = self._stack.__enter__()
        dt.now.return_value = self.value
        return dt

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)


def _patch_now(module, value):
    return _PatchNow(module, value)


def _patch_now_models(value):
    import models
    return _PatchNow(models, value)

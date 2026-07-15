import os
import sys
import time
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, date, timedelta
from contextlib import ExitStack
from tracking import (
    SessionTracker,
    format_hours,
)
from models import TimeSegment, Day
from tray_icon import get_status_icon
from persistence import PersistenceManager

# ============================================================
#  HELPERS
# ============================================================

FROZEN_DAY1 = datetime(2026, 7, 1, 9, 0, 0)
FROZEN_DAY1_1030 = datetime(2026, 7, 1, 10, 30, 0)
FROZEN_DAY2 = datetime(2026, 7, 2, 0, 0, 5)

def make_session(pm=None):
    if pm is None:
        pm = MagicMock(spec=PersistenceManager)
    return SessionTracker(pm)


class PatcherInfo:
    """Helper to return the patched datetime mocks and allow easy setting of now.return_value."""
    def __init__(self, tracking_mock, models_mock):
        self.tracking_mock = tracking_mock
        self.models_mock = models_mock

    def set_now(self, dt_value):
        self.tracking_mock.now.return_value = dt_value
        self.models_mock.now.return_value = dt_value

@pytest.fixture
def patch_all_datetimes():
    """Fixture to patch datetime.now() in both tracking and models modules."""
    with ExitStack() as stack:
        mock_datetime_tracking = MagicMock(wraps=datetime)
        mock_datetime_tracking.now.return_value = FROZEN_DAY1 # Default for helper, overridden by tests
        mock_datetime_tracking.fromisoformat.side_effect = datetime.fromisoformat
        mock_patch_tracking = stack.enter_context(patch('tracking.datetime', mock_datetime_tracking))

        mock_datetime_models = MagicMock(wraps=datetime)
        mock_datetime_models.now.return_value = FROZEN_DAY1 # Default for helper, overridden by tests
        mock_datetime_models.fromisoformat.side_effect = datetime.fromisoformat
        mock_patch_models = stack.enter_context(patch('models.datetime', mock_datetime_models))

        yield PatcherInfo(mock_patch_tracking, mock_patch_models)


# ============================================================
#  FORMATTING TESTS
# ============================================================

def test_format_hours():
    assert format_hours(3600) == "01:00"

# ============================================================
#  STATUS ICON TESTS
# ============================================================

def test_get_status_icon(): # No patch_now usage here
    target = 8 * 3600
    assert get_status_icon(is_idle=True, active_today=0, target_work_seconds=target, active_week=0, target_weekly_work_seconds=40*3600) == "🔴"

# ============================================================
#  MODEL TESTS
# ============================================================

def test_time_segment_duration():
    start = datetime(2026, 7, 1, 9, 0, 0)
    end = datetime(2026, 7, 1, 9, 30, 0)
    segment = TimeSegment(state='active', start_time=start, end_time=end)
    assert segment.duration_minutes == 30


def test_day_total_active_seconds(patch_all_datetimes):
    test_now = datetime(2026, 7, 1, 10, 0, 0)
    patch_all_datetimes.set_now(test_now)

    d = Day(date=date(2026, 7, 1))
    # Add a completed segment
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    # Add an ongoing segment
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 45, 0)))
    # 30 mins (completed) + 15 mins (ongoing) = 45 mins = 2700 seconds
    assert d.total_active_seconds() == 2700

    # Test with idle minutes
    d_idle = Day(date=date(2026, 7, 1))
    d_idle.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    d_idle.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 1, 9, 30, 0), end_time=datetime(2026, 7, 1, 9, 45, 0)))
    assert d_idle.active_minutes == 30
    assert d_idle.idle_minutes == 15 # Now this should be 15

# ============================================================
#  SESSION TRACKER TESTS
# ============================================================

def test_session_tracker_tick(patch_all_datetimes):
    s = make_session()
    patch_all_datetimes.set_now(FROZEN_DAY1)
    s.on_tick(idle_time=0, idle_threshold=300)
    assert len(s.days[FROZEN_DAY1.date()].segments) == 1
    assert s.current_segment.state == 'active'

    patch_all_datetimes.set_now(FROZEN_DAY1 + timedelta(minutes=10))
    s.on_tick(idle_time=400, idle_threshold=300)
    assert len(s.days[FROZEN_DAY1.date()].segments) == 2
    assert s.current_segment.state == 'idle'

def test_session_tracker_midnight_rollover(patch_all_datetimes):
    s = make_session()
    patch_all_datetimes.set_now(FROZEN_DAY1)
    s.on_tick(idle_time=0, idle_threshold=300)

    patch_all_datetimes.set_now(FROZEN_DAY2)
    s.on_tick(idle_time=0, idle_threshold=300)
    assert FROZEN_DAY1.date() in s.days
    assert FROZEN_DAY2.date() in s.days
    day1_segments = s.days[FROZEN_DAY1.date()].segments
    assert abs((day1_segments[-1].end_time - datetime.combine(FROZEN_DAY1.date(), datetime.max.time())).total_seconds()) < 1

def test_session_tracker_finalize(patch_all_datetimes):
    s = make_session()
    patch_all_datetimes.set_now(FROZEN_DAY1)
    s.on_tick(idle_time=0, idle_threshold=300)
    s.finalize_session()
    s.pm.save_daily_summary.assert_called_once()

# ============================================================
#  PERSISTENCE TESTS
# ============================================================

@pytest.fixture
def temp_data_dir(tmp_path):
    return tmp_path

@pytest.fixture
def pm(temp_data_dir):
    return PersistenceManager(lambda: str(temp_data_dir))

def test_persistence_manager_save_and_read(pm, temp_data_dir):
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    days = {date(2026, 7, 1): d}
    summaries = {date(2026, 7, 1): {"active_min": 30, "idle_min": 0, "session_start": "09:00", "session_end": "09:30"}}

    pm.save_segments(days)
    pm.save_daily_summary(summaries)

    active, idle = pm.read_daily_summaries_for_week(date(2026, 7, 1) - timedelta(days=date(2026, 7, 1).weekday()))
    assert active == 30
    assert idle == 0

def test_persistence_manager_read_daily_summary_for_day(pm, temp_data_dir):
    test_date = date(2026, 7, 1)
    d = Day(date=test_date)
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    d.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 1, 9, 30, 0), end_time=datetime(2026, 7, 1, 9, 40, 0)))

    daily_summary = {
        "active_min": d.active_minutes,
        "idle_min": d.idle_minutes,
        "session_start": "09:00",
        "session_end": "09:40",
    }

    pm.save_daily_summary({test_date: daily_summary})

    active, idle = pm.read_daily_summary_for_day(test_date)
    assert active == d.active_minutes
    assert idle == d.idle_minutes

# ============================================================
#  CRASH RECOVERY TESTS
# ============================================================

def test_crash_recovery(temp_data_dir, patch_all_datetimes):
    patch_all_datetimes.set_now(datetime(2026, 7, 1, 10, 0, 0)) # Ensure now is consistent
    state_file = temp_data_dir / "activity_tracker_state.json"
    state = {
        "dirty": True,
        "current_segment": {"state": "active", "start_time": "2026-07-01T10:00:00"},
        "last_active_time": "2026-07-01T10:30:00"
    }
    with open(state_file, 'w') as f:
        json.dump(state, f)

    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = make_session(pm)
    s.recover_from_crash()

    assert len(s.days[date(2026, 7, 1)].segments) == 1
    recovered_seg = s.days[date(2026, 7, 1)].segments[0]
    assert recovered_seg.end_time == datetime.fromisoformat(state["last_active_time"])

def test_crash_recovery_without_last_active_time(temp_data_dir, patch_all_datetimes):
    patch_all_datetimes.set_now(datetime(2026, 7, 1, 10, 0, 0)) # Ensure now is consistent
    state_file = temp_data_dir / "activity_tracker_state.json"
    state = {
        "dirty": True,
        "current_segment": {"state": "active", "start_time": "2026-07-01T10:00:00"},
        "last_active_time": None
    }
    with open(state_file, 'w') as f:
        json.dump(state, f)

    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = make_session(pm)
    s.recover_from_crash()

    # Should recover the ongoing segment even with null last_active_time
    assert len(s.days[date(2026, 7, 1)].segments) == 1
    recovered_seg = s.days[date(2026, 7, 1)].segments[0]
    assert recovered_seg.state == 'active'
    assert recovered_seg.start_time == datetime.fromisoformat("2026-07-01T10:00:00")
    assert recovered_seg.end_time is None  # Ongoing segment

def test_session_tracker_load_current_day_segments_clean_start(pm, temp_data_dir, patch_all_datetimes):
    today = date(2026, 7, 15)
    # Simulate some past segments for today that were saved
    day_data_to_save = Day(date=today)
    day_data_to_save.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 15, 9, 0, 0), end_time=datetime(2026, 7, 15, 9, 30, 0)))
    day_data_to_save.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 15, 9, 30, 0), end_time=datetime(2026, 7, 15, 9, 45, 0)))
    pm.save_segments({today: day_data_to_save})
    pm.save_daily_summary({today: {"active_min": day_data_to_save.active_minutes, "idle_min": day_data_to_save.idle_minutes, "session_start": "", "session_end": ""}})

    # Simulate a clean start
    s = make_session(pm)
    # Patch datetime.now() for this specific test to ensure 'today' matches the saved data
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))
    s.load_current_day_segments()

    assert today in s.days
    assert len(s.days[today].segments) == 2
    assert s.days[today].active_minutes == 30
    assert s.days[today].idle_minutes == 15

def test_session_tracker_load_current_day_segments_with_crash_recovery_merge(pm, temp_data_dir, patch_all_datetimes):
    today = date(2026, 7, 15)

    # 1. Simulate a crash state with an ongoing segment
    state_file = temp_data_dir / "activity_tracker_state.json"
    state = {
        "dirty": True,
        "current_segment": {"state": "active", "start_time": "2026-07-15T08:00:00"},
        "last_active_time": "2026-07-15T08:10:00" # 10 mins active
    }
    with open(state_file, 'w') as f:
        json.dump(state, f)

    # 2. Simulate some previously saved segments for today
    day_data_to_save = Day(date=today)
    day_data_to_save.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 15, 7, 0, 0), end_time=datetime(2026, 7, 15, 7, 30, 0))) # 30 mins active
    pm.save_segments({today: day_data_to_save})
    pm.save_daily_summary({today: {"active_min": 30, "idle_min": 0, "session_start": "", "session_end": ""}})

    # 3. Create SessionTracker and call both recovery methods
    s = make_session(pm)
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))
    s.recover_from_crash()
    s.load_current_day_segments()

    # Assertions: should have 2 segments, total 40 active minutes (30 saved + 10 recovered)
    assert today in s.days
    # Expect 2 segments: 1 from CSV, 1 from crash recovery
    assert len(s.days[today].segments) == 2
    assert s.days[today].active_minutes == 40
    assert s.days[today].idle_minutes == 0 # No idle in this scenario

    # Verify segments are sorted by start_time
    assert s.days[today].segments[0].start_time == datetime(2026, 7, 15, 7, 0, 0)
    assert s.days[today].segments[1].start_time == datetime(2026, 7, 15, 8, 0, 0)

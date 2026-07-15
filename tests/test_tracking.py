import os
import sys
import time
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, date, timedelta
from tracking import (
    SessionTracker,
    TimeSegment,
    Day,
    format_hours,
    format_delta,
    hours,
)
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

def patch_now(dt):
    return patch('tracking.datetime', **{
        'now.return_value': dt,
        'date': datetime.date,
        'combine': datetime.combine,
        'max': datetime.max,
        'min': datetime.min
    })

# ============================================================
#  FORMATTING TESTS
# ============================================================

def test_format_hours():
    assert format_hours(3600) == "01:00"

def test_get_status_icon():
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


def test_day_total_active_seconds():
    d = Day(date=date(2026, 7, 1))
    # Add a completed segment
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    # Add an ongoing segment
    with patch_now(datetime(2026, 7, 1, 10, 0, 0)):
        d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 45, 0)))
        # 30 mins (completed) + 15 mins (ongoing) = 45 mins = 2700 seconds
        assert d.total_active_seconds() == 2700

    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    d.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 1, 9, 30, 0), end_time=datetime(2026, 7, 1, 9, 45, 0)))
    assert d.active_minutes == 30
    # Idle time that starts at the session end boundary is not counted to cleanly separate work periods from post-work time
    assert d.idle_minutes == 0

# ============================================================
#  SESSION TRACKER TESTS
# ============================================================

def test_session_tracker_tick():
    s = make_session()
    with patch_now(FROZEN_DAY1):
        s.on_tick(idle_time=0, idle_threshold=300)
        assert len(s.days[FROZEN_DAY1.date()].segments) == 1
        assert s.current_segment.state == 'active'

    with patch_now(FROZEN_DAY1 + timedelta(minutes=10)):
        s.on_tick(idle_time=400, idle_threshold=300)
        assert len(s.days[FROZEN_DAY1.date()].segments) == 2
        assert s.current_segment.state == 'idle'

def test_session_tracker_midnight_rollover():
    s = make_session()
    with patch_now(FROZEN_DAY1):
        s.on_tick(idle_time=0, idle_threshold=300)

    with patch_now(FROZEN_DAY2):
        s.on_tick(idle_time=0, idle_threshold=300)
        assert FROZEN_DAY1.date() in s.days
        assert FROZEN_DAY2.date() in s.days
        day1_segments = s.days[FROZEN_DAY1.date()].segments
        assert abs((day1_segments[-1].end_time - datetime.combine(FROZEN_DAY1.date(), datetime.max.time())).total_seconds()) < 1

def test_session_tracker_finalize():
    s = make_session()
    with patch_now(FROZEN_DAY1):
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

# ============================================================
#  CRASH RECOVERY TESTS
# ============================================================

def test_crash_recovery(temp_data_dir):
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
    assert recovered_seg.end_time == datetime.fromisoformat("2026-07-01T10:30:00")

def test_crash_recovery_without_last_active_time(temp_data_dir):
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

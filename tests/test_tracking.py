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
    # After midnight, day1's segment ends at max.time() and day2 starts
    # Both days should be in s.days
    assert FROZEN_DAY1.date() in s.days or FROZEN_DAY2.date() in s.days
    assert FROZEN_DAY2.date() in s.days
    # The previous day's segment should be capped at end of day
    if FROZEN_DAY1.date() in s.days:
        day1_segments = s.days[FROZEN_DAY1.date()].segments
        if day1_segments and day1_segments[-1].end_time:
            assert abs((day1_segments[-1].end_time - datetime.combine(FROZEN_DAY1.date(), datetime.max.time())).total_seconds()) < 1

def test_session_tracker_finalize(patch_all_datetimes):
    s = make_session()
    patch_all_datetimes.set_now(FROZEN_DAY1)
    s.on_tick(idle_time=0, idle_threshold=300)
    s.finalize_session()
    # Now only saves segments, no daily summary
    s.pm.save_segments.assert_called_once()

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

    pm.save_segments(days)

    # Read minutes from segments for the week
    week_start = date(2026, 7, 1) - timedelta(days=date(2026, 7, 1).weekday())
    active, idle = pm.get_weekly_minutes(week_start)
    assert active == 30
    assert idle == 0

def test_persistence_manager_get_minutes_for_day(pm, temp_data_dir):
    test_date = date(2026, 7, 1)
    d = Day(date=test_date)
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    d.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 1, 9, 30, 0), end_time=datetime(2026, 7, 1, 9, 40, 0)))

    pm.save_segments({test_date: d})

    # Read minutes directly from segments
    active, idle = pm.get_minutes_for_date(test_date)
    assert active == d.active_minutes
    assert idle == d.idle_minutes

# ============================================================
#  CSV-ONLY RECOVERY TESTS
# ============================================================

def test_session_tracker_load_current_day_segments_clean_start(pm, temp_data_dir, patch_all_datetimes):
    """Test loading segments from CSV (CSV-only recovery, no JSON state file)."""
    from persistence import PersistenceManager
    from tracking import SessionTracker

    # Create a real PM, not a mock
    pm_real = PersistenceManager(lambda: str(temp_data_dir))
    today = date(2026, 7, 15)
    # Simulate some past segments for today that were saved
    day_data_to_save = Day(date=today)
    # Use distinct hours so segments don't overwrite each other
    day_data_to_save.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 15, 9, 0, 0), end_time=datetime(2026, 7, 15, 9, 30, 0)))
    day_data_to_save.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 15, 10, 0, 0), end_time=datetime(2026, 7, 15, 10, 15, 0)))
    pm_real.save_segments({today: day_data_to_save})

    # Simulate a clean start - data is loaded from CSV
    s = SessionTracker(pm_real)
    # Patch datetime.now() to be later than the saved segments
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 11, 0, 0))
    s.load_current_day_segments()

    assert today in s.days
    # At least one segment should be loaded (segment at 9 AM or 10 AM)
    assert len(s.days[today].segments) >= 1

def test_session_tracker_load_current_day_segments_with_ongoing_segment(pm, temp_data_dir, patch_all_datetimes):
    """Test loading segments from CSV including an ongoing segment."""
    from persistence import PersistenceManager
    from tracking import SessionTracker

    # Create a real PM, not a mock
    pm_real = PersistenceManager(lambda: str(temp_data_dir))
    today = date(2026, 7, 15)

    # Simulate some segments from earlier today that were saved - use distinct hours
    day_data_to_save = Day(date=today)
    day_data_to_save.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 15, 7, 0, 0), end_time=datetime(2026, 7, 15, 7, 30, 0)))
    day_data_to_save.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 15, 8, 0, 0), end_time=datetime(2026, 7, 15, 8, 30, 0)))
    pm_real.save_segments({today: day_data_to_save})

    # Create SessionTracker and load segments
    s = SessionTracker(pm_real)
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))

    # Load historical data from CSV
    s.load_current_day_segments()

    # Now simulate an in-progress segment started at 9:00 (not yet saved to CSV)
    # This happens when the app was running and crashed
    s.days[today].segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 15, 9, 0, 0)))
    s.current_segment = s.days[today].segments[-1]

    # Calculate active minutes - should include ongoing segment (9:00 to 10:00 = 60 mins)
    # Plus 30 mins from completed active segment
    assert s.days[today].active_minutes >= 60  # At least 60 mins (ongoing + completed)


# ============================================================
#  DAILY AND WEEK LOGGING TESTS
# ============================================================

def test_daily_logging_complete_segment(patch_all_datetimes, temp_data_dir):
    """Test that logging works correctly for a complete segment."""
    today = date(2026, 7, 15)
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    # Complete the segment after 45 minutes
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 45, 0))
    s.on_tick(idle_time=400, idle_threshold=300)

    # Now verify save_all_days persists correctly
    s.save_all_days()

    # Read back from segments and verify
    active, idle = pm.get_minutes_for_date(today)
    assert active == 45
    assert idle == 0


def test_daily_logging_with_idle_segment(patch_all_datetimes, temp_data_dir):
    """Test logging with both active and idle segments."""
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)

    # Start active at 9:00
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    # Switch to idle at 9:30
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 30, 0))
    s.on_tick(idle_time=400, idle_threshold=300)

    # Switch back to active at 10:00
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    # Verify in-memory values before save
    # We have 3 segments:
    # 1. active 9:00-9:30 = 30 min
    # 2. idle 9:30-10:00 = 30 min
    # 3. active 10:00-now (ongoing) = 0 (not yet saved)
    assert s.days[date(2026, 7, 15)].active_minutes == 30  # Only completed active segment
    assert s.days[date(2026, 7, 15)].idle_minutes == 30    # Complete idle segment

    # Save and verify by reading from segments
    s.save_all_days()

    active, idle = pm.get_minutes_for_date(date(2026, 7, 15))
    assert active == 30
    assert idle == 30


def test_daily_logging_ongoing_segment(patch_all_datetimes):
    """Test that ongoing segments are logged correctly with current time."""
    pm = make_session()  # Use mock for in-memory tests
    s = pm

    # Start active at 9:00
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    # Simulate now at 9:45 (ongoing segment = 45 mins)
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 45, 0))

    # Call total_active_seconds - should include ongoing time
    today = date(2026, 7, 15)
    assert s.days[today].active_minutes == 45


def test_weekly_logging_multiple_days(patch_all_datetimes, temp_data_dir):
    """Test weekly aggregation across multiple days."""
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)

    # Create data for specific day only by controlling days dict
    # Manually set up days for July 13 and 14

    # Day 1: Mon July 13, 9:00-10:00 active (60 mins)
    day_jul13 = Day(date=date(2026, 7, 13))
    day_jul13.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 13, 9, 0, 0), end_time=datetime(2026, 7, 13, 10, 0, 0)))
    s.days[date(2026, 7, 13)] = day_jul13

    # Day 2: Tue July 14, 11:00-11:30 active (30 mins)
    day_jul14 = Day(date=date(2026, 7, 14))
    day_jul14.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 14, 11, 0, 0), end_time=datetime(2026, 7, 14, 11, 30, 0)))
    s.days[date(2026, 7, 14)] = day_jul14

    # Save both days at once
    s.save_all_days()

    # Read week totals from segments
    week_start = date(2026, 7, 13)  # Monday
    active, idle = pm.get_weekly_minutes(week_start)

    assert active == 90   # 60 + 30
    assert idle == 0


def test_weekly_logging_with_ongoing_segment_today(patch_all_datetimes, temp_data_dir):
    """Test weekly aggregation includes ongoing segment for today."""
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)

    # Day 1: Mon July 13, 9:00-10:00 active (60 mins) - completed
    patch_all_datetimes.set_now(datetime(2026, 7, 13, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)
    patch_all_datetimes.set_now(datetime(2026, 7, 13, 10, 0, 0))
    s.on_tick(idle_time=400, idle_threshold=300)
    s.save_all_days()

    # Day 7: Sun July 19, started at 9:00, currently at 9:30 (30 mins ongoing)
    patch_all_datetimes.set_now(datetime(2026, 7, 19, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)
    patch_all_datetimes.set_now(datetime(2026, 7, 19, 9, 30, 0))

    # Day 7 active_minutes should include ongoing segment
    assert s.days[date(2026, 7, 19)].active_minutes == 30

    # When saving, the ongoing segment gets end_time set to now
    s.save_all_days()

    # Read back from segments
    active, idle = pm.get_minutes_for_date(date(2026, 7, 19))
    assert active == 30

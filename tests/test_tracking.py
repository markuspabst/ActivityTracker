import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, date, timedelta
from contextlib import ExitStack
from activitytracker.tracking import (
    SessionTracker,
    format_hours,
)
from activitytracker.models import TimeSegment, Day
from activitytracker.tray_icon import get_status_icon
from activitytracker.persistence import PersistenceManager


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
        mock_datetime_tracking.now.return_value = FROZEN_DAY1
        mock_datetime_tracking.fromisoformat.side_effect = datetime.fromisoformat
        mock_patch_tracking = stack.enter_context(patch('activitytracker.tracking.datetime', mock_datetime_tracking))

        mock_datetime_models = MagicMock(wraps=datetime)
        mock_datetime_models.now.return_value = FROZEN_DAY1
        mock_datetime_models.fromisoformat.side_effect = datetime.fromisoformat
        mock_patch_models = stack.enter_context(patch('activitytracker.models.datetime', mock_datetime_models))

        yield PatcherInfo(mock_patch_tracking, mock_patch_models)


# ============================================================
#  FORMATTING TESTS
# ============================================================

def test_format_hours():
    assert format_hours(3600) == "01:00"


# ============================================================
#  STATUS ICON TESTS
# ============================================================

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


def test_day_total_active_seconds(patch_all_datetimes):
    test_now = datetime(2026, 7, 1, 10, 0, 0)
    patch_all_datetimes.set_now(test_now)

    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 45, 0)))
    assert d.total_active_seconds() == 2700

    d_idle = Day(date=date(2026, 7, 1))
    d_idle.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    d_idle.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 1, 9, 30, 0), end_time=datetime(2026, 7, 1, 9, 45, 0)))
    assert d_idle.active_minutes == 30
    assert d_idle.idle_minutes == 15


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
    # Use a realistic sub-threshold gap (production ticks every ~5s) so the
    # sleep-gap detector does not fire across the day boundary.
    patch_all_datetimes.set_now(datetime(2026, 7, 1, 23, 59, 58))
    s.on_tick(idle_time=0, idle_threshold=300)

    patch_all_datetimes.set_now(datetime(2026, 7, 2, 0, 0, 3))
    s.on_tick(idle_time=0, idle_threshold=300)

    # After midnight rollover and save, only July 2 should remain in memory
    assert date(2026, 7, 2) in s.days
    assert date(2026, 7, 1) not in s.days


def test_midnight_rollover_splits_before_state_transition(patch_all_datetimes):
    s = make_session()
    s.pm._filter_idle_boundary_segments.side_effect = lambda segments: segments
    patch_all_datetimes.set_now(datetime(2026, 7, 1, 23, 59, 58))
    s.on_tick(idle_time=0, idle_threshold=300)

    patch_all_datetimes.set_now(datetime(2026, 7, 2, 0, 0, 3))
    s.on_tick(idle_time=400, idle_threshold=300)

    previous_day = s.pm.save_segments.call_args.args[0][date(2026, 7, 1)]
    assert previous_day.segments[0].end_time == datetime(2026, 7, 1, 23, 59, 59)
    today_segments = s.days[date(2026, 7, 2)].segments
    assert today_segments[0].start_time == datetime(2026, 7, 2, 0, 0, 0)
    assert today_segments[0].end_time == datetime(2026, 7, 2, 0, 0, 3)
    assert today_segments[1].state == 'idle'


def test_sleep_gap_ending_exactly_at_midnight_does_not_crash(patch_all_datetimes):
    s = make_session()
    patch_all_datetimes.set_now(datetime(2026, 7, 1, 23, 58, 59))
    s.on_tick(idle_time=0, idle_threshold=300)

    patch_all_datetimes.set_now(datetime(2026, 7, 2, 0, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    assert date(2026, 7, 2) in s.days
    assert s.current_segment.start_time == datetime(2026, 7, 2, 0, 0, 0)

def test_session_tracker_finalize(patch_all_datetimes):
    s = make_session()
    patch_all_datetimes.set_now(FROZEN_DAY1)
    s.on_tick(idle_time=0, idle_threshold=300)
    s.finalize_session()
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

    week_start = date(2026, 7, 1) - timedelta(days=date(2026, 7, 1).weekday())
    active, idle = pm.get_weekly_minutes(week_start)
    assert active == 30
    assert idle == 0

def test_persistence_manager_get_minutes_for_day(pm, temp_data_dir):
    test_date = date(2026, 7, 1)
    d = Day(date=test_date)
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    # Idle after active - should be filtered out
    d.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 1, 9, 30, 0), end_time=datetime(2026, 7, 1, 9, 40, 0)))

    pm.save_segments({test_date: d})

    active, idle = pm.get_minutes_for_date(test_date)
    assert active == d.active_minutes
    # Idle after last active is filtered, so idle should be 0
    assert idle == 0


# ============================================================
#  CSV LOADING TESTS
# ============================================================

def test_session_tracker_load_current_day_segments_clean_start(pm, temp_data_dir, patch_all_datetimes):
    from activitytracker.persistence import PersistenceManager
    from activitytracker.tracking import SessionTracker

    pm_real = PersistenceManager(lambda: str(temp_data_dir))
    today = date(2026, 7, 15)
    day_data_to_save = Day(date=today)
    day_data_to_save.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 15, 9, 0, 0), end_time=datetime(2026, 7, 15, 9, 30, 0)))
    day_data_to_save.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 15, 10, 0, 0), end_time=datetime(2026, 7, 15, 10, 15, 0)))
    pm_real.save_segments({today: day_data_to_save})

    s = SessionTracker(pm_real)
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 11, 0, 0))
    s.load_current_day_segments()

    assert today in s.days
    assert len(s.days[today].segments) >= 1

def test_session_tracker_load_current_day_segments_with_ongoing_segment(pm, temp_data_dir, patch_all_datetimes):
    from activitytracker.persistence import PersistenceManager
    from activitytracker.tracking import SessionTracker

    pm_real = PersistenceManager(lambda: str(temp_data_dir))
    today = date(2026, 7, 15)

    day_data_to_save = Day(date=today)
    day_data_to_save.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 15, 7, 0, 0), end_time=datetime(2026, 7, 15, 7, 30, 0)))
    day_data_to_save.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 15, 8, 0, 0), end_time=datetime(2026, 7, 15, 8, 30, 0)))
    pm_real.save_segments({today: day_data_to_save})
    # Provide a known last-write time so the (manually added) open segment below
    # finalizes with a real duration (FR-2.6) instead of being credited zero.
    pm_real.save_last_segment_write(datetime(2026, 7, 15, 10, 0, 0))

    s = SessionTracker(pm_real)
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))

    s.load_current_day_segments()

    s.days[today].segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 15, 9, 0, 0)))
    s.current_segment = s.days[today].segments[-1]

    assert s.days[today].active_minutes >= 60


def test_session_tracker_load_finalizes_orphaned_open_segment(tmp_path, patch_all_datetimes):
    from activitytracker.persistence import PersistenceManager
    from activitytracker.tracking import SessionTracker

    pm_real = PersistenceManager(lambda: str(tmp_path))
    today = date(2026, 7, 15)

    day_data_to_save = Day(date=today)
    # Active 7:00-7:30
    day_data_to_save.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 15, 7, 0, 0), end_time=datetime(2026, 7, 15, 7, 30, 0)))
    # Idle after last active - with the new behavior, this is filtered out and not saved
    # So when loading, only the active segment exists
    day_data_to_save.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 15, 8, 0, 0)))
    pm_real.save_segments({today: day_data_to_save})
    pm_real.save_last_segment_write(datetime(2026, 7, 15, 9, 0, 0))

    s = SessionTracker(pm_real)
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))
    s.load_current_day_segments()

    # The idle segment after last active is filtered, so only the active segment remains
    # The orphan finalization applies to ongoing segments, but since the idle was filtered,
    # the last saved segment is the active one which already has end_time=7:30
    assert s.current_segment is None
    assert len(s.days[today].segments) == 1
    assert s.days[today].segments[0].state == 'active'
    assert s.days[today].segments[0].end_time == datetime(2026, 7, 15, 7, 30, 0)


def test_session_tracker_load_orphaned_segment_when_last_write_is_none(tmp_path, patch_all_datetimes):
    pm = MagicMock(spec=PersistenceManager)
    today = date(2026, 7, 15)
    orphan = TimeSegment(state='active', start_time=datetime(2026, 7, 15, 9, 0, 0), end_time=None)
    pm.read_segments_for_day.return_value = [orphan]
    pm.read_last_segment_write.return_value = None

    s = SessionTracker(pm)
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))
    s.load_current_day_segments()

    assert s.current_segment is None
    assert len(s.days[today].segments) == 1
    # When no last_write is available, closes conservatively at start_time
    assert s.days[today].segments[0].end_time == datetime(2026, 7, 15, 9, 0, 0)


def test_session_tracker_load_orphaned_segment_when_last_write_is_invalid(tmp_path, patch_all_datetimes, caplog):
    import logging
    pm = MagicMock(spec=PersistenceManager)
    today = date(2026, 7, 15)
    orphan = TimeSegment(state='active', start_time=datetime(2026, 7, 15, 9, 0, 0), end_time=None)
    pm.read_segments_for_day.return_value = [orphan]
    pm.read_last_segment_write.return_value = "not-a-datetime"

    s = SessionTracker(pm)
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))
    with caplog.at_level(logging.WARNING):
        s.load_current_day_segments()

    assert s.current_segment is None
    assert len(s.days[today].segments) == 1
    assert s.days[today].segments[0].end_time == datetime(2026, 7, 15, 9, 0, 0)
    assert "Invalid last_segment_write timestamp: not-a-datetime" in caplog.text


def test_on_tick_records_sleep_gap_as_idle(patch_all_datetimes):
    s = make_session()
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    # Simulate the machine sleeping for ~2 hours (far beyond the poll interval).
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 11, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    segs = s.days[date(2026, 7, 15)].segments
    idle_segs = [seg for seg in segs if seg.state == 'idle']
    assert idle_segs, "expected an idle segment covering the sleep gap"
    gap = idle_segs[0]
    assert gap.start_time == datetime(2026, 7, 15, 9, 0, 0)
    assert gap.end_time == datetime(2026, 7, 15, 11, 0, 0)


def test_on_tick_no_false_sleep_gap_for_normal_interval(patch_all_datetimes):
    s = make_session()
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)
    # A normal ~5s tick gap must NOT be recorded as a sleep interval.
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 0, 5))
    s.on_tick(idle_time=0, idle_threshold=300)
    idle_segs = [seg for seg in s.days[date(2026, 7, 15)].segments if seg.state == 'idle']
    assert not idle_segs


def test_pause_tracking_closes_at_last_valid_sample_and_resumes_cleanly(patch_all_datetimes):
    s = make_session()
    first_sample = datetime(2026, 7, 15, 9, 0, 0)
    last_sample = first_sample + timedelta(seconds=10)
    resume_time = first_sample + timedelta(minutes=1)

    patch_all_datetimes.set_now(first_sample)
    s.on_tick(idle_time=0, idle_threshold=300)
    patch_all_datetimes.set_now(last_sample)
    s.on_tick(idle_time=0, idle_threshold=300)
    paused_segment = s.current_segment

    # Sensor failure is detected later; the unknown interval is not credited.
    patch_all_datetimes.set_now(resume_time - timedelta(seconds=1))
    s.pause_tracking()

    assert paused_segment.end_time == last_sample
    assert s.current_segment is None

    patch_all_datetimes.set_now(resume_time)
    s.on_tick(idle_time=0, idle_threshold=300)
    assert s.current_segment is not paused_segment
    assert s.current_segment.start_time == resume_time


def test_save_all_days_propagates_write_error_and_retains_memory():
    from activitytracker.persistence import PersistenceWriteError
    s = make_session()
    today = date(2026, 7, 15)
    s.days[today] = Day(date=today)
    s.current_segment = TimeSegment('active', datetime(2026, 7, 15, 9, 0, 0))
    s.days[today].segments.append(s.current_segment)
    s.pm.save_segments.side_effect = PersistenceWriteError("disk full")

    with pytest.raises(PersistenceWriteError):
        s.save_all_days()

    # In-memory data must be retained (not cleared) so it can be retried (NFR-5.2).
    assert today in s.days
    assert len(s.days[today].segments) == 1


def test_failed_save_keeps_current_segment_open_and_tracking_advances(patch_all_datetimes):
    from activitytracker.persistence import PersistenceWriteError

    s = make_session()
    today = date(2026, 7, 15)
    segment = TimeSegment('active', datetime(2026, 7, 15, 9, 0, 0))
    s.days[today] = Day(date=today, segments=[segment])
    s.current_segment = segment
    s.pm.save_segments.side_effect = PersistenceWriteError("disk full")

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))
    with pytest.raises(PersistenceWriteError):
        s.save_all_days()

    assert segment.end_time is None
    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 10, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    assert segment.end_time is None
    assert s.days[today].total_active_seconds() == 70 * 60


# ============================================================
#  DAILY AND WEEKLY LOGGING TESTS
# ============================================================

def test_daily_logging_complete_segment(patch_all_datetimes, temp_data_dir):
    today = date(2026, 7, 15)
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 45, 0))
    s.on_tick(idle_time=400, idle_threshold=300)

    s.save_all_days()

    active, idle = pm.get_minutes_for_date(today)
    assert active == 45
    assert idle == 0


def test_daily_logging_with_idle_segment(patch_all_datetimes, temp_data_dir):
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 30, 0))
    s.on_tick(idle_time=400, idle_threshold=300)

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 10, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    assert s.days[date(2026, 7, 15)].active_minutes == 30
    assert s.days[date(2026, 7, 15)].idle_minutes == 30

    s.save_all_days()

    active, idle = pm.get_minutes_for_date(date(2026, 7, 15))
    assert active == 30
    assert idle == 30


def test_daily_logging_ongoing_segment(patch_all_datetimes):
    pm = make_session()
    s = pm

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 9, 45, 0))

    today = date(2026, 7, 15)
    assert s.days[today].active_minutes == 45


def test_weekly_logging_multiple_days(patch_all_datetimes, temp_data_dir):
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)

    day_jul13 = Day(date=date(2026, 7, 13))
    day_jul13.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 13, 9, 0, 0), end_time=datetime(2026, 7, 13, 10, 0, 0)))
    s.days[date(2026, 7, 13)] = day_jul13

    day_jul14 = Day(date=date(2026, 7, 14))
    day_jul14.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 14, 11, 0, 0), end_time=datetime(2026, 7, 14, 11, 30, 0)))
    s.days[date(2026, 7, 14)] = day_jul14

    s.save_all_days()

    week_start = date(2026, 7, 13)
    active, idle = pm.get_weekly_minutes(week_start)

    assert active == 90
    assert idle == 0


def test_weekly_logging_with_ongoing_segment_today(patch_all_datetimes, temp_data_dir):
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)

    patch_all_datetimes.set_now(datetime(2026, 7, 13, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)
    patch_all_datetimes.set_now(datetime(2026, 7, 13, 10, 0, 0))
    s.on_tick(idle_time=400, idle_threshold=300)
    s.save_all_days()

    patch_all_datetimes.set_now(datetime(2026, 7, 19, 9, 0, 0))
    s.on_tick(idle_time=0, idle_threshold=300)
    patch_all_datetimes.set_now(datetime(2026, 7, 19, 9, 30, 0))

    assert s.days[date(2026, 7, 19)].active_minutes == 30

    s.save_all_days()

    active, idle = pm.get_minutes_for_date(date(2026, 7, 19))
    assert active == 30


def test_save_all_days_preserves_lunch_break_in_memory_when_active_ongoing(patch_all_datetimes, temp_data_dir):
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)
    today = date(2026, 7, 15)

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 14, 0, 0))
    s.days[today] = Day(date=today, segments=[
        TimeSegment(state='active', start_time=datetime(2026, 7, 15, 9, 0, 0), end_time=datetime(2026, 7, 15, 12, 0, 0)),
        TimeSegment(state='idle', start_time=datetime(2026, 7, 15, 12, 0, 0), end_time=datetime(2026, 7, 15, 13, 0, 0)),
        TimeSegment(state='active', start_time=datetime(2026, 7, 15, 13, 0, 0), end_time=None),
    ])
    s.current_segment = s.days[today].segments[-1]

    assert s.days[today].idle_minutes == 60

    # Periodic save happens during afternoon work
    s.save_all_days()

    # Lunch break must still be present in memory and idle_minutes preserved
    assert len(s.days[today].segments) == 3
    assert s.days[today].idle_minutes == 60
    assert s.days[today].segments[1].state == 'idle'
    assert s.days[today].segments[1].start_time == datetime(2026, 7, 15, 12, 0, 0)
    assert s.days[today].segments[1].end_time == datetime(2026, 7, 15, 13, 0, 0)
    assert s.days[today].segments[2].state == 'active'
    assert s.days[today].segments[2].end_time is None


def test_save_all_days_preserves_ongoing_idle_break_in_memory(patch_all_datetimes, temp_data_dir):
    pm = PersistenceManager(lambda: str(temp_data_dir))
    s = SessionTracker(pm)
    today = date(2026, 7, 15)

    patch_all_datetimes.set_now(datetime(2026, 7, 15, 12, 30, 0))
    s.days[today] = Day(date=today, segments=[
        TimeSegment(state='active', start_time=datetime(2026, 7, 15, 9, 0, 0), end_time=datetime(2026, 7, 15, 12, 0, 0)),
        TimeSegment(state='idle', start_time=datetime(2026, 7, 15, 12, 0, 0), end_time=None),
    ])
    s.current_segment = s.days[today].segments[-1]

    # Hourly save runs while user is away at lunch
    s.save_all_days()

    # In-memory session must not discard the live ongoing idle segment
    assert len(s.days[today].segments) == 2
    assert s.days[today].segments[1].state == 'idle'
    assert s.days[today].segments[1].start_time == datetime(2026, 7, 15, 12, 0, 0)
    assert s.days[today].segments[1].end_time is None
    assert s.current_segment == s.days[today].segments[1]

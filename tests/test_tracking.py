import os
import sys
import time
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
    get_status_icon,
    hours,
)
from persistence import PersistenceManager

# ============================================================
#  HELPERS
# ============================================================

FROZEN_DAY1 = datetime(2026, 7, 1, 9, 0, 0)     # Wed 2026-07-01 09:00
FROZEN_DAY1_1030 = datetime(2026, 7, 1, 10, 30, 0)
FROZEN_DAY2 = datetime(2026, 7, 2, 0, 0, 5)      # Thu 2026-07-02 00:00:05

def make_session(start_time=None):
    """Create a SessionTracker with a mocked PersistenceManager."""
    pm = MagicMock(spec=PersistenceManager)
    return SessionTracker(pm)

def patch_now(dt):
    """Context manager that patches ``tracking.datetime`` so ``now()`` returns *dt*."""
    return patch('tracking.datetime', **{
        'now.return_value': dt,
        'date': datetime.date,
    })

# ============================================================
#  EXISTING FORMATTING TESTS (Still valid)
# ============================================================

def test_format_hours():
    assert format_hours(3600) == "01:00"
    assert format_hours(5400) == "01:30"
    assert format_hours(86399) == "23:59"

def test_get_status_icon():
    target = 8 * 3600
    assert get_status_icon(is_idle=True, active_today=0, target_work_seconds=target) == "🔴"
    assert get_status_icon(is_idle=False, active_today=10000, target_work_seconds=target) == "🟡"
    assert get_status_icon(is_idle=False, active_today=30000, target_work_seconds=target) == "🟢"

# ============================================================
#  NEW TESTS
# ============================================================

def test_time_segment_duration():
    start = datetime(2026, 7, 1, 9, 0, 0)
    end = datetime(2026, 7, 1, 9, 30, 0)
    segment = TimeSegment(state='active', start_time=start, end_time=end)
    assert segment.duration_minutes == 30

def test_day_properties():
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 0, 0), end_time=datetime(2026, 7, 1, 9, 30, 0)))
    d.segments.append(TimeSegment(state='idle', start_time=datetime(2026, 7, 1, 9, 30, 0), end_time=datetime(2026, 7, 1, 9, 45, 0)))
    d.segments.append(TimeSegment(state='active', start_time=datetime(2026, 7, 1, 9, 45, 0), end_time=datetime(2026, 7, 1, 10, 0, 0)))

    assert d.active_minutes == 45
    assert d.idle_minutes == 15
    assert d.session_start == datetime(2026, 7, 1, 9, 0, 0)
    assert d.session_end == datetime(2026, 7, 1, 10, 0, 0)

def test_session_tracker_tick():
    s = make_session()
    with patch_now(FROZEN_DAY1):
        s.on_tick(idle_time=0, idle_threshold=300)
        assert len(s.days[FROZEN_DAY1.date()].segments) == 1
        assert s.current_segment.state == 'active'

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
        assert day1_segments[-1].end_time.time() == datetime.max.time()

def test_session_tracker_finalize():
    s = make_session()
    with patch_now(FROZEN_DAY1):
        s.on_tick(idle_time=0, idle_threshold=300)
        s.finalize_session()
        s.pm.save_daily_summary.assert_called_once()

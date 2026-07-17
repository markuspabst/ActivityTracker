"""Tests for the data models (models.py)."""

from datetime import datetime, date, timedelta
from unittest.mock import patch

from models import TimeSegment, Day


def test_time_segment_duration_seconds_closed():
    seg = TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 9, 30, 0),
    )
    assert seg.duration_seconds == 1800.0


def test_time_segment_duration_seconds_open_returns_zero():
    seg = TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=None,
    )
    assert seg.duration_seconds == 0.0


def test_time_segment_duration_minutes_closed():
    seg = TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 9, 45, 0),
    )
    assert seg.duration_minutes == 45


def test_time_segment_duration_minutes_open_uses_now():
    now = datetime(2026, 7, 1, 10, 0, 0)
    start = datetime(2026, 7, 1, 9, 35, 0)
    with patch("models.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        seg = TimeSegment(state="active", start_time=start, end_time=None)
        assert seg.duration_minutes == 25


def test_day_active_and_idle_minutes():
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 9, 30, 0),
    ))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 9, 30, 0),
        end_time=datetime(2026, 7, 1, 9, 45, 0),
    ))
    assert d.active_minutes == 30
    assert d.idle_minutes == 15


def test_day_session_start_and_end():
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 8, 0, 0),
        end_time=datetime(2026, 7, 1, 8, 30, 0),
    ))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 0, 0),
    ))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 11, 0, 0),
        end_time=datetime(2026, 7, 1, 12, 0, 0),
    ))
    assert d.session_start == datetime(2026, 7, 1, 9, 0, 0)
    assert d.session_end == datetime(2026, 7, 1, 12, 0, 0)


def test_day_session_start_none_when_no_active():
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 8, 0, 0),
        end_time=datetime(2026, 7, 1, 8, 30, 0),
    ))
    assert d.session_start is None
    assert d.session_end is None


def test_day_session_end_none_when_active_unfinished():
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=None,
    ))
    assert d.session_start == datetime(2026, 7, 1, 9, 0, 0)
    assert d.session_end is None


def test_day_total_active_seconds_closed_only():
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 9, 30, 0),
    ))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 9, 30, 0),
        end_time=datetime(2026, 7, 1, 9, 45, 0),
    ))
    assert d.total_active_seconds() == 1800.0


def test_day_total_active_seconds_includes_ongoing():
    now = datetime(2026, 7, 1, 10, 0, 0)
    start = datetime(2026, 7, 1, 9, 50, 0)
    with patch("models.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        d = Day(date=date(2026, 7, 1))
        d.segments.append(TimeSegment(
            state="active",
            start_time=datetime(2026, 7, 1, 9, 0, 0),
            end_time=datetime(2026, 7, 1, 9, 30, 0),
        ))
        d.segments.append(TimeSegment(
            state="active",
            start_time=start,
            end_time=None,  # ongoing, last segment
        ))
        # 1800 (closed) + 600 (ongoing 9:50 -> 10:00)
        assert d.total_active_seconds() == 2400.0


def test_day_total_active_seconds_ongoing_only_counts_last():
    """Only the LAST segment, if active+open, contributes ongoing time."""
    now = datetime(2026, 7, 1, 10, 0, 0)
    start = datetime(2026, 7, 1, 9, 30, 0)
    with patch("models.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        d = Day(date=date(2026, 7, 1))
        d.segments.append(TimeSegment(
            state="active",
            start_time=start,
            end_time=None,  # open but NOT last -> not counted as ongoing
        ))
        d.segments.append(TimeSegment(
            state="idle",
            start_time=datetime(2026, 7, 1, 9, 45, 0),
            end_time=datetime(2026, 7, 1, 9, 50, 0),
        ))
        assert d.total_active_seconds() == 0.0

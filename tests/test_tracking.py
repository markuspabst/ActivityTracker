import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from unittest.mock import patch
from datetime import datetime, date, timedelta
from tracking import (
    SessionTracker,
    format_hours,
    format_delta,
    get_status_icon,
    hours,
)

# ============================================================
#  HELPERS
# ============================================================

FROZEN_DAY1 = datetime(2026, 7, 1, 9, 0, 0)     # Wed 2026-07-01 09:00
FROZEN_DAY1_1030 = datetime(2026, 7, 1, 10, 30, 0)
FROZEN_DAY2 = datetime(2026, 7, 2, 0, 0, 5)      # Thu 2026-07-02 00:00:05
FROZEN_DAY2_0900 = datetime(2026, 7, 2, 9, 0, 0)


def make_session(start_time=None):
    """Create a SessionTracker with known state, bypassing real `datetime.now()`."""
    s = SessionTracker.__new__(SessionTracker)
    st = start_time or FROZEN_DAY1
    s.start_time = st
    s.last_tick_date = st.date()
    s.first_activity_this_day = None
    s.last_active_time = None
    s.total_idle_session = 0.0
    s.idle_start = None
    s.idle_before_first_activity = 0.0
    s.saved_total_session = 0.0
    s.saved_active_session = 0.0
    s.saved_idle_session = 0.0
    s.last_was_idle = False
    s.previous_is_idle = None
    return s


def patch_now(dt):
    """Context manager that patches ``tracking.datetime`` so ``now()`` returns *dt*."""
    return patch('tracking.datetime', **{
        'now.return_value': dt,
        'date': datetime.date,
    })


# ============================================================
#  EXISTING FORMATTING TESTS
# ============================================================

def test_format_hours():
    assert format_hours(3600) == "01:00"
    assert format_hours(5400) == "01:30"
    assert format_hours(86399) == "23:59"


def test_format_delta():
    assert format_delta(3600) == "+01:00 ✅"
    assert format_delta(-1800) == "-00:30 ⚠️"


def test_get_status_icon():
    target = 8 * 3600
    assert get_status_icon(is_idle=True, active_today=0, target_work_seconds=target) == "🔴"
    assert get_status_icon(is_idle=False, active_today=10000, target_work_seconds=target) == "🟡"
    assert get_status_icon(is_idle=False, active_today=30000, target_work_seconds=target) == "🟢"


def test_hours():
    assert hours(3600) == 1.0
    assert hours(5400) == 1.5


# ============================================================
#  SESSION INIT
# ============================================================

def test_session_init_sets_all_fields():
    """__init__ delegates to reset() which sets correct initial state."""
    s = SessionTracker()
    assert s.start_time is not None
    assert s.last_tick_date is not None
    assert s.first_activity_this_day is None
    assert s.total_idle_session == 0.0
    assert s.idle_start is None
    assert s.idle_before_first_activity == 0.0
    assert s.saved_total_session == 0.0
    assert s.saved_active_session == 0.0
    assert s.saved_idle_session == 0.0


# ============================================================
#  on_tick
# ============================================================

def test_on_tick_same_day_not_idle_sets_first_activity():
    s = make_session()
    with patch_now(FROZEN_DAY1):
        result = s.on_tick(is_idle=False)
    assert result is None
    assert s.first_activity_this_day == FROZEN_DAY1
    assert s.last_tick_date == FROZEN_DAY1.date()


def test_on_tick_same_day_idle_does_not_set_first_activity():
    s = make_session()
    with patch_now(FROZEN_DAY1):
        result = s.on_tick(is_idle=True)
    assert result is None
    assert s.first_activity_this_day is None
    assert s.last_tick_date == FROZEN_DAY1.date()


def test_on_tick_first_activity_already_set_unchanged():
    """first_activity_this_day is never overwritten once set."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1
    with patch_now(FROZEN_DAY1):
        result = s.on_tick(is_idle=True)   # idle = True, but already set
    assert result is None
    assert s.first_activity_this_day == FROZEN_DAY1


def test_on_tick_midnight_rollover_returns_prev_date():
    s = make_session()
    with patch_now(FROZEN_DAY2):
        result = s.on_tick(is_idle=True)
    assert result == FROZEN_DAY1.date()
    assert s.last_tick_date == FROZEN_DAY2.date()


def test_on_tick_midnight_rollover_resets_first_activity():
    """first_activity_this_day is None after rollover — must be re-detected."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1   # was set on previous day
    with patch_now(FROZEN_DAY2):
        s.on_tick(is_idle=True)
    assert s.first_activity_this_day is None


def test_on_tick_midnight_rollover_sets_first_activity_when_not_idle():
    s = make_session()
    with patch_now(FROZEN_DAY2):
        result = s.on_tick(is_idle=False)
    assert result == FROZEN_DAY1.date()
    assert s.first_activity_this_day == FROZEN_DAY2


def test_on_tick_does_not_set_first_activity_after_resume_without_prior_idle():
    s = make_session(start_time=FROZEN_DAY1)
    s.last_was_idle = False
    s.previous_is_idle = False
    with patch_now(FROZEN_DAY1_1030):
        s.on_tick(is_idle=False)
    assert s.first_activity_this_day is None


def test_on_tick_sets_first_activity_after_idle_transition():
    s = make_session(start_time=FROZEN_DAY1)
    s.last_was_idle = False
    s.previous_is_idle = True
    with patch_now(FROZEN_DAY1_1030):
        s.on_tick(is_idle=False)
    assert s.first_activity_this_day == FROZEN_DAY1_1030


def test_on_tick_midnight_rollover_resets_idle_before_first_activity():
    s = make_session()
    s.idle_before_first_activity = 3600.0
    with patch_now(FROZEN_DAY2):
        s.on_tick(is_idle=True)
    assert s.idle_before_first_activity == 0.0


def test_on_tick_midnight_rollover_only_on_first_tick():
    """Multiple ticks on the new day only return None after the first."""
    s = make_session()
    with patch_now(FROZEN_DAY2):
        r1 = s.on_tick(is_idle=True)
    assert r1 == FROZEN_DAY1.date()
    with patch_now(datetime(2026, 7, 2, 0, 1, 0)):
        r2 = s.on_tick(is_idle=True)
    assert r2 is None


# ============================================================
#  reset
# ============================================================

def test_reset_clears_all_state():
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1
    s.total_idle_session = 5000.0
    s.idle_before_first_activity = 1000.0
    s.saved_total_session = 10000.0
    s.saved_active_session = 8000.0
    s.saved_idle_session = 2000.0
    new_time = FROZEN_DAY2
    with patch_now(new_time):
        s.reset()
    assert s.start_time == new_time
    assert s.first_activity_this_day is None
    assert s.total_idle_session == 0.0
    assert s.idle_before_first_activity == 0.0
    assert s.saved_total_session == 0.0
    assert s.saved_active_session == 0.0
    assert s.saved_idle_session == 0.0
    assert s.last_tick_date == new_time.date()
    assert s.idle_start is None


# ============================================================
#  calculate_unsaved_delta
# ============================================================

def test_unsaved_delta_consistency():
    """delta_total always equals delta_active + delta_idle."""
    s = make_session()
    s.mark_saved(100.0, 80.0, 20.0)
    dt, da, di = s.calculate_unsaved_delta(
        total_session=200.0, active_session=150.0, idle_session=30.0,
    )
    assert da == 70.0    # 150 - 80
    assert di == 10.0    # 30 - 20
    assert dt == da + di  # 80 = 70 + 10


def test_unsaved_delta_no_change():
    s = make_session()
    s.mark_saved(100.0, 80.0, 20.0)
    dt, da, di = s.calculate_unsaved_delta(100.0, 80.0, 20.0)
    assert dt == 0.0
    assert da == 0.0
    assert di == 0.0


def test_unsaved_delta_all_active():
    s = make_session()
    s.mark_saved(0.0, 0.0, 0.0)
    dt, da, di = s.calculate_unsaved_delta(3600.0, 3600.0, 0.0)
    assert dt == 3600.0
    assert da == 3600.0
    assert di == 0.0
    assert dt == da + di


def test_unsaved_delta_mixed():
    s = make_session()
    s.mark_saved(7200.0, 6500.0, 700.0)
    dt, da, di = s.calculate_unsaved_delta(10800.0, 9500.0, 1300.0)
    assert da == 3000.0   # 9500 - 6500
    assert di == 600.0    # 1300 - 700
    assert dt == 3600.0   # 3000 + 600


def test_unsaved_delta_before_first_activity():
    """Pre-activity idle is excluded — delta_active and delta_idle can be 0
    even though total_session has grown, and delta_total stays 0 too."""
    s = make_session()
    dt, da, di = s.calculate_unsaved_delta(
        total_session=3600.0, active_session=0.0, idle_session=0.0,
    )
    assert da == 0.0
    assert di == 0.0
    assert dt == 0.0


def test_unsaved_delta_never_negative():
    s = make_session()
    s.mark_saved(100.0, 80.0, 20.0)
    dt, da, di = s.calculate_unsaved_delta(50.0, 30.0, 5.0)
    assert dt == 0.0
    assert da == 0.0
    assert di == 0.0


# ============================================================
#  mark_saved
# ============================================================

def test_mark_saved_updates_watermarks():
    s = make_session()
    s.mark_saved(7200.0, 6500.0, 700.0)
    assert s.saved_total_session == 7200.0
    assert s.saved_active_session == 6500.0
    assert s.saved_idle_session == 700.0


# ============================================================
#  build_report
# ============================================================

def test_build_report_uses_csv_start_time():
    """When CSV has a start_time, it is used even if other sources exist."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1_1030
    csv_data = {
        "2026-07-01": {
            "date": "2026-07-01",
            "start_time": "09:05:00",
            "end_time": "10:00:00",
            "total_seconds": "3300.0",
            "active_seconds": "3000.0",
            "idle_seconds": "300.0",
            "total_hours": "0.92",
            "active_hours": "0.83",
            "idle_hours": "0.08",
            "last_updated": "2026-07-01 10:00:00",
        }
    }
    report = s.build_report(FROZEN_DAY1_1030, 5400.0, 4800.0, 600.0, csv_data)
    assert report["start_time"] == "09:05:00"


def test_build_report_falls_back_to_first_activity():
    """When CSV has no start_time, falls back to first_activity_this_day."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1_1030
    report = s.build_report(FROZEN_DAY1_1030, 5400.0, 4800.0, 600.0, csv_data={})
    assert report["start_time"] == "10:30:00"


def test_build_report_returns_na_when_no_start_time():
    """When CSV has no start_time and no first_activity, report shows N/A."""
    s = make_session(start_time=FROZEN_DAY2)
    report = s.build_report(FROZEN_DAY2, 5.0, 0.0, 0.0, csv_data={})
    assert report["start_time"] == "N/A"


def test_build_report_merges_csv_and_unsaved_delta():
    s = make_session()
    s.mark_saved(100.0, 80.0, 20.0)
    csv_data = {
        "2026-07-01": {
            "date": "2026-07-01",
            "start_time": "09:00:00",
            "end_time": "10:00:00",
            "total_seconds": "3600.0",
            "active_seconds": "3000.0",
            "idle_seconds": "600.0",
            "total_hours": "1.0",
            "active_hours": "0.83",
            "idle_hours": "0.17",
            "last_updated": "2026-07-01 10:00:00",
        }
    }
    now = FROZEN_DAY1_1030
    report = s.build_report(now, 5400.0, 4800.0, 700.0, csv_data)

    expected_da = 4800.0 - 80.0   # 4720
    expected_di = 700.0 - 20.0    # 680
    expected_dt = expected_da + expected_di  # 5400

    assert report["active_seconds"] == 3000.0 + expected_da
    assert report["idle_seconds"] == 600.0 + expected_di
    assert report["total_seconds"] == 3600.0 + expected_dt
    assert report["end_time"] == now.strftime("%H:%M:%S")
    assert report["date"] == "2026-07-01"


# ============================================================
#  calculate_current_session
# ============================================================

def test_calc_current_session_not_idle():
    s = make_session()
    with patch_now(FROZEN_DAY1_1030):
        now, total, active, idle, is_idle = s.calculate_current_session(
            300, lambda: 0,
        )
    assert now == FROZEN_DAY1_1030
    assert total == pytest.approx(5400.0, rel=0.01)  # 1.5 h
    assert active == pytest.approx(5400.0, rel=0.01)
    assert idle == pytest.approx(0.0)
    assert is_idle is False


def test_calc_current_session_all_idle():
    s = make_session()
    with patch_now(FROZEN_DAY1_1030):
        now, total, active, idle, is_idle = s.calculate_current_session(
            300, lambda: 600,  # system idle for 10 min
        )
    assert is_idle is True


def test_calc_current_session_idle_before_first_activity():
    """Idle time before first activity of the day is excluded from reported idle."""
    s = make_session()
    s.first_activity_this_day = None
    s.idle_start = datetime(2026, 7, 1, 9, 0, 0)   # been idle since 9:00
    with patch_now(FROZEN_DAY1_1030):
        now, total, active, idle, is_idle = s.calculate_current_session(
            300, lambda: 600,
        )
    # All 5400 s are pre-activity, so reported idle should be 0
    assert idle == 0.0
    # active should also be 0 since we've been idle the whole time
    assert active == 0.0


def test_calc_current_session_first_activity_stops_pre_activity_accumulation():
    """Once first_activity_this_day is set, idle_start is no longer excluded."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1.replace(hour=9, minute=5)
    s.total_idle_session = 300.0       # 5 min of idle before first activity
    s.idle_before_first_activity = 300.0  # same 5 min was pre-activity
    s.idle_start = None                # currently not idle

    with patch_now(FROZEN_DAY1_1030):
        now, total, active, idle, is_idle = s.calculate_current_session(
            300, lambda: 0,  # not idle now
        )
    # total = 5400, current_idle = 300 (past idle), pre_activity = 300
    # active = 5400 - 300 = 5100
    # reported_idle = 300 - 300 = 0
    assert idle == 0.0
    assert active == pytest.approx(5100.0, rel=0.01)


def test_calc_current_session_updates_last_active_time():
    """When the user is active, last_active_time is updated to now."""
    s = make_session()
    t = FROZEN_DAY1_1030
    with patch_now(t):
        s.calculate_current_session(300, lambda: 0)  # not idle
    assert s.last_active_time == t


def test_calc_current_session_does_not_update_last_active_time_when_idle():
    """When idle, last_active_time stays frozen at its previous value."""
    s = make_session()
    s.last_active_time = datetime(2026, 7, 1, 17, 0, 0)

    with patch_now(datetime(2026, 7, 1, 17, 30, 0)):
        s.calculate_current_session(300, lambda: 600)  # idle

    assert s.last_active_time == datetime(2026, 7, 1, 17, 0, 0)


def test_calc_last_active_time_updates_when_idle_ends():
    """When idle ends and user becomes active again, last_active_time updates."""
    s = make_session()
    s.last_active_time = datetime(2026, 7, 1, 10, 0, 0)
    s.idle_start = datetime(2026, 7, 1, 10, 5, 0)

    t = datetime(2026, 7, 1, 10, 30, 0)
    with patch_now(t):
        s.calculate_current_session(300, lambda: 0)  # back!

    assert s.last_active_time == t


def test_build_report_end_time_uses_last_active_time():
    """When last_active_time is set, it appears as the report end_time."""
    s = make_session()
    s.last_active_time = datetime(2026, 7, 1, 17, 0, 0)
    report = s.build_report(
        now=datetime(2026, 7, 1, 18, 0, 0),
        total_session=100.0, active_session=80.0, idle_session=20.0,
        csv_data={},
    )
    assert report["end_time"] == "17:00:00"


def test_build_report_end_time_falls_back_to_now():
    """When no last_active_time exists, end_time falls back to now."""
    s = make_session()
    report = s.build_report(
        now=FROZEN_DAY1_1030,
        total_session=100.0, active_session=80.0, idle_session=20.0,
        csv_data={},
    )
    assert report["end_time"] == FROZEN_DAY1_1030.strftime("%H:%M:%S")


# ============================================================
#  IDLE DETECTION & ACCUMULATION
# ============================================================

def test_idle_just_detected_sets_idle_start():
    """On the first tick where idle_time > threshold, idle_start is set
    and no idle seconds have accumulated yet."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1

    t = datetime(2026, 7, 1, 10, 10, 0)
    with patch_now(t):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)

    # The tracker computes the true idle start as "now - idle_time".
    assert s.idle_start == t - timedelta(seconds=600)
    assert s.total_idle_session == 0.0
    assert is_idle is True


def test_idle_ongoing_accumulates_current_idle():
    """During an ongoing idle period, ``current_idle = (now - idle_start)``
    grows every tick."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1
    s.idle_start = datetime(2026, 7, 1, 10, 10, 0)  # idle first detected

    t = datetime(2026, 7, 1, 10, 30, 0)  # 20 min later
    with patch_now(t):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)

    # current_idle = 0 + (10:30 - 10:10) = 1200 s
    assert idle == pytest.approx(1200.0, rel=0.01)
    # total = (10:30 - 09:00) = 5400 → active = 5400 - 1200 = 4200
    assert active == pytest.approx(4200.0, rel=0.01)
    assert total == pytest.approx(5400.0, rel=0.01)
    assert is_idle is True


def test_idle_ongoing_accumulates_more_over_time():
    """As idle persists, current_idle keeps growing."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1
    s.idle_start = datetime(2026, 7, 1, 10, 10, 0)

    t = datetime(2026, 7, 1, 11, 0, 0)  # 50 min later
    with patch_now(t):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)

    elapsed = (t - s.idle_start).total_seconds()  # 3000 s
    assert idle == pytest.approx(elapsed, rel=0.01)
    assert is_idle is True


def test_idle_period_ends_updates_total_idle_and_resets_idle_start():
    """When the user becomes active again, idle_start is cleared and the
    elapsed idle seconds are moved into total_idle_session."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1
    s.idle_start = datetime(2026, 7, 1, 10, 10, 0)

    t = datetime(2026, 7, 1, 10, 30, 0)  # user returns
    with patch_now(t):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)

    # 20 min idle completed
    assert s.total_idle_session == pytest.approx(1200.0, rel=0.01)
    assert s.idle_start is None
    assert is_idle is False

    # current_idle = total_idle_session = 1200 (no running idle)
    # total = 5400 → active = 5400 - 1200 = 4200
    assert idle == pytest.approx(1200.0, rel=0.01)
    assert active == pytest.approx(4200.0, rel=0.01)


def test_idle_period_ends_updates_idle_before_first_activity():
    """When idle ends and no activity has occurred yet, the elapsed idle
    is also tracked in idle_before_first_activity (for exclusion later)."""
    s = make_session()
    s.first_activity_this_day = None
    s.idle_start = datetime(2026, 7, 1, 9, 0, 0)

    t = datetime(2026, 7, 1, 10, 0, 0)  # user's first activity
    with patch_now(t):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)

    assert s.total_idle_session == pytest.approx(3600.0, rel=0.01)
    assert s.idle_before_first_activity == pytest.approx(3600.0, rel=0.01)
    # first_activity_this_day is set *on* this tick (in on_tick, not here)
    # reported_idle = 3600 - 3600 = 0
    assert idle == 0.0


def test_multiple_idle_periods_accumulate():
    """Consecutive idle periods stack in total_idle_session."""
    s = make_session()
    s.first_activity_this_day = FROZEN_DAY1

    # Idle period 1: 10:05 → 10:15 (600 s)
    s.total_idle_session = 600.0
    s.idle_start = None

    # Idle period 2 starts: 11:05
    s.idle_start = datetime(2026, 7, 1, 11, 5, 0)

    # 11:20 — still idle (15 min into 2nd period)
    t = datetime(2026, 7, 1, 11, 20, 0)
    with patch_now(t):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)

    # current_idle = 600 (period 1) + (11:20 - 11:05) = 600 + 900 = 1500
    # total = (11:20 - 09:00) = 8400 → active = 8400 - 1500 = 6900
    assert idle == pytest.approx(1500.0, rel=0.01)
    assert active == pytest.approx(6900.0, rel=0.01)
    assert is_idle is True

    # Second period ends at 11:30
    s.idle_start = datetime(2026, 7, 1, 11, 5, 0)
    t = datetime(2026, 7, 1, 11, 30, 0)
    with patch_now(t):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)

    assert s.total_idle_session == pytest.approx(600.0 + 1500.0, rel=0.01)  # period 1 + period 2
    assert s.idle_start is None
    assert idle == pytest.approx(2100.0, rel=0.01)  # all past idle
    # total = (11:30 - 09:00) = 9000 → active = 9000 - 2100 = 6900
    assert active == pytest.approx(6900.0, rel=0.01)


# ============================================================
#  FULL-DAY SCENARIO SIMULATIONS
# ============================================================

def test_scenario_active_then_idle_then_active():
    """Realistic sequence: work → break → work, verifying state at each step."""
    s = make_session(start_time=FROZEN_DAY1)
    s.first_activity_this_day = FROZEN_DAY1

    # ── 09:00 → 10:00 working (all active) ──
    t1 = datetime(2026, 7, 1, 10, 0, 0)
    with patch_now(t1):
        n1, total1, act1, idl1, _ = s.calculate_current_session(300, lambda: 0)
    assert act1 == pytest.approx(3600.0, rel=0.01)
    assert idl1 == pytest.approx(0.0, rel=0.01)
    assert s.last_active_time == t1

    # ── 10:05 idle FIRST detected (system idle crosses threshold) ──
    tidle_start = datetime(2026, 7, 1, 10, 5, 0)
    with patch_now(tidle_start):
        s.calculate_current_session(300, lambda: 360)
        # idle_start is computed as now - idle_time (360s => 6 minutes earlier)
        assert s.idle_start == tidle_start - timedelta(seconds=360)
    assert s.total_idle_session == 0.0

    # ── 10:20 idle ongoing (15 min of idle accumulated) ──
    t2 = datetime(2026, 7, 1, 10, 20, 0)
    with patch_now(t2):
        n2, total2, act2, idl2, is_idle2 = s.calculate_current_session(300, lambda: 600)
    assert idl2 == pytest.approx(1260.0, rel=0.01)    # 21 min (computed from last input)
    assert is_idle2 is True
    assert s.last_active_time == t1                   # frozen at 10:00

    # ── 10:30 user returns (idle ends) ──
    t3 = datetime(2026, 7, 1, 10, 30, 0)
    with patch_now(t3):
        n3, total3, act3, idl3, is_idle3 = s.calculate_current_session(300, lambda: 0)
    assert s.total_idle_session == pytest.approx(1860.0, rel=0.01)  # 31 min total idle
    assert s.idle_start is None
    assert idl3 == pytest.approx(1860.0, rel=0.01)
    assert act3 == pytest.approx(3540.0, rel=0.01)    # 5400 - 1860 = 3540
    assert is_idle3 is False
    assert s.last_active_time == t3                   # updated to return time


def test_scenario_multiple_breaks():
    """Work → short break → work → lunch → work → end of day."""
    s = make_session(start_time=FROZEN_DAY1)
    s.first_activity_this_day = FROZEN_DAY1

    # ── 09:00 → 11:00 work (2 h, all active) ──
    with patch_now(datetime(2026, 7, 1, 11, 0, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)
    assert active == pytest.approx(7200.0, rel=0.01)
    assert idle == 0.0

    # ── 11:05 → 11:15 coffee break (10 min idle) ──
    s.total_idle_session = 600.0
    s.idle_before_first_activity = 0.0
    # idle completed: no ongoing idle
    s.idle_start = None

    # ── 11:15 → 12:00 work ──
    with patch_now(datetime(2026, 7, 1, 12, 0, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)
    # total = (12:00 - 09:00) = 10800
    # current_idle = 600 (coffee break), active = 10800 - 600 = 10200
    assert active == pytest.approx(10200.0, rel=0.01)
    assert idle == pytest.approx(600.0, rel=0.01)

    # ── 12:05 → 13:00 lunch (55 min idle) ──
    # First, set idle detection start
    s.idle_start = datetime(2026, 7, 1, 12, 5, 0)

    # 13:00 — idle ongoing (55 min running)
    with patch_now(datetime(2026, 7, 1, 13, 0, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)
    # current_idle = 600 (coffee) + (13:00 - 12:05) = 600 + 3300 = 3900
    # total = (13:00 - 09:00) = 14400
    # active = 14400 - 3900 = 10500
    # reported_idle = 3900
    assert idle == pytest.approx(3900.0, rel=0.01)
    assert active == pytest.approx(10500.0, rel=0.01)
    assert is_idle is True

    # 13:00 user returns from lunch
    s.idle_start = datetime(2026, 7, 1, 12, 5, 0)
    with patch_now(datetime(2026, 7, 1, 13, 0, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)
    # lunch elapsed = (13:00 - 12:05) = 3300 → total_idle_session = 600 + 3300 = 3900
    assert s.total_idle_session == pytest.approx(3900.0, rel=0.01)
    assert s.idle_start is None

    # ── 13:00 → 16:30 afternoon work ──
    with patch_now(datetime(2026, 7, 1, 16, 30, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)
    # total = (16:30 - 09:00) = 7.5 h = 27000
    # active = 27000 - 3900 = 23100 (= 6h 25min)
    # idle = 3900 (= 1h 5min: 10 min coffee + 55 min lunch)
    assert active == pytest.approx(23100.0, rel=0.01)
    assert idle == pytest.approx(3900.0, rel=0.01)
    assert is_idle is False


def test_scenario_overnight_idle_before_first_activity():
    """Overnight idle is excluded from reported idle until first activity.
    Once first activity happens, subsequent idle IS counted."""
    s = make_session(start_time=FROZEN_DAY1)
    s.last_tick_date = FROZEN_DAY1.date()

    # ── User is idle at 09:00 (computer on, nobody there) ──
    s.idle_start = datetime(2026, 7, 1, 9, 0, 0)

    # 09:30 — still idle
    with patch_now(datetime(2026, 7, 1, 9, 30, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)
    # All pre-activity → idle = 0, active = 0
    assert idle == 0.0
    assert active == 0.0
    assert is_idle is True

    # ── 10:00 — user sits down (first activity at 09:55, now idle_end) ──
    # Simulate idle period ending → first_activity set in on_tick
    with patch_now(datetime(2026, 7, 1, 10, 0, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)
    # idle ended: elapsed = (10:00 - 09:00) = 3600 → total_idle_session = 3600
    # idle_before_first_activity = 3600 (since first_activity_this_day was None)
    assert s.total_idle_session == pytest.approx(3600.0, rel=0.01)
    assert s.idle_before_first_activity == pytest.approx(3600.0, rel=0.01)
    # reported_idle = current_idle - pre_activity = 3600 - 3600 = 0
    assert idle == 0.0
    assert is_idle is False

    # Now simulate on_tick setting first_activity_this_day
    with patch_now(datetime(2026, 7, 1, 10, 0, 0)):
        s.on_tick(is_idle=False)
    assert s.first_activity_this_day == datetime(2026, 7, 1, 10, 0, 0)

    # ── 11:00 — user goes idle again ──
    s.idle_start = datetime(2026, 7, 1, 11, 5, 0)
    with patch_now(datetime(2026, 7, 1, 11, 20, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)
    # current_idle = 3600 (overnight) + 900 (this break) = 4500
    # pre_activity = 3600 (only the overnight part)
    # reported_idle = 4500 - 3600 = 900 ← the break IS counted
    assert idle == pytest.approx(900.0, rel=0.01)
    assert is_idle is True


def test_scenario_no_activity_all_day():
    """Full day without any user activity — nothing should be reported
    as active or idle time."""
    s = make_session(start_time=FROZEN_DAY1)
    s.idle_start = FROZEN_DAY1  # idle from the start

    t = datetime(2026, 7, 1, 17, 0, 0)  # end of day
    with patch_now(t):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)

    # All 8h are pre-activity, first_activity is None
    assert idle == 0.0
    assert active == 0.0
    assert is_idle is True

    # delta should be zero too
    dt, da, di = s.calculate_unsaved_delta(total, active, idle)
    assert da == 0.0
    assert di == 0.0
    assert dt == 0.0


def test_scenario_end_time_tracks_last_active_moment():
    """The CSV end_time should reflect the last active time, not the
    save time. Using the app's _do_save_delta flow: ``last_active_time``
    is passed to ``add_delta_to_csv``."""
    s = make_session(start_time=FROZEN_DAY1)
    s.first_activity_this_day = FROZEN_DAY1

    # Active from 09:00 → 12:00
    with patch_now(datetime(2026, 7, 1, 12, 0, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)
    assert s.last_active_time == datetime(2026, 7, 1, 12, 0, 0)

    # Idle at 12:05 → 14:00 (lunch)
    s.idle_start = datetime(2026, 7, 1, 12, 5, 0)
    with patch_now(datetime(2026, 7, 1, 14, 0, 0)):
        n, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)

    # last_active_time frozen at 12:00 despite saving at 14:00
    assert s.last_active_time == datetime(2026, 7, 1, 12, 0, 0)


# ============================================================
#  INTEGRATION — midnight rollover through save → reset
# ============================================================

def test_midnight_scenario_save_prev_day_then_reset():
    """Simulate the app-layer flow that our fix implements:

    Day 1 09:00 – session started, user works
    Day 1 10:00 – first save watermark
    Day 1 17:00 – user goes idle
    Day 2 00:00:05 – tick fires → on_tick returns prev_date
    → caller saves delta to Day 1, calls reset()
    → new day tracks from midnight with fresh counters
    """
    s = make_session(start_time=FROZEN_DAY1)

    # -- Day 1: user becomes active --
    with patch_now(FROZEN_DAY1):
        s.on_tick(is_idle=False)
    assert s.first_activity_this_day == FROZEN_DAY1

    # -- Day 1 10:00: first save (watermark) --
    ts10 = datetime(2026, 7, 1, 10, 0, 0)
    with patch_now(ts10):
        now, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 0)
    s.mark_saved(total, active, idle)
    assert s.saved_total_session == pytest.approx(3600.0, rel=0.01)  # 1 hour

    # -- Day 1 17:00: user goes idle (no save, just idle time accumulating) --
    ts17 = datetime(2026, 7, 1, 17, 0, 0)
    with patch_now(ts17):
        now, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)
    assert is_idle is True
    idle_at_17 = s.total_idle_session

    # -- MIDNIGHT: Day 2 00:00:05 --
    # Calculate session (still Day 1's state), then on_tick detects rollover
    with patch_now(FROZEN_DAY2):
        # calculate_current_session sees old first_activity_this_day
        now, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)
        prev_date = s.on_tick(is_idle=is_idle)

    assert prev_date == FROZEN_DAY1.date()  # ← must return previous day

    # Compute unsaved delta that would be written to Day 1's CSV row
    dt, da, di = s.calculate_unsaved_delta(total, active, idle)
    assert dt == da + di  # invariant holds
    assert da >= 0
    assert di >= 0

    # -- Caller saves delta to prev_date, then resets --
    s.mark_saved(total, active, idle)   # <-- what _do_save_delta does
    with patch_now(FROZEN_DAY2):
        s.reset()
    # All counters are cleared for the new day
    assert s.start_time == FROZEN_DAY2
    assert s.first_activity_this_day is None
    assert s.saved_total_session == 0.0

    # -- Day 2 09:00: user becomes active --
    with patch_now(FROZEN_DAY2_0900):
        s.on_tick(is_idle=False)
    assert s.first_activity_this_day == FROZEN_DAY2_0900

    # Build report — start_time should show first activity of Day 2
    with patch_now(FROZEN_DAY2_0900):
        now2, total2, active2, idle2, _ = s.calculate_current_session(300, lambda: 0)
    report = s.build_report(now2, total2, active2, idle2, csv_data={})
    assert report["start_time"] == "09:00:00"


def test_unsaved_delta_consistency_after_midnight_without_first_activity():
    """If the save interval fires before any activity on the new day,
    delta_total = delta_active + delta_idle, and with no activity
    all three are 0."""
    s = make_session(start_time=datetime(2026, 7, 2, 0, 0, 5))
    s.last_tick_date = date(2026, 7, 2)
    s.idle_start = datetime(2026, 7, 2, 0, 0, 5)  # been idle since start

    # 30 minutes pass, user idle the whole time
    t = datetime(2026, 7, 2, 0, 30, 0)
    with patch_now(t):
        now, total, active, idle, is_idle = s.calculate_current_session(300, lambda: 600)

    # All 30 min are pre-activity idle → reported_idle = 0, active = 0
    assert idle == 0.0
    assert active == 0.0

    # delta_total must also be 0 (not the raw total_session)
    dt, da, di = s.calculate_unsaved_delta(total, active, idle)
    assert da == 0.0
    assert di == 0.0
    assert dt == 0.0


# ============================================================
#  write_state (data dict shape)
# ============================================================

def test_write_state_shape():
    """write_state produces the expected dict structure."""
    s = make_session()
    now = FROZEN_DAY1_1030
    with patch('tracking.write_state') as mock_write:
        s.write_state(now, 5400.0, 4800.0, 600.0, dirty=True)

    args, _ = mock_write.call_args
    state = args[0]
    assert state["dirty"] is True
    assert state["date"] == "2026-07-01"
    assert state["session_start"] == FROZEN_DAY1.isoformat()
    assert state["last_active_time"] is None  # Never been active
    assert state["total_session"] == 5400.0
    assert state["active_session"] == 4800.0
    assert state["idle_session"] == 600.0
    assert state["saved_total_session"] == 0.0
    assert state["saved_active_session"] == 0.0
    assert state["saved_idle_session"] == 0.0


def test_write_state_includes_last_active_time():
    """When last_active_time is set, it is serialized in the state."""
    s = make_session()
    s.last_active_time = datetime(2026, 7, 1, 17, 0, 0)
    now = datetime(2026, 7, 1, 17, 30, 0)
    with patch('tracking.write_state') as mock_write:
        s.write_state(now, 100.0, 80.0, 20.0, dirty=True)

    args, _ = mock_write.call_args
    state = args[0]
    assert state["last_active_time"] == "2026-07-01T17:00:00"
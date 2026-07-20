"""Comprehensive tests for the CSV persistence layer (persistence.py)."""

import csv
import os
from datetime import datetime, date, timedelta
from pathlib import Path

import pytest

from persistence import PersistenceManager
from models import TimeSegment, Day


@pytest.fixture
def pm(tmp_path):
    return PersistenceManager(lambda: str(tmp_path))


def _write_raw(pm, year, header, rows):
    """Write a raw CSV (header + rows) bypassing the normal writer."""
    path = pm.get_log_file_path("activities", year)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    return path


# ------------------------------------------------------------
# Path handling
# ------------------------------------------------------------

def test_get_log_file_path_format(pm, tmp_path):
    p = pm.get_log_file_path("activities", 2026)
    assert isinstance(p, Path)
    assert str(p) == os.path.join(str(tmp_path), "activities-2026.csv")


def test_get_log_file_path_is_cached(pm):
    p1 = pm.get_log_file_path("activities", 2026)
    p2 = pm.get_log_file_path("activities", 2026)
    # The string path is cached, so repeated calls return an equal Path
    assert p1 == p2
    assert "activities-2026" in pm._path_cache


def test_get_log_file_path_respects_prefix(pm, tmp_path):
    p = pm.get_log_file_path("otherprefix", 2025)
    assert str(p) == os.path.join(str(tmp_path), "otherprefix-2025.csv")


def test_get_data_dir(pm, tmp_path):
    assert pm.get_data_dir() == str(tmp_path)


# ------------------------------------------------------------
# Saving
# ------------------------------------------------------------

def test_save_segments_empty_is_noop(pm, tmp_path):
    pm.save_segments({})
    # No file should be created for an empty dict
    assert not os.path.exists(os.path.join(str(tmp_path), "activities-2026.csv"))


def test_save_segments_skips_segments_without_start_time(pm, tmp_path):
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(state="active", start_time=None))
    pm.save_segments({date(2026, 7, 1): d})
    path = pm.get_log_file_path("activities", 2026)
    assert os.path.exists(path)
    with open(path) as f:
        lines = f.readlines()
    # Only header, no data rows
    assert len(lines) == 1


def test_save_segments_writes_header_and_rows(pm, tmp_path):
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 0, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d})

    path = pm.get_log_file_path("activities", 2026)
    with open(path) as f:
        lines = f.readlines()
    assert lines[0].strip() == "date,state,start,end,duration_min,duration_seconds"
    assert "2026-07-01" in lines[1]
    assert "active" in lines[1]
    assert "09:00:00" in lines[1] and "10:00:00" in lines[1]
    assert "60" in lines[1]      # duration_min
    assert "3600" in lines[1]    # duration_seconds


def test_save_segments_splits_by_year(pm, tmp_path):
    d1 = Day(date=date(2026, 12, 31))
    d1.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 12, 31, 23, 0, 0),
        end_time=datetime(2026, 12, 31, 23, 30, 0),
    ))
    d2 = Day(date=date(2027, 1, 1))
    d2.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2027, 1, 1, 0, 0, 0),
        end_time=datetime(2027, 1, 1, 0, 30, 0),
    ))
    pm.save_segments({date(2026, 12, 31): d1, date(2027, 1, 1): d2})
    assert os.path.exists(pm.get_log_file_path("activities", 2026))
    assert os.path.exists(pm.get_log_file_path("activities", 2027))


def test_save_segments_is_idempotent_and_merges(pm, tmp_path):
    """Re-saving the same day must not duplicate rows (keyed by date+start)."""
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 9, 30, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d})
    # Save again with the same single segment
    pm.save_segments({date(2026, 7, 1): d})

    segs = pm.read_segments_for_day(date(2026, 7, 1))
    assert len(segs) == 1


def test_save_segments_preserves_existing_and_adds_new(pm, tmp_path):
    d1 = Day(date=date(2026, 7, 1))
    d1.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 9, 30, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d1})

    d2 = Day(date=date(2026, 7, 1))
    d2.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 10, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 15, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d2})

    segs = pm.read_segments_for_day(date(2026, 7, 1))
    assert len(segs) == 2


def test_save_segments_legacy_migration_adds_duration_seconds(pm, tmp_path):
    """Legacy CSV rows without a duration_seconds column should be migrated.

    save_segments() returns early on an empty dict, so we must actually save a
    (different) segment for the same year to force the existing-file read/merge
    path that performs the migration.
    """
    _write_raw(
        pm, 2026,
        ["date", "state", "start", "end", "duration_min"],
        [["2026-07-01", "active", "09:00:00", "10:00:00", "60"]],  # legacy, no duration_seconds
    )
    # Save a separate segment for the same year so the merge path runs
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 8, 0, 0),   # different key -> preserved
        end_time=datetime(2026, 7, 1, 8, 15, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d})

    path = pm.get_log_file_path("activities", 2026)
    with open(path) as f:
        reader = csv.DictReader(f)
        rows = {r["start"]: r for r in reader}
    # The legacy 09:00:00 row must now carry a migrated duration_seconds field
    assert "duration_seconds" in rows["09:00:00"]
    assert rows["09:00:00"]["duration_seconds"] == "60"


# ------------------------------------------------------------
# Reading
# ------------------------------------------------------------

def test_read_segments_for_day_roundtrip(pm, tmp_path):
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 0, 0),
    ))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 10, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 30, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d})

    segs = pm.read_segments_for_day(date(2026, 7, 1))
    assert len(segs) == 2
    assert segs[0].state == "active"
    assert segs[0].start_time == datetime(2026, 7, 1, 9, 0, 0)
    assert segs[0].end_time == datetime(2026, 7, 1, 10, 0, 0)
    assert segs[1].state == "idle"
    assert segs[1].end_time == datetime(2026, 7, 1, 10, 30, 0)


def test_read_segments_ongoing_has_no_end_time(pm, tmp_path):
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=None,
    ))
    pm.save_segments({date(2026, 7, 1): d})

    segs = pm.read_segments_for_day(date(2026, 7, 1))
    assert len(segs) == 1
    assert segs[0].end_time is None
    assert segs[0].state == "active"


def test_read_segments_missing_file_returns_empty(pm, tmp_path):
    assert pm.read_segments_for_day(date(2026, 1, 1)) == []


def test_read_segments_skips_malformed_rows(pm, tmp_path):
    _write_raw(
        pm, 2026,
        ["date", "state", "start", "end", "duration_min", "duration_seconds"],
        [
            ["2026-07-01", "active", "badtime", "", "0", "0"],   # malformed start
            ["2026-07-01", "active", "09:00:00", "10:00:00", "60", "3600"],  # valid
        ],
    )
    segs = pm.read_segments_for_day(date(2026, 7, 1))
    assert len(segs) == 1
    assert segs[0].start_time == datetime(2026, 7, 1, 9, 0, 0)


def test_read_segments_only_target_day(pm, tmp_path):
    d1 = Day(date=date(2026, 7, 1))
    d1.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 9, 30, 0),
    ))
    d2 = Day(date=date(2026, 7, 2))
    d2.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 2, 9, 0, 0),
        end_time=datetime(2026, 7, 2, 9, 30, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d1, date(2026, 7, 2): d2})

    segs = pm.read_segments_for_day(date(2026, 7, 1))
    assert len(segs) == 1
    assert segs[0].start_time.date() == date(2026, 7, 1)


def test_read_segments_for_day_path_is_a_directory(pm, tmp_path):
    """If the CSV path is a directory (not a file), reading must not crash."""
    path = pm.get_log_file_path("activities", 2026)
    os.makedirs(path)  # simulate a directory occupying the CSV path
    assert pm.read_segments_for_day(date(2026, 7, 1)) == []


# ------------------------------------------------------------
# get_minutes_for_date
# ------------------------------------------------------------

def test_get_minutes_for_date_missing_file(pm, tmp_path):
    assert pm.get_minutes_for_date(date(2026, 1, 1)) == (0, 0)


def test_get_minutes_for_date_filters_by_state(pm, tmp_path):
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 9, 30, 0),
    ))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 10, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 15, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d})
    active, idle = pm.get_minutes_for_date(date(2026, 7, 1))
    assert active == 30
    assert idle == 15


def test_get_minutes_for_date_bad_duration_is_ignored(pm, tmp_path):
    """A corrupt duration_seconds value must not crash the reader (row ignored)."""
    _write_raw(
        pm, 2026,
        ["date", "state", "start", "end", "duration_min", "duration_seconds"],
        [["2026-07-01", "active", "09:00:00", "10:00:00", "60", "notanint"]],
    )
    # duration_seconds fails to parse -> that row contributes 0, call returns (0,0)
    assert pm.get_minutes_for_date(date(2026, 7, 1)) == (0, 0)


# ------------------------------------------------------------
# get_weekly_minutes
# ------------------------------------------------------------

def test_get_weekly_minutes_missing_file(pm, tmp_path):
    week_start = date(2026, 7, 6)
    assert pm.get_weekly_minutes(week_start) == (0, 0)


def test_get_weekly_minutes_aggregates_week(pm, tmp_path):
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 0, 0),
    ))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 10, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 30, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d})

    week_start = date(2026, 7, 1) - timedelta(days=date(2026, 7, 1).weekday())
    active, idle = pm.get_weekly_minutes(week_start)
    assert active == 60
    assert idle == 30


def test_get_weekly_minutes_only_in_range(pm, tmp_path):
    """Segments outside the week window must be excluded."""
    # In-range day
    d_in = Day(date=date(2026, 7, 1))
    d_in.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 0, 0),
    ))
    # Out-of-range day (different week)
    d_out = Day(date=date(2026, 7, 15))
    d_out.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 15, 9, 0, 0),
        end_time=datetime(2026, 7, 15, 10, 0, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d_in, date(2026, 7, 15): d_out})

    week_start = date(2026, 7, 1) - timedelta(days=date(2026, 7, 1).weekday())
    active, _ = pm.get_weekly_minutes(week_start)
    assert active == 60


def test_get_weekly_minutes_spans_year_boundary(pm, tmp_path):
    d_dec = Day(date=date(2026, 12, 28))  # Monday, start of a cross-year week
    d_dec.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 12, 28, 9, 0, 0),
        end_time=datetime(2026, 12, 28, 10, 0, 0),
    ))
    d_jan = Day(date=date(2027, 1, 1))
    d_jan.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2027, 1, 1, 9, 0, 0),
        end_time=datetime(2027, 1, 1, 9, 30, 0),
    ))
    pm.save_segments({date(2026, 12, 28): d_dec, date(2027, 1, 1): d_jan})

    week_start = date(2026, 12, 28)
    active, _ = pm.get_weekly_minutes(week_start)
    assert active == 90  # 60 (Dec) + 30 (Jan)


def test_get_weekly_minutes_bad_duration_is_ignored(pm, tmp_path):
    _write_raw(
        pm, 2026,
        ["date", "state", "start", "end", "duration_min", "duration_seconds"],
        [["2026-07-01", "active", "09:00:00", "10:00:00", "60", "notanint"]],
    )
    week_start = date(2026, 7, 1)
    assert pm.get_weekly_minutes(week_start) == (0, 0)


# ------------------------------------------------------------
# Aggregates (get_minutes_for_date / get_weekly_minutes)
# These are sourced directly from the activities segment log; there is no
# separate daily-summary file anymore.
# ------------------------------------------------------------

def test_get_minutes_for_date_derives_from_activities_log(pm, tmp_path):
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 0, 0),
    ))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 10, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 15, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d})

    active, idle = pm.get_minutes_for_date(date(2026, 7, 1))
    assert active == 60
    assert idle == 15

    # No separate daily-summary file should be written.
    assert not os.path.exists(pm.get_log_file_path("daily", 2026))


def test_get_minutes_for_date_floors_seconds_like_daily_summary(pm, tmp_path):
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 9, 0, 59),  # 59s -> 0 minutes
    ))
    d.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 1, 9, 1, 0),
        end_time=datetime(2026, 7, 1, 9, 1, 30),  # 30s -> 0 minutes
    ))
    pm.save_segments({date(2026, 7, 1): d})

    active, idle = pm.get_minutes_for_date(date(2026, 7, 1))
    assert active == 0
    assert idle == 0


def test_get_weekly_minutes_sums_days_from_activities_log(pm, tmp_path):
    d1 = Day(date=date(2026, 7, 1))
    d1.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 0, 0),
    ))
    d2 = Day(date=date(2026, 7, 3))
    d2.segments.append(TimeSegment(
        state="idle",
        start_time=datetime(2026, 7, 3, 9, 0, 0),
        end_time=datetime(2026, 7, 3, 9, 45, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d1, date(2026, 7, 3): d2})

    active, idle = pm.get_weekly_minutes(date(2026, 6, 29))
    assert active == 60
    assert idle == 45


def test_save_segments_drops_inner_segment_covered_by_merged(pm, tmp_path):
    """A merged/extended segment must not leave an overlapping inner row behind."""
    # Seed a file with an outer segment and an inner one (e.g. legacy/corrupt overlap)
    _write_raw(
        pm, 2026,
        ["date", "state", "start", "end", "duration_min", "duration_seconds"],
        [
            ["2026-07-01", "active", "09:00:00", "09:30:00", "30", "1800"],
            ["2026-07-01", "idle", "09:15:00", "09:25:00", "10", "600"],
        ],
    )
    # Now persist an extended active segment 09:00-10:00 that covers the inner one
    d = Day(date=date(2026, 7, 1))
    d.segments.append(TimeSegment(
        state="active",
        start_time=datetime(2026, 7, 1, 9, 0, 0),
        end_time=datetime(2026, 7, 1, 10, 0, 0),
    ))
    pm.save_segments({date(2026, 7, 1): d})

    segs = pm.read_segments_for_day(date(2026, 7, 1))
    assert len(segs) == 1
    assert segs[0].start_time == datetime(2026, 7, 1, 9, 0, 0)
    assert segs[0].end_time == datetime(2026, 7, 1, 10, 0, 0)


def test_readers_survive_unreadable_log_file(pm, tmp_path):
    """A corrupt/unreadable activities log must not raise; return empty."""
    # Point the 2026 activities log at a directory so open() fails.
    real_path = pm.get_log_file_path("activities", 2026)
    os.makedirs(real_path, exist_ok=True)
    # get_minutes_for_date / read_segments_for_day should return empty, not raise
    assert pm.get_minutes_for_date(date(2026, 7, 1)) == (0, 0)
    assert pm.read_segments_for_day(date(2026, 7, 1)) == []


# ------------------------------------------------------------
# merge_segments_to_save (static)
# ------------------------------------------------------------

def test_merge_segments_to_save_empty():
    assert PersistenceManager.merge_segments_to_save([]) == []


def test_merge_segments_to_save_different_states_not_merged():
    segs = [
        TimeSegment(state="active", start_time=datetime(2026, 7, 1, 9, 0, 0),
                    end_time=datetime(2026, 7, 1, 9, 30, 0)),
        TimeSegment(state="idle", start_time=datetime(2026, 7, 1, 9, 30, 0),
                    end_time=datetime(2026, 7, 1, 10, 0, 0)),
    ]
    assert len(PersistenceManager.merge_segments_to_save(segs, 300)) == 2


def test_merge_segments_to_save_merges_small_gap():
    segs = [
        TimeSegment(state="active", start_time=datetime(2026, 7, 1, 9, 0, 0),
                    end_time=datetime(2026, 7, 1, 9, 30, 0)),
        TimeSegment(state="active", start_time=datetime(2026, 7, 1, 9, 31, 0),
                    end_time=datetime(2026, 7, 1, 10, 0, 0)),
    ]
    merged = PersistenceManager.merge_segments_to_save(segs, 300)
    assert len(merged) == 1
    assert merged[0].end_time == datetime(2026, 7, 1, 10, 0, 0)


def test_merge_segments_to_save_keeps_large_gap():
    segs = [
        TimeSegment(state="active", start_time=datetime(2026, 7, 1, 9, 0, 0),
                    end_time=datetime(2026, 7, 1, 9, 30, 0)),
        TimeSegment(state="active", start_time=datetime(2026, 7, 1, 10, 30, 0),
                    end_time=datetime(2026, 7, 1, 11, 0, 0)),
    ]
    assert len(PersistenceManager.merge_segments_to_save(segs, 300)) == 2


def test_merge_segments_to_save_single_segment():
    segs = [TimeSegment(state="active", start_time=datetime(2026, 7, 1, 9, 0, 0),
                        end_time=datetime(2026, 7, 1, 9, 30, 0))]
    assert len(PersistenceManager.merge_segments_to_save(segs, 300)) == 1


def test_merge_segments_to_save_uses_idle_threshold_half():
    """Gap is compared against idle_threshold/2."""
    # Gap of 150s, threshold 300 -> 150 <= 150 -> merge
    segs = [
        TimeSegment(state="active", start_time=datetime(2026, 7, 1, 9, 0, 0),
                    end_time=datetime(2026, 7, 1, 9, 0, 0)),
        TimeSegment(state="active", start_time=datetime(2026, 7, 1, 9, 2, 30),
                    end_time=datetime(2026, 7, 1, 9, 5, 0)),
    ]
    assert len(PersistenceManager.merge_segments_to_save(segs, 300)) == 1

    # Gap of 151s, threshold 300 -> 151 > 150 -> keep separate
    segs2 = [
        TimeSegment(state="active", start_time=datetime(2026, 7, 1, 9, 0, 0),
                    end_time=datetime(2026, 7, 1, 9, 0, 0)),
        TimeSegment(state="active", start_time=datetime(2026, 7, 1, 9, 2, 31),
                    end_time=datetime(2026, 7, 1, 9, 5, 0)),
    ]
    assert len(PersistenceManager.merge_segments_to_save(segs2, 300)) == 2

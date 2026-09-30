import csv
import json
import logging
import math
import os
import threading
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from itertools import groupby
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union
from activitytracker.models import TimeSegment, Day

logger = logging.getLogger(__name__)

# Constants
ACTIVITIES_LOG_PREFIX = "activities"
MAX_CACHED_YEARS = 2
DEFAULT_IDLE_THRESHOLD_SECONDS = 300


class PersistenceWriteError(IOError):
    """Raised when segment data cannot be written to disk (see NFR-5.2)."""


def _hms_to_seconds(value: str) -> Optional[int]:
    """Parse an 'HH:MM:SS' (or 'HH:MM') time into seconds since midnight."""
    if not value:
        return None
    fmt = "%H:%M:%S" if value.count(':') == 2 else "%H:%M"
    try:
        dt = datetime.strptime(value, fmt)
    except (ValueError, TypeError, AttributeError):
        return None
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def _non_negative_int(value: Optional[str]) -> Optional[int]:
    """Parse a non-negative integer-like CSV value, or return None."""
    try:
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            return None
        parsed = int(numeric)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None
    return parsed


def _row_duration_seconds(row: dict) -> int:
    """Read precise duration, falling back to the legacy minute column."""
    seconds = _non_negative_int(row.get("duration_seconds"))
    if seconds is not None:
        return seconds
    minutes = _non_negative_int(row.get("duration_min"))
    return minutes * 60 if minutes is not None else 0


def _parse_activities_row(row: dict, target_date: Optional[date] = None) -> Optional[TimeSegment]:
    """Parse a single activities CSV row into a ``TimeSegment``.

    If *target_date* is provided, rows for other dates are ignored. Malformed
    or unsupported rows are skipped by returning ``None``.
    """
    date_str = row.get('date')
    state = row.get('state')
    if not date_str or state not in ('active', 'idle'):
        return None
    if target_date is not None and date_str != target_date.strftime("%Y-%m-%d"):
        return None
    try:
        day_date = date.fromisoformat(date_str)
        start_fmt = "%H:%M:%S" if row['start'].count(':') == 2 else "%H:%M"
        start_dt = datetime.combine(
            day_date,
            datetime.strptime(row['start'], start_fmt).time(),
        )
        end_dt = None
        if row.get('end'):
            end_fmt = "%H:%M:%S" if row['end'].count(':') == 2 else "%H:%M"
            end_dt = datetime.combine(
                day_date,
                datetime.strptime(row['end'], end_fmt).time(),
            )
            if end_dt < start_dt and end_dt.time() == datetime.min.time():
                end_dt += timedelta(days=1)
        return TimeSegment(state=state, start_time=start_dt, end_time=end_dt)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def _segment_to_row(seg: TimeSegment) -> Optional[dict]:
    """Convert a ``TimeSegment`` into a CSV row dict.

    Returns ``None`` for segments without a start time.
    """
    if not seg.start_time:
        return None
    return {
        "date": seg.start_time.strftime("%Y-%m-%d"),
        "state": seg.state,
        "start": seg.start_time.strftime("%H:%M:%S"),
        "end": seg.end_time.strftime("%H:%M:%S") if seg.end_time else "",
        "duration_min": seg.duration_minutes,
        "duration_seconds": int((seg.end_time - seg.start_time).total_seconds()) if seg.end_time else 0,
    }


def _first_active_starts(segments: List[TimeSegment]) -> Dict[date, datetime]:
    """Return the earliest active start time for each day present in *segments*.

    Segments without a start time are ignored. Days with no active segments are
    omitted from the result.
    """
    first_active: Dict[date, datetime] = {}
    for seg in segments:
        if seg.state == "active" and seg.start_time is not None:
            day = seg.start_time.date()
            first_active[day] = min(first_active.get(day, seg.start_time), seg.start_time)
    return first_active


def _read_existing_rows(path: str) -> Dict[str, dict]:
    """Read valid rows from an existing activities CSV into a lookup dict.

    The returned dict maps ``"<date> <start>"`` to the row dict. Invalid or
    truncated rows are skipped. The ``duration_seconds`` value is normalized
    using the same non-negative / legacy-minute logic used elsewhere.
    """
    existing: Dict[str, dict] = {}
    if not os.path.exists(path):
        return existing
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                date_str = row.get('date')
                start_str = row.get('start')
                if not date_str or not start_str or row.get('state') not in ('active', 'idle'):
                    # A truncated row or a file missing either identifying
                    # column/state cannot be merged safely. Skip it without
                    # discarding other valid rows.
                    continue
                key = f"{date_str} {start_str}"
                row["duration_seconds"] = str(_row_duration_seconds(row))
                existing[key] = row
    except (IOError, csv.Error, OSError) as exc:
        logger.warning("Could not read existing %s, starting fresh: %s", path, exc)
    return existing


def _drop_contained_rows(existing: Dict[str, dict], new_rows: List[dict]) -> None:
    """Remove existing rows that are fully contained within a new row.

    A merged/extended segment can fully contain an older row of the same day
    (e.g. after merge_segments_to_save merged a gap). Only finalized new rows
    (with an end) can contain others; an ongoing segment (end="") must not drop
    already-saved neighbors.
    """
    for seg in sorted(new_rows, key=lambda s: (s['date'], s['start'])):
        seg_date = seg['date']
        seg_start = _hms_to_seconds(seg['start'])
        seg_end = _hms_to_seconds(seg['end']) if seg['end'] else None
        if seg_end is None or seg_start is None:
            continue
        for key in list(existing.keys()):
            erow = existing[key]
            if erow['date'] != seg_date or key == f"{seg_date} {seg['start']}":
                continue
            e_start = _hms_to_seconds(erow['start'])
            e_end = _hms_to_seconds(erow['end']) if erow['end'] else None
            if e_start is None or e_end is None:
                continue
            if e_start >= seg_start and e_end <= seg_end:
                del existing[key]


class PersistenceManager:
    __slots__ = ('_get_data_dir', '_get_state_file_path', '_path_cache', '_totals_cache', '_file_lock')

    def __init__(
        self,
        data_dir_fn: Callable[[], Union[str, Path]],
        state_file_path_fn: Optional[Callable[[], Union[str, Path]]] = None,
    ) -> None:
        self._get_data_dir = data_dir_fn
        self._get_state_file_path = state_file_path_fn
        self._path_cache: Dict[str, str] = {}
        self._totals_cache: Dict[int, Dict[str, Tuple[int, int]]] = {}
        self._file_lock = threading.RLock()

    @contextmanager
    def csv_transaction(self):
        """Serialize CSV read/modify/write operations within this process."""
        with self._file_lock:
            yield

    def _state_file_path(self) -> str:
        if self._get_state_file_path is not None:
            return str(self._get_state_file_path())
        return os.path.join(str(self._get_data_dir()), "state.json")

    def invalidate_totals_cache(self, year: Optional[int] = None) -> None:
        """Invalidate the day-totals cache for *year*, or all years if omitted."""
        with self._file_lock:
            if year is None:
                self._totals_cache.clear()
            else:
                self._totals_cache.pop(year, None)

    def invalidate_path_cache(self) -> None:
        """Invalidate cached log file paths after a data-dir switch."""
        self._path_cache.clear()

    def invalidate_caches(self) -> None:
        """Invalidate all cached paths and totals."""
        self.invalidate_path_cache()
        self.invalidate_totals_cache()

    def _cache_year_totals(self, year: int, totals: Dict[str, Tuple[int, int]]) -> None:
        """Cache recent totals without retaining every queried year in memory."""
        self._totals_cache[year] = totals
        while len(self._totals_cache) > MAX_CACHED_YEARS:
            self._totals_cache.pop(next(iter(self._totals_cache)))

    def get_log_file_path(self, prefix: str, year: int) -> Path:
        key = f"{prefix}-{year}"
        if key not in self._path_cache:
            self._path_cache[key] = str(Path(self._get_data_dir()) / f"{prefix}-{year}.csv")
        return Path(self._path_cache[key])

    def get_weekly_minutes(self, week_start_date: date) -> Tuple[int, int]:
        end_of_week = week_start_date + timedelta(days=6)
        years = {week_start_date.year, end_of_week.year}
        totals_by_year = {year: self._day_totals_for_year(year) for year in years}
        active_total, idle_total = 0, 0
        current = week_start_date
        while current <= end_of_week:
            day_active, day_idle = totals_by_year[current.year].get(
                current.strftime("%Y-%m-%d"), (0, 0)
            )
            active_total += day_active
            idle_total += day_idle
            current += timedelta(days=1)
        return active_total, idle_total

    def get_minutes_for_date(self, target_date: date) -> Tuple[int, int]:
        return self._day_totals_for_year(target_date.year).get(
            target_date.strftime("%Y-%m-%d"), (0, 0)
        )

    def _day_totals_for_year(self, year: int) -> Dict[str, Tuple[int, int]]:
        with self._file_lock:
            return self._day_totals_for_year_locked(year)

    def _day_totals_for_year_locked(self, year: int) -> Dict[str, Tuple[int, int]]:
        """Read one year's activities log once and return {date: (active_min, idle_min)}.

        Results are cached per year; call ``invalidate_totals_cache(year)``
        after the file is re-written to force a fresh read.
        """
        if year in self._totals_cache:
            return self._totals_cache[year]

        path = str(self.get_log_file_path(ACTIVITIES_LOG_PREFIX, year))
        totals_seconds: Dict[str, Tuple[int, int]] = {}
        if not os.path.exists(path):
            self._cache_year_totals(year, {})
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    seg = _parse_activities_row(row)
                    if seg is None or seg.end_time is None:
                        # Ongoing segments have no known duration; ignore for
                        # totals until they are finalized.
                        continue
                    # Keep the non-negative / legacy-minute handling used by the
                    # old totals parser; timestamps alone are enough to identify
                    # the day and state.
                    duration_seconds = _row_duration_seconds(row)
                    date_str = seg.start_time.strftime("%Y-%m-%d")
                    active, idle = totals_seconds.get(date_str, (0, 0))
                    if seg.state == 'active':
                        active += duration_seconds
                    else:
                        idle += duration_seconds
                    totals_seconds[date_str] = (active, idle)
        except (IOError, csv.Error, OSError) as exc:
            logger.warning("Failed to read activities log for %s: %s", year, exc)
        totals = {
            date_str: ((active_seconds + 30) // 60, (idle_seconds + 30) // 60)
            for date_str, (active_seconds, idle_seconds) in totals_seconds.items()
        }
        self._cache_year_totals(year, totals)
        return totals

    def read_segments_for_day(self, target_date: date) -> List[TimeSegment]:
        with self._file_lock:
            return self._read_segments_for_day_locked(target_date)

    def _read_segments_for_day_locked(self, target_date: date) -> List[TimeSegment]:
        """Optimized: minimal parsing, direct list construction."""
        segments: List[TimeSegment] = []
        path = self.get_log_file_path(ACTIVITIES_LOG_PREFIX, target_date.year)
        if not os.path.exists(path):
            return segments
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    seg = _parse_activities_row(row, target_date)
                    if seg is not None:
                        segments.append(seg)
        except (IOError, csv.Error, OSError) as exc:
            logger.warning("Failed to read segments for %s: %s", target_date, exc)
        return segments

    def read_segments_for_year(self, year: int) -> List[TimeSegment]:
        """Read every valid segment from a year's activities log."""
        with self._file_lock:
            return self._read_segments_for_year_locked(year)

    def _read_segments_for_year_locked(self, year: int) -> List[TimeSegment]:
        """Read all valid segments from a year's log.

        Propagates read errors so callers (e.g. CSV optimization) can surface
        them to the user. Use ``read_segments_for_year`` for the public API.
        """
        segments: List[TimeSegment] = []
        path = self.get_log_file_path(ACTIVITIES_LOG_PREFIX, year)
        if not os.path.exists(path):
            return segments
        with open(path, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seg = _parse_activities_row(row)
                if seg is not None:
                    segments.append(seg)
        return segments

    def save_segments(self, segments_by_day: Dict[date, Day], idle_threshold: int = DEFAULT_IDLE_THRESHOLD_SECONDS) -> None:
        with self._file_lock:
            self._save_segments_locked(segments_by_day, idle_threshold)

    def _save_segments_locked(self, segments_by_day: Dict[date, Day], idle_threshold: int = DEFAULT_IDLE_THRESHOLD_SECONDS) -> None:
        """Save segment-level data to a CSV file, by year."""
        if not segments_by_day:
            return
        segments_by_year: Dict[int, List[TimeSegment]] = {}

        for day, day_data in segments_by_day.items():
            optimized_segments = self.optimize_segments(day_data.segments, idle_threshold)
            # Ensure the year is scheduled for rewrite even if every segment for
            # this day was filtered out, so legacy-row migration still runs.
            segments_by_year.setdefault(day.year, []).extend(optimized_segments)

        for year, segments in segments_by_year.items():
            self._write_segments_for_year(year, segments)

    def _write_segments_for_year(self, year: int, segments: List[TimeSegment]) -> None:
        """Convert segments to rows and rewrite the year's CSV, superseding rows
        that are fully contained within the new ones.
        """
        new_rows = [row for seg in segments if (row := _segment_to_row(seg)) is not None]

        path = str(self.get_log_file_path(ACTIVITIES_LOG_PREFIX, year))
        existing_segments = _read_existing_rows(path)
        _drop_contained_rows(existing_segments, new_rows)

        for seg in new_rows:
            key = f"{seg['date']} {seg['start']}"
            existing_segments[key] = seg

        sorted_keys = sorted(existing_segments.keys(), reverse=True)
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["date", "state", "start", "end", "duration_min", "duration_seconds"])
                writer.writeheader()
                for key in sorted_keys:
                    writer.writerow(existing_segments[key])
            # File was written successfully — invalidate the totals cache for
            # this year so the next read picks up fresh data.
            self._totals_cache.pop(year, None)
        except (IOError, OSError) as exc:
            logger.error("Failed to write %s: %s", path, exc)
            raise PersistenceWriteError(f"Could not write {path}: {exc}") from exc

    def optimize_year_file(self, year: int, idle_threshold: int = DEFAULT_IDLE_THRESHOLD_SECONDS) -> Tuple[int, int]:
        """Read, optimize per-day, and rewrite one year's activities log.

        Returns ``(original_row_count, optimized_row_count)``.
        """
        segments = self._read_segments_for_year_locked(year)
        if not segments:
            return 0, 0

        optimized: List[TimeSegment] = []
        for seg_day, day_segments in groupby(
            sorted(segments, key=lambda seg: seg.start_time),
            key=lambda seg: seg.start_time.date(),
        ):
            optimized.extend(self.optimize_segments(list(day_segments), idle_threshold))

        self._write_segments_for_year(year, optimized)
        return len(segments), len(optimized)

    def optimize_segments(
        self, segments: List[TimeSegment], idle_threshold: int = DEFAULT_IDLE_THRESHOLD_SECONDS
    ) -> List[TimeSegment]:
        """Normalize a day's segments into their final persisted form.

        Composes the full pre-save pipeline in order:

        1. Filter idle segments outside the active window (before the first
           active start / after the last active end).
        2. Fill any remaining internal gaps with idle segments.
        3. Compact: merge same-state neighbours and absorb short idle gaps into
           surrounding active time (FR-3.10).

        Returns a new list of ``TimeSegment`` objects; the input list is never
        mutated in place.
        """
        filtered = self._filter_idle_boundary_segments(segments)
        filled = self.fill_gaps_with_idle(filtered)
        return self.merge_segments_to_save(filled, idle_threshold)

    @staticmethod
    def _filter_idle_boundary_segments(segments: List[TimeSegment]) -> List[TimeSegment]:
        """Filter out idle segments before first active start and after last active end.

        Idle segments between active segments are preserved (e.g., lunch break).
        If there are no active segments, an empty list is returned.

        Returns a new list of TimeSegment objects; the input list is not mutated.
        """
        if not segments:
            return []

        first_active_per_day = _first_active_starts(segments)
        if not first_active_per_day:
            return []
        first_active = min(first_active_per_day.values())

        active_segments = [seg for seg in segments if seg.state == 'active' and seg.start_time is not None]

        # Check if an active segment is ongoing (end_time is None) or starts later
        has_ongoing_active = any(seg.end_time is None for seg in active_segments)
        latest_active_start = max(seg.start_time for seg in active_segments)

        last_active_end = None
        active_with_end = [seg.end_time for seg in active_segments if seg.end_time is not None]
        if active_with_end:
            last_active_end = max(active_with_end)

        # Filter out idle segments outside the active window
        filtered = []
        for seg in segments:
            if seg.state == 'idle':
                seg_start = seg.start_time
                seg_end = seg.end_time

                # Skip idle segments that begin before the first active segment.
                # This covers both idle that ends before activity begins
                # (seg_end <= first_active) and corrupt idle that overlaps the
                # first active start (seg_start < first_active), so no idle
                # segment ever starts before the first active time.
                if (seg_end and seg_end <= first_active) or (seg_start and seg_start < first_active):
                    continue

                # Skip idle segments that start after the last active segment ended.
                # If an active segment is ongoing or starts after this idle segment,
                # this idle segment is NOT after the last active period.
                if not has_ongoing_active or (seg_start and seg_start > latest_active_start):
                    if seg_start and last_active_end and seg_start >= last_active_end:
                        continue

            # Keep non-idle segments and relevant idle segments
            filtered.append(seg)

        return filtered

    @staticmethod
    def fill_gaps_with_idle(segments: List[TimeSegment]) -> List[TimeSegment]:
        """Fill internal, same-day gaps with idle segments.

        Invalid-start segments are ignored. Leading idle, cross-day gaps,
        overlaps, and gaps after an open segment are left unchanged.
        """
        ordered = sorted(
            (seg for seg in segments if seg.start_time is not None),
            key=lambda seg: seg.start_time,
        )
        if len(ordered) < 2:
            return ordered

        first_active = _first_active_starts(ordered)

        result: List[TimeSegment] = []
        day: Optional[date] = None
        covered_until: Optional[datetime] = None
        open_segment = False

        for seg in ordered:
            seg_day = seg.start_time.date()
            if seg_day != day:
                day, covered_until, open_segment = seg_day, None, False

            # Only fill gaps that fall at or after the first active segment of
            # the day. This prevents fabricating idle time from midnight up to
            # the first real activity.
            if (
                covered_until is not None
                and not open_segment
                and covered_until >= first_active.get(seg_day, datetime.max)
                and seg.start_time > covered_until
            ):
                result.append(TimeSegment("idle", covered_until, seg.start_time))

            result.append(seg)
            if seg.end_time is None:
                open_segment = True
            elif not open_segment:
                end = max(seg.start_time, seg.end_time)
                covered_until = max(covered_until, end) if covered_until else end

        return result

    @staticmethod
    def merge_segments_to_save(segments: List[TimeSegment], idle_threshold: int = DEFAULT_IDLE_THRESHOLD_SECONDS) -> List[TimeSegment]:
        """Merge consecutive same-state segments whose gap is within idle_threshold.

        Returns a new list of ``TimeSegment`` objects; the input list is never
        mutated in place.
        """
        if len(segments) <= 1:
            return segments[:]

        def _merge_same_state(input_segments: List[TimeSegment]) -> List[TimeSegment]:
            merged: List[TimeSegment] = [input_segments[0]]
            for seg in input_segments[1:]:
                prev = merged[-1]
                # Never merge across a calendar-day boundary: segments are stored
                # per-year sorted chronologically, so a same-state segment ending
                # 23:59 and one starting 00:00 would otherwise be merged into the
                # previous day and corrupt daily totals.
                same_day = (
                    prev.start_time is not None
                    and seg.start_time is not None
                    and prev.start_time.date() == seg.start_time.date()
                )
                if same_day and prev.end_time and seg.start_time and prev.state == seg.state:
                    # Guard against overlapping segments (shouldn't happen in normal
                    # operation, but corrupt/legacy/manually-edited CSV could contain
                    # them). Never create a segment with end_time < start_time.
                    if seg.start_time < prev.end_time:
                        if seg.end_time and seg.end_time > prev.end_time:
                            # Replace prev with a new copy so the original is not mutated
                            merged[-1] = TimeSegment(
                                state=prev.state,
                                start_time=prev.start_time,
                                end_time=seg.end_time,
                            )
                        continue
                    gap = (seg.start_time - prev.end_time).total_seconds()
                    if gap <= idle_threshold:
                        # Replace prev with a new copy so the original is not mutated
                        merged[-1] = TimeSegment(
                            state=prev.state,
                            start_time=prev.start_time,
                            end_time=seg.end_time or datetime.now().replace(microsecond=0),
                        )
                        continue
                merged.append(seg)
            return merged

        merged = _merge_same_state(segments)

        absorbed_idle: List[TimeSegment] = []
        for seg in merged:
            if (
                absorbed_idle
                and seg.state == "idle"
                and absorbed_idle[-1].state == "active"
                and absorbed_idle[-1].end_time is not None
                and seg.start_time is not None
                and seg.end_time is not None
                and absorbed_idle[-1].start_time.date() == seg.start_time.date() == seg.end_time.date()
            ):
                idle_duration = (seg.end_time - seg.start_time).total_seconds()
                if 0 <= idle_duration <= idle_threshold and seg.start_time >= absorbed_idle[-1].end_time:
                    absorbed_idle[-1] = TimeSegment(
                        state="active",
                        start_time=absorbed_idle[-1].start_time,
                        end_time=seg.end_time,
                    )
                    continue
            absorbed_idle.append(seg)

        return _merge_same_state(absorbed_idle)

    def get_data_dir(self) -> str:
        return self._get_data_dir()

    # ------------------------------------------------------------
    # Runtime state (cross-process, lives next to the data files)
    # ------------------------------------------------------------

    def save_last_segment_write(self, when: datetime) -> None:
        """Persist the timestamp of the last successful segment write (FR-2.6)."""
        path = self._state_file_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"last_segment_write": when.isoformat()}, f)
        except OSError as exc:
            logger.warning("Could not persist runtime state: %s", exc)

    def read_last_segment_write(self) -> Optional[datetime]:
        """Read the last successful segment-write timestamp, or None."""
        path = self._state_file_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return datetime.fromisoformat(data["last_segment_write"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def clear_last_segment_write(self) -> None:
        """Remove the last successful segment-write timestamp from runtime state."""
        path = self._state_file_path()
        try:
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "last_segment_write" in data:
                del data["last_segment_write"]
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not clear runtime state: %s", exc)

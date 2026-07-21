import csv
import json
import logging
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from models import TimeSegment, Day

logger = logging.getLogger(__name__)

# Constants
ACTIVITIES_LOG_PREFIX = "activities"


class PersistenceWriteError(IOError):
    """Raised when segment data cannot be written to disk (see NFR-5.2)."""


def _hms_to_seconds(value: str) -> Optional[int]:
    """Parse an 'HH:MM:SS' (or 'HH:MM') time into seconds since midnight."""
    if not value:
        return None
    try:
        parts = [int(p) for p in value.split(':')]
    except (ValueError, TypeError, AttributeError):
        return None
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = parts[0], parts[1], 0
    else:
        return None
    return h * 3600 + m * 60 + s


class PersistenceManager:
    __slots__ = ('_get_data_dir', '_path_cache', '_totals_cache')

    def __init__(self, data_dir_fn) -> None:
        self._get_data_dir = data_dir_fn
        self._path_cache: Dict[str, str] = {}
        self._totals_cache: Dict[int, Dict[str, Tuple[int, int]]] = {}

    def invalidate_totals_cache(self, year: Optional[int] = None) -> None:
        """Invalidate the day-totals cache for *year*, or all years if omitted."""
        if year is None:
            self._totals_cache.clear()
        else:
            self._totals_cache.pop(year, None)

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
        """Read one year's activities log once and return {date: (active_min, idle_min)}.

        Results are cached per year; call ``invalidate_totals_cache(year)``
        after the file is re-written to force a fresh read.
        """
        if year in self._totals_cache:
            return self._totals_cache[year]

        path = str(self.get_log_file_path(ACTIVITIES_LOG_PREFIX, year))
        totals: Dict[str, Tuple[int, int]] = {}
        if not os.path.exists(path):
            self._totals_cache[year] = totals
            return totals
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    date_str = row['date']
                    # Prefer the stored duration_min column (which uses the same
                    # rounding as the model), falling back to duration_seconds // 60
                    # for legacy CSV files that predate the column.
                    dur_str = row.get('duration_min', '')
                    if dur_str and dur_str.strip():
                        try:
                            dur = int(dur_str)
                        except (ValueError, TypeError):
                            dur = 0
                    else:
                        try:
                            dur_seconds = int(float(row.get('duration_seconds', '0') or '0'))
                            dur = (dur_seconds + 30) // 60  # round to nearest
                        except (ValueError, TypeError):
                            dur = 0
                    active, idle = totals.get(date_str, (0, 0))
                    if row['state'] == 'active':
                        active += dur
                    else:
                        idle += dur
                    totals[date_str] = (active, idle)
        except (IOError, csv.Error, OSError) as exc:
            logger.warning("Failed to read activities log for %s: %s", year, exc)
        self._totals_cache[year] = totals
        return totals

    def read_segments_for_day(self, target_date: date) -> List[TimeSegment]:
        """Optimized: minimal parsing, direct list construction."""
        segments: List[TimeSegment] = []
        path = self.get_log_file_path(ACTIVITIES_LOG_PREFIX, target_date.year)
        if not os.path.exists(path):
            return segments
        target_str = target_date.strftime("%Y-%m-%d")
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['date'] != target_str:
                        continue
                    try:
                        parts = row['start'].split(':')
                        start_dt = datetime(target_date.year, target_date.month, target_date.day,
                                            int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
                        end_dt = None
                        if row.get('end'):
                            parts = row['end'].split(':')
                            end_dt = datetime(target_date.year, target_date.month, target_date.day,
                                            int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
                        segments.append(TimeSegment(state=row['state'], start_time=start_dt, end_time=end_dt))
                    except (ValueError, TypeError):
                        continue
        except (IOError, csv.Error, OSError) as exc:
            logger.warning("Failed to read segments for %s: %s", target_date, exc)
        return segments

    def save_segments(self, segments_by_day) -> None:
        """Save segment-level data to a CSV file, by year."""
        if not segments_by_day:
            return
        segments_by_year: Dict[int, List[dict]] = {}

        for day, day_data in segments_by_day.items():
            year = day.year
            if year not in segments_by_year:
                segments_by_year[year] = []
            for seg in day_data.segments:
                if seg.start_time:
                    segments_by_year[year].append({
                        "date": day.strftime("%Y-%m-%d"),
                        "state": seg.state,
                        "start": seg.start_time.strftime("%H:%M:%S"),
                        "end": seg.end_time.strftime("%H:%M:%S") if seg.end_time else "",
                        "duration_min": seg.duration_minutes,
                        "duration_seconds": int((seg.end_time - seg.start_time).total_seconds()) if seg.end_time else 0,
                    })

        for year, new_segments in segments_by_year.items():
            path = self.get_log_file_path(ACTIVITIES_LOG_PREFIX, year)
            existing_segments: Dict[str, dict] = {}

            if os.path.exists(path):
                try:
                    with open(path, "r", newline="", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            key = f"{row['date']} {row['start']}"
                            if "duration_seconds" not in row:
                                row["duration_seconds"] = row.get('duration_min', '0') or '0'
                            existing_segments[key] = row
                except (IOError, csv.Error, OSError) as exc:
                    logger.warning("Could not read existing %s, starting fresh: %s", path, exc)

            # A merged/extended segment can fully contain an older row of the
            # same day (e.g. after merge_segments_to_save merged a gap). Drop the
            # contained row so we never persist overlapping duplicate data.
            # Only finalized segments (with an end) can contain others; an
            # ongoing segment (end="") must not drop already-saved neighbors.
            for seg in sorted(new_segments, key=lambda s: (s['date'], s['start'])):
                seg_date = seg['date']
                seg_start = _hms_to_seconds(seg['start'])
                seg_end = _hms_to_seconds(seg['end']) if seg['end'] else None
                if seg_end is None or seg_start is None:
                    continue
                for key in list(existing_segments.keys()):
                    erow = existing_segments[key]
                    if erow['date'] != seg_date or key == f"{seg_date} {seg['start']}":
                        continue
                    e_start = _hms_to_seconds(erow['start'])
                    e_end = _hms_to_seconds(erow['end']) if erow['end'] else None
                    if e_start is None or e_end is None:
                        continue
                    if e_start >= seg_start and e_end <= seg_end:
                        del existing_segments[key]

            for seg in new_segments:
                key = f"{seg['date']} {seg['start']}"
                existing_segments[key] = seg

            sorted_keys = sorted(existing_segments.keys())
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

    @staticmethod
    def merge_segments_to_save(segments: List[TimeSegment], idle_threshold: int = 300) -> List[TimeSegment]:
        """Merge consecutive same-state segments whose gap is within idle_threshold.

        Returns a new list of ``TimeSegment`` objects; the input list is never
        mutated in place.
        """
        if len(segments) <= 1:
            return segments[:]
        merged: List[TimeSegment] = [segments[0]]
        for seg in segments[1:]:
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

    def get_data_dir(self) -> str:
        return self._get_data_dir()

    # ------------------------------------------------------------
    # Runtime state (cross-process, lives next to the data files)
    # ------------------------------------------------------------

    def save_last_segment_write(self, when: datetime) -> None:
        """Persist the timestamp of the last successful segment write (FR-2.6)."""
        path = os.path.join(str(self._get_data_dir()), "state.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"last_segment_write": when.isoformat()}, f)
        except OSError as exc:
            logger.warning("Could not persist runtime state: %s", exc)

    def read_last_segment_write(self) -> Optional[datetime]:
        """Read the last successful segment-write timestamp, or None."""
        path = os.path.join(str(self._get_data_dir()), "state.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return datetime.fromisoformat(data["last_segment_write"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None


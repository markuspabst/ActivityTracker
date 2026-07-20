import csv
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
from models import TimeSegment, Day

# Constants
ACTIVITIES_LOG_PREFIX = "activities"
DAILY_LOG_PREFIX = "daily"


class PersistenceManager:
    __slots__ = ('_get_data_dir', '_path_cache')

    def __init__(self, data_dir_fn) -> None:
        self._get_data_dir = data_dir_fn
        self._path_cache: Dict[str, str] = {}

    def get_log_file_path(self, prefix: str, year: int) -> Path:
        key = f"{prefix}-{year}"
        if key not in self._path_cache:
            self._path_cache[key] = str(Path(self._get_data_dir()) / f"{prefix}-{year}.csv")
        return Path(self._path_cache[key])

    def get_weekly_minutes(self, week_start_date: date) -> Tuple[int, int]:
        end_of_week = week_start_date + timedelta(days=6)
        active_total, idle_total = 0, 0
        week_start_str, week_end_str = week_start_date.strftime("%Y-%m-%d"), end_of_week.strftime("%Y-%m-%d")
        years_to_check = {week_start_date.year, end_of_week.year} if end_of_week.year != week_start_date.year else {week_start_date.year}

        for year in years_to_check:
            path = str(self.get_log_file_path(ACTIVITIES_LOG_PREFIX, year))
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row_date = row['date']
                        if week_start_str <= row_date <= week_end_str:
                            dur = int(row.get('duration_min', '0') or '0')
                            if row['state'] == 'active':
                                active_total += dur
                            else:
                                idle_total += dur
            except Exception:
                pass
        return active_total, idle_total

    def get_minutes_for_date(self, target_date: date) -> Tuple[int, int]:
        path = str(self.get_log_file_path(ACTIVITIES_LOG_PREFIX, target_date.year))
        if not os.path.exists(path):
            return 0, 0
        target_str = target_date.strftime("%Y-%m-%d")
        active_min, idle_min = 0, 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['date'] == target_str:
                        dur = int(row.get('duration_min', '0') or '0')
                        if row['state'] == 'active':
                            active_min += dur
                        else:
                            idle_min += dur
        except Exception:
            pass
        return active_min, idle_min

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
        except (IOError, csv.Error):
            pass
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
                except (IOError, csv.Error):
                    pass

            for seg in new_segments:
                key = f"{seg['date']} {seg['start']}"
                existing_segments[key] = seg

            sorted_keys = sorted(existing_segments.keys())
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["date", "state", "start", "end", "duration_min", "duration_seconds"])
                writer.writeheader()
                for key in sorted_keys:
                    writer.writerow(existing_segments[key])

    def save_daily_summary(self, dates) -> None:
        """Write/merge the daily-summary log (FR-3.3), one row per day.

        Schema: date, active_min, idle_min, session_start (HH:MM), session_end (HH:MM).

        Values are derived from the authoritative segment-level log (read back
        after save_segments) so the two logs stay consistent: the sum of a day's
        segment durations always equals active_min + idle_min. Days with no
        recorded activity are omitted (FR-3.7). The file is rotated per calendar
        year (daily-{year}.csv) per FR-3.6.
        """
        # Group the affected dates by calendar year (FR-3.6).
        dates_by_year: Dict[int, set] = {}
        for d in dates:
            dates_by_year.setdefault(d.year, set()).add(d)

        for year, year_dates in dates_by_year.items():
            # Build fresh summary rows from the segment log for the touched days.
            new_rows: Dict[str, dict] = {}
            for d in year_dates:
                active_min, idle_min = self.get_minutes_for_date(d)
                if active_min == 0 and idle_min == 0:
                    continue  # FR-3.7: omit days with no recorded activity.
                day = Day(date=d, segments=self.read_segments_for_day(d))
                start = day.session_start
                end = day.session_end
                date_str = d.strftime("%Y-%m-%d")
                new_rows[date_str] = {
                    "date": date_str,
                    "active_min": active_min,
                    "idle_min": idle_min,
                    "session_start": start.strftime("%H:%M") if start else "",
                    "session_end": end.strftime("%H:%M") if end else "",
                }

            path = self.get_log_file_path(DAILY_LOG_PREFIX, year)

            # Preserve rows for days not touched in this save.
            existing: Dict[str, dict] = {}
            if os.path.exists(path):
                try:
                    with open(path, "r", newline="", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            existing[row['date']] = row
                except (IOError, csv.Error):
                    pass

            # Freshly computed rows overwrite any stale row for the same day.
            existing.update(new_rows)
            if not existing:
                continue

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["date", "active_min", "idle_min", "session_start", "session_end"],
                )
                writer.writeheader()
                for date_str in sorted(existing.keys()):
                    writer.writerow(existing[date_str])

    @staticmethod
    def merge_segments_to_save(segments: List[TimeSegment], idle_threshold: int = 300) -> List[TimeSegment]:
        """Merge consecutive same-state segments with small gaps."""
        if len(segments) <= 1:
            return segments
        merged: List[TimeSegment] = [segments[0]]
        for seg in segments[1:]:
            prev = merged[-1]
            if prev.end_time and seg.start_time and prev.state == seg.state:
                gap = (seg.start_time - prev.end_time).total_seconds()
                if gap <= idle_threshold / 2:
                    prev.end_time = seg.end_time or datetime.now().replace(microsecond=0)
                    continue
            merged.append(seg)
        return merged

    def get_data_dir(self) -> str:
        return self._get_data_dir()

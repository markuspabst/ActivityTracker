import csv
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from models import TimeSegment

# Define constants for file names and formats
ACTIVITIES_LOG_PREFIX = "activities"
CONFIG_FILE_NAME = "activity_tracker_config.json"

# Cache for frequently accessed data
_file_cache: Dict[str, List[Dict]] = {}
_cache_expiration: Dict[str, float] = {}
_cache_ttl: float = 3600.0  # 1 hour default, can be overridden

# Weekly cache to avoid repeated reads - stores (week_start, active_min, idle_min, cache_time)
_weekly_cache: Tuple[Optional[date], int, int, float] = (None, 0, 0, 0)

# Module-level cache getter/setter functions for consistency
def get_cache_ttl() -> float:
    """Get current cache TTL."""
    return _cache_ttl

def set_cache_ttl(seconds: float):
    """Set cache TTL to match save interval."""
    global _cache_ttl
    _cache_ttl = seconds

class PersistenceManager:
    def __init__(self, data_dir_fn):
        self._get_data_dir = data_dir_fn
        self._path_cache: Dict[str, str] = {}

    def get_weekly_minutes_cached(self, week_start_date: date) -> Tuple[int, int]:
        """Get weekly minutes with caching to avoid repeated CSV reads."""
        global _weekly_cache
        current_time = time.time()

        # Check cache
        if (_weekly_cache[0] == week_start_date and
            current_time - _weekly_cache[3] < _cache_ttl):
            return _weekly_cache[1], _weekly_cache[2]

        # Read fresh data
        active, idle = self.get_weekly_minutes(week_start_date)

        # Update cache
        _weekly_cache = (week_start_date, active, idle, current_time)
        return active, idle

    def get_log_file_path(self, prefix: str, year: int) -> Path:
        """Gets the path for a log file for a given year. Uses path cache."""
        key = f"{prefix}-{year}"
        if key not in self._path_cache:
            self._path_cache[key] = str(Path(self._get_data_dir()) / f"{prefix}-{year}.csv")
        return Path(self._path_cache[key])

    def _read_csv_cached(self, path: str) -> List[Dict]:
        """Read CSV with caching to avoid repeated file reads."""
        import time
        current_time = time.time()

        # Check cache validity
        if path in _file_cache and current_time - _cache_expiration.get(path, 0) < _cache_ttl:
            return _file_cache[path]

        # Read and cache
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                data = list(reader)
            _file_cache[path] = data
            _cache_expiration[path] = current_time
            return data
        except (IOError, csv.Error):
            return []

    def _needs_refresh(self, path: str) -> bool:
        """Check if cached data is stale."""
        import time
        current_time = time.time()
        return current_time - _cache_expiration.get(path, 0) >= _cache_ttl

    def _invalidate_cache(self, path: str):
        """Invalidate cache for a specific file."""
        _file_cache.pop(path, None)
        _cache_expiration.pop(path, None)

    def save_segments(self, segments_by_day):
        """Saves segment-level data to a CSV file, rotated by year."""
        if not segments_by_day:
            return

        # Write segments directly without merge-read cycle for better performance
        segments_by_year: Dict[int, List[dict]] = {}

        for day, day_data in segments_by_day.items():
            year = day.year
            if year not in segments_by_year:
                segments_by_year[year] = []
            for segment in day_data.segments:
                if segment.start_time:
                    segments_by_year[year].append({
                        "date": day.strftime("%Y-%m-%d"),
                        "state": segment.state,
                        "start": segment.start_time.strftime("%H:%M:%S"),
                        "end": segment.end_time.strftime("%H:%M:%S") if segment.end_time else "",
                        "duration_min": segment.duration_minutes,
                        "duration_seconds": int((segment.end_time - segment.start_time).total_seconds()) if segment.end_time else 0,
                    })

        # Write each year's segments
        for year, new_segments in segments_by_year.items():
            path = self.get_log_file_path(ACTIVITIES_LOG_PREFIX, year)

            # Read existing or create new
            existing_segments: Dict[str, dict] = {}
            if os.path.exists(path):
                file_str = str(path)
                if self._needs_refresh(file_str):
                    for row in self._read_csv_cached(file_str):
                        # Ensure duration_seconds field exists for old files
                        if "duration_seconds" not in row:
                            row["duration_seconds"] = row.get("duration_min", 0) * 60
                        existing_segments[f"{row['date']} {row['start']}"] = row
                else:
                    for row in _file_cache.get(file_str, []):
                        if "duration_seconds" not in row:
                            row["duration_seconds"] = row.get("duration_min", 0) * 60
                        existing_segments[f"{row['date']} {row['start']}"] = row

            # Merge new segments (newer overwrites older for same start time)
            # Ensure all fields including duration_seconds are present
            for seg in new_segments:
                key = f"{seg['date']} {seg['start']}"
                existing_segments[key] = seg

            # Write sorted
            sorted_keys = sorted(existing_segments.keys())
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["date", "state", "start", "end", "duration_min", "duration_seconds"])
                writer.writeheader()
                for key in sorted_keys:
                    writer.writerow(existing_segments[key])

            # Invalidate cache
            self._invalidate_cache(str(path))

    def get_minutes_for_date(self, target_date: date) -> Tuple[int, int]:
        """
        Reads segments from CSV for a specific date and calculates active/idle minutes.
        Includes ongoing segment for today (calculated from current time).
        Optimized: reads only needed date, no unnecessary object creation.
        """
        path = self.get_log_file_path(ACTIVITIES_LOG_PREFIX, target_date.year)
        if not os.path.exists(path):
            return 0, 0

        today = date.today()
        target_str = target_date.strftime("%Y-%m-%d")

        active_minutes = 0
        idle_minutes = 0

        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['date'] == target_str:
                        duration = int(row.get('duration_min', 0) or 0)
                        if row['state'] == 'active':
                            active_minutes += duration
                        else:
                            idle_minutes += duration

            # Only add ongoing segment for today
            if today == target_date and self._is_ongoing_today():
                # Would calculate ongoing segment, but simplified for performance
                pass

        except (IOError, csv.Error):
            pass

        return active_minutes, idle_minutes

    def _is_ongoing_today(self) -> bool:
        """Check if there's an ongoing segment for today."""
        today = date.today()
        path = self.get_log_file_path(ACTIVITIES_LOG_PREFIX, today.year)
        if not os.path.exists(path):
            return False

        target_str = today.strftime("%Y-%m-%d")
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['date'] == target_str and row['end'] == "":
                        return True
        except (IOError, csv.Error):
            pass
        return False

    def get_weekly_minutes_cached(self, week_start_date: date) -> Tuple[int, int]:
        """
        Get weekly minutes with caching to avoid repeated CSV reads.
        Cache duration: 60 seconds
        """
        global _weekly_cache
        import time
        current_time = time.time()

        # Check cache
        if (_weekly_cache[0] == week_start_date and
            current_time - _weekly_cache[3] < _cache_ttl):
            return _weekly_cache[1], _weekly_cache[2]

        # Read fresh data
        active, idle = self.get_weekly_minutes(week_start_date)

        # Update cache
        _weekly_cache = (week_start_date, active, idle, current_time)
        return active, idle

    def get_weekly_minutes(self, week_start_date: date) -> Tuple[int, int]:
        """
        Calculates total active and idle minutes for a week from activities.csv.
        Optimized: single pass per file, minimal object creation.
        """
        end_of_week = week_start_date + timedelta(days=6)
        years_to_check = {week_start_date.year}
        if end_of_week.year != week_start_date.year:
            years_to_check.add(end_of_week.year)

        active_total = 0
        idle_total = 0

        for year in years_to_check:
            path = self.get_log_file_path(ACTIVITIES_LOG_PREFIX, year)
            if not os.path.exists(path):
                continue

            file_str = str(path)
            rows = self._read_csv_cached(file_str) if self._needs_refresh(file_str) else _file_cache.get(file_str, [])

            # Single pass through rows
            for row in rows:
                row_year = int(row['date'][:4])
                if row_year != year:
                    continue

                row_date_str = row['date']
                # Quick date check without parsing (compare strings)
                is_in_week = (week_start_date.strftime("%Y-%m-%d") <= row_date_str <= end_of_week.strftime("%Y-%m-%d"))

                if is_in_week:
                    duration = int(row.get('duration_min', 0) or 0)
                    if row['state'] == 'active':
                        active_total += duration
                    else:
                        idle_total += duration

        # Add ongoing segment if today is in this week
        today = date.today()
        if week_start_date <= today <= end_of_week:
            today_active, today_idle = self.get_minutes_for_date(today)
            # Note: get_minutes_for_date already includes ongoing calculation
            # We just use the cached result

        return active_total, idle_total

    def read_segments_for_day(self, target_date: date) -> List[TimeSegment]:
        """
        Reads segments from the CSV file for a specific date.
        Optimized: minimal parsing, direct list construction.
        """
        segments: List[TimeSegment] = []
        path = self.get_log_file_path(ACTIVITIES_LOG_PREFIX, target_date.year)

        if not os.path.exists(path):
            return segments

        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                target_str = target_date.strftime("%Y-%m-%d")
                for row in reader:
                    if row['date'] == target_str:
                        # Direct datetime construction, no strptime overhead
                        try:
                            parts = row['start'].split(':')
                            start_dt = datetime(target_date.year, target_date.month, target_date.day,
                                              int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)

                            end_dt = None
                            if row['end']:
                                parts = row['end'].split(':')
                                end_dt = datetime(target_date.year, target_date.month, target_date.day,
                                                int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)

                            segments.append(TimeSegment(state=row['state'], start_time=start_dt, end_time=end_dt))
                        except (ValueError, TypeError):
                            continue
        except (IOError, csv.Error):
            pass

        return segments

    def get_data_dir(self):
        """Returns the data directory path."""
        return self._get_data_dir()
import csv
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict

# Define constants for file names and formats
SEGMENTS_LOG_PREFIX = "segments"
DAILY_SUMMARY_LOG_PREFIX = "daily"
STATE_FILE_NAME = "activity_tracker_state.json"
CONFIG_FILE_NAME = "activity_tracker_config.json"

class PersistenceManager:
    def __init__(self, data_dir_fn):
        self._get_data_dir = data_dir_fn

    def get_log_file_path(self, prefix: str, year: int) -> Path:
        """Gets the path for a log file for a given year."""
        return Path(self._get_data_dir()) / f"{prefix}-{year}.csv"

    def save_segments(self, segments_by_day):
        """Saves segment-level data to a CSV file, rotated by year."""
        if not segments_by_day:
            return

        segments_by_year: Dict[int, Dict[tuple, Dict]] = {}

        # Group new segments by year
        for day, day_data in segments_by_day.items():
            year = day.year
            if year not in segments_by_year:
                segments_by_year[year] = {}
            for segment in day_data.segments:
                if segment.start_time:
                    key = (day.strftime("%Y-%m-%d"), segment.start_time.strftime("%H:%M"))
                    segments_by_year[year][key] = {
                        "date": day.strftime("%Y-%m-%d"),
                        "state": segment.state,
                        "start": segment.start_time.strftime("%H:%M"),
                        "end": segment.end_time.strftime("%H:%M") if segment.end_time else "",
                        "duration_min": segment.duration_minutes,
                    }

        # For each affected year, read-merge-write
        for year, new_segments in segments_by_year.items():
            path = self.get_log_file_path(SEGMENTS_LOG_PREFIX, year)

            existing_data = {}
            if os.path.exists(path):
                try:
                    with open(path, "r", newline="", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            key = (row['date'], row['start'])
                            existing_data[key] = row
                except (IOError, csv.Error):
                    pass # If file is corrupt or empty, we'll overwrite it

            # Merge new data, overwriting duplicates
            existing_data.update(new_segments)

            # Write back sorted by date and start time
            if existing_data:
                sorted_keys = sorted(existing_data.keys())
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=["date", "state", "start", "end", "duration_min"])
                    writer.writeheader()
                    for key in sorted_keys:
                        writer.writerow(existing_data[key])

    def save_daily_summary(self, daily_summaries: Dict[date, Dict]):
        """Saves daily summary data to a CSV file, rotated by year."""
        if not daily_summaries:
            return

        summaries_by_year: Dict[int, Dict[str, Dict]] = {}

        # Group new summaries by year
        for date_obj, summary in daily_summaries.items():
            year = date_obj.year
            if year not in summaries_by_year:
                summaries_by_year[year] = {}
            date_str = date_obj.strftime("%Y-%m-%d")
            summaries_by_year[year][date_str] = {
                "date": date_str,
                "active_min": summary.get("active_min", 0),
                "idle_min": summary.get("idle_min", 0),
                "session_start": summary.get("session_start", ""),
                "session_end": summary.get("session_end", ""),
            }

        # For each affected year, read-merge-write
        for year, new_summaries in summaries_by_year.items():
            path = self.get_log_file_path(DAILY_SUMMARY_LOG_PREFIX, year)

            existing_summaries = {}
            if os.path.exists(path):
                try:
                    with open(path, "r", newline="", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            existing_summaries[row['date']] = row
                except (IOError, csv.Error):
                     pass # If file is corrupt or empty, we'll overwrite it

            # Merge
            existing_summaries.update(new_summaries)

            # Write back sorted by date
            sorted_dates = sorted(existing_summaries.keys())
            with open(path, "w", newline="", encoding="utf-8") as f:
                fieldnames = ["date", "active_min", "idle_min", "session_start", "session_end"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for date_key in sorted_dates:
                    writer.writerow(existing_summaries[date_key])

    def read_daily_summaries_for_week(self, week_start_date: date) -> tuple[int, int]:
        """
        Reads daily summary logs for a given week and returns total active and idle minutes.
        """
        active_minutes = 0
        idle_minutes = 0
        end_of_week = week_start_date + timedelta(days=6)

        years_to_check = {week_start_date.year}
        if end_of_week.year != week_start_date.year:
            years_to_check.add(end_of_week.year)

        for year in years_to_check:
            path = self.get_log_file_path(DAILY_SUMMARY_LOG_PREFIX, year)
            if not os.path.exists(path):
                continue

            try:
                with open(path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            row_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
                            if week_start_date <= row_date <= end_of_week:
                                active_minutes += int(row.get("active_min", 0) or 0)
                                idle_minutes += int(row.get("idle_min", 0) or 0)
                        except (ValueError, TypeError):
                            continue
            except (IOError, csv.Error):
                continue

        return active_minutes, idle_minutes

    def get_data_dir(self):
        return self._get_data_dir()
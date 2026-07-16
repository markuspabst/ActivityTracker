"""
Pure data / persistence / calculation layer for ActivityTracker.

This module contains *no* UI code and *no* platform-specific code.
It can be imported by the menu app, the dashboard generator, tests, etc.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, date, timedelta
from typing import Any, Optional, List, Dict, Tuple
from persistence import PersistenceManager
from models import TimeSegment, Day

import platformdirs

# ------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------

APP_NAME = "ActivityTracker"

DEFAULT_TARGET_SECONDS = 8 * 3600
DEFAULT_WEEKLY_TARGET_SECONDS = 40 * 3600
DEFAULT_IDLE_THRESHOLD = 300
DEFAULT_SAVE_INTERVAL_SECONDS = 3600

# ------------------------------------------------------------
# PATHS
# ------------------------------------------------------------

DEFAULT_BASE_DIR = platformdirs.user_data_dir(APP_NAME)
CONFIG_DIR = platformdirs.user_config_dir(APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "activity_tracker_config.json")
DATA_DIR: Optional[str] = None

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}

def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def get_config_value(key, default=None):
    return load_config().get(key, default)

def set_config_value(key, value):
    config = load_config()
    config[key] = value
    save_config(config)

def get_configured_data_dir():
    return get_config_value('data_dir', DEFAULT_BASE_DIR)

def set_data_dir(path):
    global DATA_DIR
    DATA_DIR = path
    os.makedirs(DATA_DIR, exist_ok=True)


def persist_data_dir(path: str) -> None:
    set_config_value("data_dir", os.path.expanduser(path))


def reset_data_dir_to_default() -> None:
    config = load_config()
    if "data_dir" in config:
        del config["data_dir"]
    save_config(config)
    set_data_dir(DEFAULT_BASE_DIR)


# ------------------------------------------------------------
# SESSION TRACKER
# ------------------------------------------------------------

class SessionTracker:
    def __init__(self, persistence_manager: PersistenceManager) -> None:
        self.pm = persistence_manager
        self.days: Dict[date, Day] = {}
        self.current_segment: Optional[TimeSegment] = None
        self.is_locked = False

    def on_tick(self, idle_time: float, idle_threshold: int):
        """Process a tick with consistent timestamp handling."""
        now = datetime.now().replace(microsecond=0)
        current_date = now.date()

        if current_date not in self.days:
            self.days[current_date] = Day(date=current_date)

        is_idle_by_time = idle_time > idle_threshold
        current_state = 'idle' if is_idle_by_time or self.is_locked else 'active'

        if self.current_segment is None:
            self.current_segment = TimeSegment(state=current_state, start_time=now)
            self.days[current_date].segments.append(self.current_segment)
        elif self.current_segment.state != current_state:
            # Ensure end_time is always >= start_time
            end_time = self.current_segment.start_time if now < self.current_segment.start_time else now
            self.current_segment.end_time = end_time
            self.current_segment = TimeSegment(state=current_state, start_time=now)
            self.days[current_date].segments.append(self.current_segment)
        # else: state hasn't changed, continue with existing segment (end_time will be set on save)

        if self.current_segment.start_time.date() != current_date:
            # Round midnight to the exact start of the day
            midnight = datetime.combine(self.current_segment.start_time.date(), datetime.max.time())
            midnight = midnight.replace(microsecond=0)
            self.current_segment.end_time = midnight

            new_day_start = datetime.combine(current_date, datetime.min.time())
            new_day_start = new_day_start.replace(microsecond=0)
            self.current_segment = TimeSegment(state=self.current_segment.state, start_time=new_day_start)
            self.days[current_date].segments.append(self.current_segment)

            # Save data for the previous day when midnight crosses
            self.save_all_days()

    def finalize_session(self):
        if self.current_segment and self.current_segment.end_time is None:
            now = datetime.now().replace(microsecond=0)
            self.current_segment.end_time = self.current_segment.start_time if now < self.current_segment.start_time else now
        self.save_all_days()

    def save_all_days(self):
        # Set end_time for all ongoing segments using current time
        # This ensures we save accurate duration data
        now = datetime.now().replace(microsecond=0)
        for day_obj in self.days.values():
            for seg in day_obj.segments:
                if seg.end_time is None:
                    seg.end_time = now

        self.pm.save_segments(self.days)

        # Reset end_time for the current segment so it remains ongoing
        if self.current_segment:
            self.current_segment.end_time = None

        # Clear completed segments but keep the current ongoing segment in memory
        current_date = datetime.now().date()

        if current_date in self.days and self.current_segment:
            # Keep ALL segments but reset end_time for the current ongoing segment
            # This preserves historical data for today while allowing the current segment to continue
            updated_segments = []
            for seg in self.days[current_date].segments:
                if seg.start_time == self.current_segment.start_time:
                    # This is the current segment - reset end_time for continued tracking
                    updated_segments.append(TimeSegment(
                        state=seg.state,
                        start_time=seg.start_time,
                        end_time=None
                    ))
                else:
                    # Keep historical segments as-is
                    updated_segments.append(seg)
            self.days = {current_date: Day(date=current_date, segments=updated_segments)}
        else:
            self.days = {}

    def recover_from_crash(self):
        """
        Load previously saved segments from CSV for the current day.
        The JSON state file is no longer used - all data is in CSV.
        """
        pass  # No longer needed - data is loaded from CSV during initialization

    def load_current_day_segments(self):
        """
        Loads all segments for the current day from CSV into memory (self.days).
        This is called on startup to ensure historical data for today is present.
        Also sets current_segment to the last ongoing segment if any.
        """
        today = datetime.now().date()
        segments_for_today = self.pm.read_segments_for_day(today)

        if segments_for_today:
            if today not in self.days:
                self.days[today] = Day(date=today)
            # Append only new segments to avoid duplicates if recover_from_crash already added some
            existing_segment_start_times = {seg.start_time for seg in self.days[today].segments}
            for segment in segments_for_today:
                if segment.start_time not in existing_segment_start_times:
                    self.days[today].segments.append(segment)

            # Re-sort segments by start_time to maintain order
            self.days[today].segments.sort(key=lambda seg: seg.start_time)

            # Set current_segment to the last segment if it's still ongoing (end_time is None)
            if self.days[today].segments:
                last_segment = self.days[today].segments[-1]
                if last_segment.end_time is None:
                    self.current_segment = last_segment

    def set_locked(self, is_locked: bool):
        self.is_locked = is_locked
        self.on_tick(0, 0)

# ------------------------------------------------------------
# FORMATTING HELPERS
# ------------------------------------------------------------
def format_hours(seconds: float) -> str:
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h:02d}:{m:02d}"


"""
Pure data / persistence / calculation layer for ActivityTracker.

This module contains *no* UI code and *no* platform-specific code.
It can be imported by the menu app, the dashboard generator, tests, etc.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, date, timedelta
from typing import Any, Optional, List, Dict
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
        now = datetime.now()
        current_date = now.date()

        if current_date not in self.days:
            self.days[current_date] = Day(date=current_date)

        is_idle_by_time = idle_time > idle_threshold
        current_state = 'idle' if is_idle_by_time or self.is_locked else 'active'

        if self.current_segment is None:
            self.current_segment = TimeSegment(state=current_state, start_time=now)
            self.days[current_date].segments.append(self.current_segment)
        elif self.current_segment.state != current_state:
            self.current_segment.end_time = max(self.current_segment.start_time, now)
            self.current_segment = TimeSegment(state=current_state, start_time=now)
            self.days[current_date].segments.append(self.current_segment)

        if self.current_segment.start_time.date() != current_date:
            midnight = datetime.combine(self.current_segment.start_time.date(), datetime.max.time())
            self.current_segment.end_time = midnight

            new_day_start = datetime.combine(current_date, datetime.min.time())
            self.current_segment = TimeSegment(state=self.current_segment.state, start_time=new_day_start)
            self.days[current_date].segments.append(self.current_segment)

    def finalize_session(self):
        if self.current_segment and self.current_segment.end_time is None:
            self.current_segment.end_time = max(self.current_segment.start_time, datetime.now())
        self.save_all_days()

    def save_all_days(self):
        if self.current_segment and self.current_segment.end_time is None:
            self.current_segment.end_time = max(self.current_segment.start_time, datetime.now())
        daily_summaries = {}
        for day_date, day_obj in self.days.items():
            if not day_obj.segments:
                continue
            sess_start = day_obj.session_start
            sess_end = day_obj.session_end
            daily_summaries[day_date] = {
                "active_min": day_obj.active_minutes,
                "idle_min": day_obj.idle_minutes,
                "session_start": sess_start.strftime("%H:%M") if sess_start else "",
                "session_end": sess_end.strftime("%H:%M") if sess_end else "",
            }

        self.pm.save_segments(self.days)
        self.pm.save_daily_summary(daily_summaries)
        current_date = datetime.now().date()
        if current_date in self.days:
            self.days = {current_date: self.days[current_date]}
        else:
            self.days = {}

    def recover_from_crash(self):
        state_file = os.path.join(self.pm.get_data_dir(), "activity_tracker_state.json")
        if not os.path.exists(state_file):
            return

        with open(state_file, 'r') as f:
            try:
                state = json.load(f)
            except json.JSONDecodeError:
                return # Ignore corrupt state file

        if state.get("dirty"):
            last_segment_info = state.get("current_segment")
            if last_segment_info:
                # Always recover the current segment, regardless of last_active_time
                segment_start_time = datetime.fromisoformat(last_segment_info["start_time"])
                segment_date = segment_start_time.date()

                if segment_date not in self.days:
                    self.days[segment_date] = Day(date=segment_date)

                # Handle both cases: with and without last_active_time
                last_active_time_str = state.get("last_active_time")
                if last_active_time_str:
                    last_active_time = datetime.fromisoformat(last_active_time_str)

                    if last_active_time.date() != segment_date:
                        end_of_day = datetime.combine(segment_date, datetime.max.time())
                        recovered_segment = TimeSegment(
                            state=last_segment_info["state"],
                            start_time=segment_start_time,
                            end_time=end_of_day
                        )
                    else:
                        recovered_segment = TimeSegment(
                            state=last_segment_info["state"],
                            start_time=segment_start_time,
                            end_time=last_active_time
                        )

                    # Add the recovered segment and save historical data
                    self.days[segment_date].segments.append(recovered_segment)

                    # Save the recovered data without clearing memory (don't use save_all_days)
                    daily_summaries = {}
                    day_obj = self.days[segment_date]
                    if day_obj.segments:
                        sess_start = day_obj.session_start
                        sess_end = day_obj.session_end
                        daily_summaries[segment_date] = {
                            "active_min": day_obj.active_minutes,
                            "idle_min": day_obj.idle_minutes,
                            "session_start": sess_start.strftime("%H:%M") if sess_start else "",
                            "session_end": sess_end.strftime("%H:%M") if sess_end else "",
                        }

                    self.pm.save_segments({segment_date: day_obj})
                    self.pm.save_daily_summary(daily_summaries)
                else:
                    # No last_active_time means the segment is still ongoing
                    # Just restore it to memory without saving
                    recovered_segment = TimeSegment(
                        state=last_segment_info["state"],
                        start_time=segment_start_time,
                        end_time=None
                    )
                    self.days[segment_date].segments.append(recovered_segment)
                    # Don't save ongoing segments - they're still in progress

        self.mark_state_clean()

    def load_current_day_segments(self):
        """
        Loads all segments for the current day from CSV into memory (self.days).
        This is called on startup to ensure historical data for today is present.
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

    def write_state(self, dirty: bool = True):
        state_file = os.path.join(self.pm.get_data_dir(), "activity_tracker_state.json")
        last_active_times = [
            seg.end_time
            for day in self.days.values()
            for seg in day.segments
            if seg.state == 'active' and seg.end_time
        ]
        last_active = max(last_active_times) if last_active_times else None

        current_segment_info = None
        if self.current_segment:
            current_segment_info = {
                "state": self.current_segment.state,
                "start_time": self.current_segment.start_time.isoformat()
            }

        state = {
            "dirty": dirty,
            "timestamp": datetime.now().isoformat(),
            "current_segment": current_segment_info,
            "last_active_time": last_active.isoformat() if last_active else None
        }
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def mark_state_clean(self):
        self.write_state(dirty=False)

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


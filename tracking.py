"""
Pure data / persistence / calculation layer for ActivityTracker.

This module contains *no* UI code and *no* platform-specific code.
It can be imported by the menu app, the dashboard generator, tests, etc.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, date, timedelta
import datetime as _dt_module
from typing import Optional, Dict
from persistence import PersistenceManager
from models import TimeSegment, Day

import platformdirs

# ------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------

APP_NAME = "ActivityTracker"

# If the gap between two consecutive ticks exceeds this, the machine is assumed
# to have slept/suspended; the gap is recorded as Idle (FR-1.5). Normal ticks
# are ~5s apart, so 60s is a safe threshold for "the system was away".
SLEEP_GAP_THRESHOLD_SECONDS = 60

# ------------------------------------------------------------
# PATHS
# ------------------------------------------------------------

DEFAULT_BASE_DIR = platformdirs.user_data_dir(APP_NAME)
# Keep config/state files in the app's default base folder regardless of
# custom data directory selection.
CONFIG_DIR = DEFAULT_BASE_DIR
CONFIG_FILE = os.path.join(CONFIG_DIR, "activity_tracker_config.json")
LEGACY_CONFIG_FILE = os.path.join(platformdirs.user_config_dir(APP_NAME), "activity_tracker_config.json")
STATE_FILE = os.path.join(DEFAULT_BASE_DIR, "state.json")
DATA_DIR: Optional[str] = None

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

def load_config():
    if not os.path.exists(CONFIG_FILE):
        # One-time compatibility fallback: load from legacy config location
        # if present, then persist it in the new default-base location.
        if os.path.exists(LEGACY_CONFIG_FILE):
            try:
                with open(LEGACY_CONFIG_FILE, 'r') as f:
                    cfg = json.load(f)
                save_config(cfg)
                return cfg
            except (IOError, json.JSONDecodeError):
                return {}
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


def get_state_file_path() -> str:
    os.makedirs(DEFAULT_BASE_DIR, exist_ok=True)
    return STATE_FILE

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
        # Guards concurrent access to self.days / self.current_segment between
        # the background update thread (writes) and the menu thread (reads).
        self._lock = threading.Lock()
        # Timestamp of the previous tick; used to detect sleep/suspend gaps.
        self._last_tick_time: Optional[datetime] = None

    def on_tick(self, idle_time: float, idle_threshold: int):
        """Process a tick with consistent timestamp handling."""
        with self._lock:
            now = datetime.now().replace(microsecond=0)
            current_date = now.date()

            # FR-1.5: if the gap since the last tick is far larger than the poll
            # interval, the machine likely slept/suspended. Record that interval
            # as Idle and resume normal tracking from `now`. We only do this when
            # the system appears active afterward (idle_time <= threshold): a
            # genuine idle stretch already yields Idle segments through the normal
            # path, so we must not overwrite it. After a real sleep the idle timer
            # resets to ~0, so this condition detects exactly the false-active case.
            if self._last_tick_time is not None:
                gap_seconds = (now - self._last_tick_time).total_seconds()
                if gap_seconds > SLEEP_GAP_THRESHOLD_SECONDS and idle_time <= idle_threshold:
                    self._insert_sleep_gap(self._last_tick_time, now)
            self._last_tick_time = now

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

    def _insert_sleep_gap(self, gap_start: datetime, gap_end: datetime) -> None:
        """Record a sleep/suspend interval [gap_start, gap_end) as Idle segments.

        The interval is split at day boundaries so no segment spans a date
        (FR-2.4). The previously-open segment is closed at the moment sleep
        began so its tail is not double-counted.
        """
        if self.current_segment is not None and self.current_segment.end_time is None:
            self.current_segment.end_time = gap_start

        cur = gap_start
        while cur < gap_end:
            day = cur.date()
            day_end = datetime.combine(day, datetime.max.time()).replace(microsecond=0)
            seg_end = gap_end if gap_end <= day_end else day_end
            segment = TimeSegment(state="idle", start_time=cur, end_time=seg_end)
            self.days.setdefault(day, Day(date=day)).segments.append(segment)
            if gap_end <= day_end:
                break
            cur = datetime.combine(day, datetime.min.time()).replace(microsecond=0) + timedelta(days=1)
        self.current_segment = self.days[cur.date()].segments[-1]

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
        # Persist the last successful write time so an orphaned open segment
        # from an abnormal shutdown can be finalized to a known timestamp (FR-2.6).
        self.pm.save_last_segment_write(now)

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

            # Filter idle segments that are before first active or after last active
            updated_segments = self.pm._filter_idle_boundary_segments(updated_segments)

            self.days = {current_date: Day(date=current_date, segments=updated_segments)}
        else:
            self.days = {}

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

            # FR-2.6: finalize any orphaned open segment from a previous
            # (abnormal) shutdown so the untracked gap is not counted as active
            # time. Close it at the last known write time (persisted on each
            # save) — the most recent moment we are confident data was recorded.
            # If no write time is known, conservatively close it at its own start
            # (no unknown time is credited). The segment is finalized and not
            # resumed as the current (ongoing) segment.
            open_segments = [s for s in self.days[today].segments if s.end_time is None]
            if open_segments:
                last_write = self.pm.read_last_segment_write()
                if not isinstance(last_write, _dt_module.datetime):
                    last_write = None
                now = datetime.now().replace(microsecond=0)
                for seg in open_segments:
                    seg.end_time = max(seg.start_time, min(last_write, now)) if last_write else seg.start_time
                # Orphan finalized; do not resume it as the current segment.
                self.current_segment = None

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


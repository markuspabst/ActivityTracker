"""
Pure data / persistence / calculation layer for ActivityTracker.

This module contains *no* UI code and *no* platform-specific code.
It can be imported by the menu app, the dashboard generator, tests, etc.
"""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import platformdirs


# ------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------

APP_NAME = "ActivityTracker"

DEFAULT_TARGET_SECONDS = 8 * 3600        # 8 h
DEFAULT_WEEKLY_TARGET_SECONDS = 40 * 3600  # 40 h
DEFAULT_IDLE_THRESHOLD = 300              # 5 min
DEFAULT_SAVE_INTERVAL_SECONDS = 3600    # 1 h

TARGET_WORK_SECONDS = DEFAULT_TARGET_SECONDS
WEEKLY_TARGET_SECONDS = DEFAULT_WEEKLY_TARGET_SECONDS
IDLE_THRESHOLD = DEFAULT_IDLE_THRESHOLD


# ------------------------------------------------------------
# PATHS
# ------------------------------------------------------------

DEFAULT_BASE_DIR = platformdirs.user_data_dir(APP_NAME)
CONFIG_DIR = platformdirs.user_config_dir(APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "activity_tracker_config.json")

DATA_DIR: Optional[str] = None
CSV_FILE: Optional[str] = None
STATE_FILE: Optional[str] = None


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

class AppConfig:
    """Lightweight configuration."""

    def __init__(self) -> None:
        self.target_seconds = DEFAULT_TARGET_SECONDS
        self.weekly_target_seconds = DEFAULT_WEEKLY_TARGET_SECONDS
        self.idle_threshold_seconds = DEFAULT_IDLE_THRESHOLD
        self.save_interval_seconds = DEFAULT_SAVE_INTERVAL_SECONDS

    def validate(self) -> None:
        self.target_seconds = max(3600, min(86400, self.target_seconds))
        self.weekly_target_seconds = max(3600, min(168 * 3600, self.weekly_target_seconds))
        self.idle_threshold_seconds = max(60, min(1800, self.idle_threshold_seconds))
        self.save_interval_seconds = max(60, min(7200, self.save_interval_seconds))


def _config_to_dict(cfg: AppConfig) -> dict:
    return {
        "target_seconds": cfg.target_seconds,
        "weekly_target_seconds": cfg.weekly_target_seconds,
        "idle_threshold_seconds": cfg.idle_threshold_seconds,
        "save_interval_seconds": cfg.save_interval_seconds,
    }


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


_config_cache: Optional[dict] = None


def load_config() -> dict:
    """Load and validate configuration from file."""
    global _config_cache
    ensure_dir(CONFIG_DIR)
    config = AppConfig()

    if not os.path.isfile(CONFIG_FILE):
        _config_cache = _config_to_dict(config)
        return _config_cache

    try:
        with open(CONFIG_FILE, "r") as f:
            config_data = json.load(f)
            config.target_seconds = config_data.get("target_seconds", DEFAULT_TARGET_SECONDS)
            config.weekly_target_seconds = config_data.get("weekly_target_seconds", DEFAULT_WEEKLY_TARGET_SECONDS)
            config.idle_threshold_seconds = config_data.get("idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD)
            config.save_interval_seconds = config_data.get("save_interval_seconds", DEFAULT_SAVE_INTERVAL_SECONDS)
            config.validate()
            merged = _config_to_dict(config)
            # Preserve extra keys from the stored config (e.g. data_dir, locale)
            for k, v in config_data.items():
                if k not in ("target_seconds", "weekly_target_seconds", "idle_threshold_seconds", "save_interval_seconds"):
                    merged[k] = v
            _config_cache = merged
            return _config_cache
    except Exception as e:
        print(f"Warning: Invalid config, using defaults: {e}")
        _config_cache = _config_to_dict(config)
        return _config_cache


def save_config(config: dict) -> None:
    """Save configuration with validation."""
    global _config_cache
    ensure_dir(CONFIG_DIR)

    try:
        cfg = AppConfig()
        cfg.target_seconds = config.get("target_seconds", DEFAULT_TARGET_SECONDS)
        cfg.weekly_target_seconds = config.get("weekly_target_seconds", DEFAULT_WEEKLY_TARGET_SECONDS)
        cfg.idle_threshold_seconds = config.get("idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD)
        cfg.save_interval_seconds = config.get("save_interval_seconds", DEFAULT_SAVE_INTERVAL_SECONDS)
        cfg.validate()
        # Start with validated core keys
        merged = _config_to_dict(cfg)
        # Preserve any extra keys from the input (e.g. data_dir, locale)
        for k, v in config.items():
            if k not in ("target_seconds", "weekly_target_seconds", "idle_threshold_seconds", "save_interval_seconds"):
                merged[k] = v
        _config_cache = merged
        with open(CONFIG_FILE, "w") as f:
            json.dump(_config_cache, f, indent=2)
    except Exception as e:
        print(f"Warning: Invalid config values: {e}")
        cfg = AppConfig()
        merged = _config_to_dict(cfg)
        # Also preserve extra keys in the fallback path
        for k, v in config.items():
            if k not in ("target_seconds", "weekly_target_seconds", "idle_threshold_seconds", "save_interval_seconds"):
                merged[k] = v
        _config_cache = merged
        with open(CONFIG_FILE, "w") as f:
            json.dump(_config_cache, f, indent=2)


def get_config_value(key: str, default: Any = None) -> Any:
    config = load_config()
    return config.get(key, default)


def set_config_value(key: str, value: Any) -> None:
    config = load_config()
    config[key] = value
    save_config(config)


def get_configured_data_dir() -> str:
    config = load_config()
    configured_dir = config.get("data_dir")
    if configured_dir:
        return os.path.expanduser(configured_dir)
    return DEFAULT_BASE_DIR


def set_data_dir(path: str) -> None:
    global DATA_DIR, CSV_FILE, STATE_FILE, _csv_cache, _csv_cache_time
    DATA_DIR = os.path.expanduser(path)
    ensure_dir(DATA_DIR)
    CSV_FILE = os.path.join(DATA_DIR, "activity_tracker_log.csv")
    STATE_FILE = os.path.join(DATA_DIR, "activity_tracker_state.json")
    # Invalidate caches so the next read picks up the new location
    _csv_cache = None
    _csv_cache_time = 0.0


def persist_data_dir(path: str) -> None:
    config = load_config()
    config["data_dir"] = os.path.expanduser(path)
    save_config(config)


def reset_data_dir_to_default() -> None:
    config = load_config()
    if "data_dir" in config:
        del config["data_dir"]
    save_config(config)
    set_data_dir(DEFAULT_BASE_DIR)


# ------------------------------------------------------------
# Config wrappers
# ------------------------------------------------------------

def load_target() -> int:
    return int(get_config_value("target_seconds", DEFAULT_TARGET_SECONDS))


def persist_target(s: int) -> None:
    set_config_value("target_seconds", int(s))


def load_weekly_target() -> int:
    return int(get_config_value("weekly_target_seconds", DEFAULT_WEEKLY_TARGET_SECONDS))


def persist_weekly_target(s: int) -> None:
    set_config_value("weekly_target_seconds", int(s))


def load_idle_threshold() -> int:
    return int(get_config_value("idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD))


def persist_idle_threshold(s: int) -> None:
    set_config_value("idle_threshold_seconds", int(s))


def load_save_interval() -> int:
    return int(get_config_value("save_interval_seconds", DEFAULT_SAVE_INTERVAL_SECONDS))


def persist_save_interval(s: int) -> None:
    set_config_value("save_interval_seconds", int(s))


# ------------------------------------------------------------
# FORMATTING HELPERS
# ------------------------------------------------------------

def hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def format_hours_decimal(seconds: float) -> str:
    return f"{seconds / 3600:.2f} h"


def format_hours(seconds: float) -> str:
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h:02d}:{m:02d}"


def format_delta(seconds: float) -> str:
    s = int(seconds)
    sign = "+" if s >= 0 else "-"
    s = abs(s)
    h = s // 3600
    m = (s % 3600) // 60
    icon = "✅" if sign == "+" else "⚠️"
    return f"{sign}{h:02d}:{m:02d} {icon}"


def format_delta_decimal(seconds: float) -> str:
    value = seconds / 3600
    sign = "+" if value >= 0 else ""
    icon = "✅" if value >= 0 else "⚠️"
    return f"{sign}{value:.2f} h {icon}"


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def get_status_icon(is_idle: bool, active_today: float, target_work_seconds: int) -> str:
    if is_idle:
        return "🔴"
    if active_today < target_work_seconds:
        return "🟡"
    return "🟢"


# ------------------------------------------------------------
# SESSION TRACKER
# ------------------------------------------------------------

class SessionTracker:
    """Tracks the current session's time, idle, and unsaved deltas.

    This is pure data logic — no UI, no platform code.  The caller
    (the menu app) is responsible for scheduling periodic saves.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Start a fresh session (called at init and after midnight)."""
        now = datetime.now()
        self.start_time: datetime = now
        self.last_tick_date = now.date()
        self.first_activity_this_day: Optional[datetime] = None
        self.total_idle_session: float = 0.0
        self.idle_start: Optional[datetime] = None
        self.saved_total_session: float = 0.0
        self.saved_active_session: float = 0.0
        self.saved_idle_session: float = 0.0

    # ── Runtime calculations ───────────────────────────────

    def calculate_current_session(
        self, idle_threshold: int, get_idle_time_fn
    ) -> tuple:
        """Return (now, total_session, active_session, idle_session, is_idle)."""
        now = datetime.now()
        idle_time = get_idle_time_fn()

        if idle_time > idle_threshold:
            if self.idle_start is None:
                self.idle_start = now
        else:
            if self.idle_start is not None:
                self.total_idle_session += (now - self.idle_start).total_seconds()
                self.idle_start = None

        current_idle = self.total_idle_session
        if self.idle_start is not None:
            current_idle += (now - self.idle_start).total_seconds()

        total_session = (now - self.start_time).total_seconds()
        active_session = max(total_session - current_idle, 0)
        is_idle = idle_time > idle_threshold

        return now, total_session, active_session, current_idle, is_idle

    def calculate_unsaved_delta(
        self, total_session: float, active_session: float, idle_session: float
    ) -> tuple:
        """Return (delta_total, delta_active, delta_idle) since last save."""
        delta_total = max(total_session - self.saved_total_session, 0)
        delta_active = max(active_session - self.saved_active_session, 0)
        delta_idle = max(idle_session - self.saved_idle_session, 0)
        return delta_total, delta_active, delta_idle

    def on_tick(self, is_idle: bool) -> None:
        """Call on every tick to handle midnight rollover and first activity."""
        now = datetime.now()
        if now.date() > self.last_tick_date:
            self.first_activity_this_day = None
        if self.first_activity_this_day is None and not is_idle:
            self.first_activity_this_day = now
        self.last_tick_date = now.date()

    def mark_saved(
        self,
        total_session: float,
        active_session: float,
        idle_session: float,
    ) -> None:
        """Update saved-watermark counters after a successful CSV write."""
        self.saved_total_session = total_session
        self.saved_active_session = active_session
        self.saved_idle_session = idle_session

    # ── Report building ────────────────────────────────────

    def build_report(
        self,
        now: datetime,
        total_session: float,
        active_session: float,
        idle_session: float,
        csv_data: Optional[dict] = None,
    ) -> dict:
        """Combine CSV + unsaved delta into a single report dict."""
        date_str = now.date().isoformat()
        csv_day = get_day_from_csv(date_str, csv_data)
        delta_total, delta_active, delta_idle = self.calculate_unsaved_delta(
            total_session, active_session, idle_session,
        )

        today_start_time = csv_day["start_time"]
        if not today_start_time:
            if self.first_activity_this_day:
                today_start_time = self.first_activity_this_day.strftime("%H:%M:%S")
            else:
                today_start_time = self.start_time.strftime("%H:%M:%S")

        return {
            "date": date_str,
            "total_seconds": csv_day["total_seconds"] + delta_total,
            "active_seconds": csv_day["active_seconds"] + delta_active,
            "idle_seconds": csv_day["idle_seconds"] + delta_idle,
            "start_time": today_start_time,
            "end_time": now.strftime("%H:%M:%S"),
            "last_updated": csv_day["last_updated"],
        }

    # ── State persistence ──────────────────────────────────

    def write_state(
        self,
        now: datetime,
        total_session: float,
        active_session: float,
        idle_session: float,
        dirty: bool = True,
    ) -> None:
        state = {
            "dirty": dirty,
            "date": now.date().isoformat(),
            "session_start": self.start_time.isoformat(),
            "last_seen": now.isoformat(),
            "total_session": round(total_session, 0),
            "active_session": round(active_session, 0),
            "idle_session": round(idle_session, 0),
            "saved_total_session": round(self.saved_total_session, 0),
            "saved_active_session": round(self.saved_active_session, 0),
            "saved_idle_session": round(self.saved_idle_session, 0),
            "is_idle": idle_session != 0,
            "data_dir": DATA_DIR,
            "csv_file": CSV_FILE,
            "state_file": STATE_FILE,
        }
        write_state(state)


# ------------------------------------------------------------
# CSV HANDLING
# ------------------------------------------------------------

CSV_FIELDS = [
    "date",
    "start_time",
    "end_time",
    "total_seconds",
    "active_seconds",
    "idle_seconds",
    "total_hours",
    "active_hours",
    "idle_hours",
    "last_updated",
]

_csv_cache: Optional[dict] = None
_csv_cache_time: float = 0.0
CSV_CACHE_TTL: float = 10.0


def read_csv_data(force: bool = False) -> dict:
    """Read the daily CSV into a ``dict[date_str -> row_dict]``."""
    global _csv_cache, _csv_cache_time

    if not force and _csv_cache is not None and (time.time() - _csv_cache_time) < CSV_CACHE_TTL:
        return _csv_cache

    _csv_cache = {}
    if not CSV_FILE or not os.path.isfile(CSV_FILE):
        _csv_cache_time = time.time()
        return _csv_cache

    try:
        with open(CSV_FILE, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date = row.get("date")
                if date:
                    _csv_cache[date] = row
    except (csv.Error, UnicodeDecodeError, IOError) as e:
        print(f"Warning: CSV reading error: {e}. Using empty data.")
        _csv_cache = {}

    _csv_cache_time = time.time()
    return _csv_cache


def write_csv_data(data: dict) -> None:
    """Write the ``dict[date_str -> row_dict]`` back to CSV, sorted by date."""
    if not DATA_DIR:
        return
    ensure_dir(DATA_DIR)
    if not CSV_FILE:
        return

    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for date_key in sorted(data.keys()):
            writer.writerow(data[date_key])


def get_day_from_csv(date_str: str, data: Optional[dict] = None) -> dict:
    if data is None:
        data = read_csv_data()

    if date_str not in data:
        return {
            "date": date_str,
            "start_time": "",
            "end_time": "",
            "total_seconds": 0.0,
            "active_seconds": 0.0,
            "idle_seconds": 0.0,
            "total_hours": 0.0,
            "active_hours": 0.0,
            "idle_hours": 0.0,
            "last_updated": "",
        }

    row = data[date_str]
    return {
        "date": row.get("date", date_str),
        "start_time": row.get("start_time", ""),
        "end_time": row.get("end_time", ""),
        "total_seconds": float(row.get("total_seconds", 0) or 0),
        "active_seconds": float(row.get("active_seconds", 0) or 0),
        "idle_seconds": float(row.get("idle_seconds", 0) or 0),
        "total_hours": float(row.get("total_hours", 0) or 0),
        "active_hours": float(row.get("active_hours", 0) or 0),
        "idle_hours": float(row.get("idle_hours", 0) or 0),
        "last_updated": row.get("last_updated", ""),
    }


def add_delta_to_csv(
    first_activity_time: Optional[datetime],
    date_str: str,
    start_time: datetime,
    end_time: datetime,
    delta_total: float,
    delta_active: float,
    delta_idle: float,
) -> None:
    """Accumulate a time delta into the CSV for the given date."""
    if delta_total <= 0:
        return

    data = read_csv_data()
    existing = get_day_from_csv(date_str, data)

    existing_total = existing["total_seconds"]
    existing_active = existing["active_seconds"]
    existing_idle = existing["idle_seconds"]

    if existing["start_time"]:
        csv_start_time = existing["start_time"]
    elif first_activity_time:
        csv_start_time = first_activity_time.strftime("%H:%M:%S")
    else:
        csv_start_time = start_time.strftime("%H:%M:%S")

    new_total = existing_total + delta_total
    new_active = existing_active + delta_active
    new_idle = existing_idle + delta_idle

    data[date_str] = {
        "date": date_str,
        "start_time": csv_start_time,
        "end_time": end_time.strftime("%H:%M:%S"),
        "total_seconds": round(new_total, 0),
        "active_seconds": round(new_active, 0),
        "idle_seconds": round(new_idle, 0),
        "total_hours": hours(new_total),
        "active_hours": hours(new_active),
        "idle_hours": hours(new_idle),
        "last_updated": end_time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    write_csv_data(data)


def get_current_week_dates() -> list[str]:
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(days=i)).isoformat() for i in range(7)]


def get_weekly_seconds_from_csv(data: Optional[dict] = None) -> float:
    if data is None:
        data = read_csv_data()
    total = 0.0
    for day in get_current_week_dates():
        if day in data:
            total += float(data[day].get("active_seconds", 0) or 0)
    return total


# ------------------------------------------------------------
# STATE HANDLING / SESSION RECOVERY
# ------------------------------------------------------------

def read_state() -> Optional[dict]:
    if not STATE_FILE or not os.path.isfile(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def write_state(state: dict) -> None:
    if not DATA_DIR:
        return
    ensure_dir(DATA_DIR)
    if not STATE_FILE:
        return
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def mark_state_clean() -> None:
    state = read_state()
    if not state:
        return
    state["dirty"] = False
    state["cleaned_at"] = datetime.now().isoformat()
    write_state(state)


def recover_previous_session_if_needed() -> Optional[dict]:
    """If the previous session ended dirty, save unsaved delta and return info."""
    state = read_state()
    if not state:
        return None
    if not state.get("dirty", False):
        return None

    try:
        date_str = state["date"]
        start_time = parse_datetime(state["session_start"])
        last_seen = parse_datetime(state["last_seen"])

        total_session = float(state.get("total_session", 0))
        active_session = float(state.get("active_session", 0))
        idle_session = float(state.get("idle_session", 0))

        saved_total = float(state.get("saved_total_session", 0))
        saved_active = float(state.get("saved_active_session", 0))
        saved_idle = float(state.get("saved_idle_session", 0))

        delta_total = max(total_session - saved_total, 0)
        delta_active = max(active_session - saved_active, 0)
        delta_idle = max(idle_session - saved_idle, 0)

        if start_time and last_seen and delta_total > 0:
            add_delta_to_csv(None, date_str, start_time, last_seen, delta_total, delta_active, delta_idle)

        state["dirty"] = False
        state["recovered_at"] = datetime.now().isoformat()
        write_state(state)

        return {
            "date": date_str,
            "recovered_seconds": delta_total,
            "last_seen": last_seen.strftime("%Y-%m-%d %H:%M:%S") if last_seen else "",
        }
    except Exception as e:
        return {"error": str(e)}

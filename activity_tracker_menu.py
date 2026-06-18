import rumps
import subprocess
import time
from datetime import datetime, timedelta
import os
import json
import sys
import plistlib
import threading
from pathlib import Path
import platformdirs
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel, Field, ValidationError, ConfigDict
from typing import Optional

from AppKit import (
    NSOpenPanel,
    NSModalResponseOK,
    NSAlertFirstButtonReturn,
    NSAlert,
    NSSlider,
    NSTextField,
    NSView
)

import i18n


# ------------------------------------------------------------
# Version fallback for development mode
# ------------------------------------------------------------

try:
    from version_generated import APP_FULL_VERSION, APP_BUILD_DATE
except Exception:
    APP_FULL_VERSION = "dev"
    APP_BUILD_DATE = "dev"


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

APP_NAME = "ActivityTracker"

IDLE_THRESHOLD = 300        # idle after 5 minutes
UPDATE_INTERVAL = 5         # UI + state update every 5 seconds
WRITE_INTERVAL = 3600       # CSV auto-save every 60 minutes

DEFAULT_TARGET_SECONDS = 8 * 3600
DEFAULT_WEEKLY_TARGET_SECONDS = 40 * 3600

TARGET_WORK_SECONDS = DEFAULT_TARGET_SECONDS
WEEKLY_TARGET_SECONDS = DEFAULT_WEEKLY_TARGET_SECONDS


# ------------------------------------------------------------
# Persistent Storage / Settings
# Using platformdirs for cross-platform support
# ------------------------------------------------------------

DEFAULT_BASE_DIR = platformdirs.user_data_dir(APP_NAME)

CONFIG_DIR = platformdirs.user_config_dir(APP_NAME)

CONFIG_FILE = os.path.join(CONFIG_DIR, "activity_tracker_config.json")

DATA_DIR = None
CSV_FILE = None
STATE_FILE = None


# Configuration Model with Validation
# Using pydantic for automatic type validation and error handling
# ============================================================

class AppConfig(BaseModel):
    """Configuration model with validation."""
    model_config = ConfigDict(validate_assignment=True)
    
    target_seconds: int = Field(
        default=DEFAULT_TARGET_SECONDS,
        ge=3600,  # At least 1 hour
        le=43200  # At most 12 hours
    )
    weekly_target_seconds: int = Field(
        default=DEFAULT_WEEKLY_TARGET_SECONDS,
        ge=10 * 3600,  # At least 10 hours/week
        le=168 * 3600  # At most 168 hours/week (full week)
    )
    data_dir: Optional[str] = None


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def load_config():
    """Load and validate configuration from file."""
    ensure_dir(CONFIG_DIR)

    if not os.path.isfile(CONFIG_FILE):
        return AppConfig().model_dump()

    try:
        with open(CONFIG_FILE, "r") as f:
            config_data = json.load(f)
        # Validate and return the config
        validated_config = AppConfig(**config_data)
        return validated_config.model_dump()
    except Exception as e:
        print(f"Warning: Invalid config, using defaults: {e}")
        return AppConfig().model_dump()


def save_config(config):
    """Save configuration with pydantic validation."""
    ensure_dir(CONFIG_DIR)
    
    try:
        # Validate before saving
        validated_config = AppConfig(**config)
        with open(CONFIG_FILE, "w") as f:
            json.dump(validated_config.model_dump(), f, indent=2)
    except ValidationError as e:
        print(f"Warning: Invalid config values: {e}")
        # Save only valid fields
        valid_config = AppConfig()
        with open(CONFIG_FILE, "w") as f:
            json.dump(valid_config.model_dump(), f, indent=2)


def get_config_value(key, default=None):
    """Get a single config value, loading from disk if needed."""
    config = load_config()
    return config.get(key, default)


def set_config_value(key, value):
    """Set a single config value and save to disk."""
    config = load_config()
    config[key] = value
    save_config(config)


def get_configured_data_dir():
    config = load_config()
    configured_dir = config.get("data_dir")

    if configured_dir:
        return os.path.expanduser(configured_dir)

    return DEFAULT_BASE_DIR


def set_data_dir(path):
    global DATA_DIR, CSV_FILE, STATE_FILE

    DATA_DIR = os.path.expanduser(path)
    ensure_dir(DATA_DIR)

    CSV_FILE = os.path.join(DATA_DIR, "activity_tracker_log.csv")
    STATE_FILE = os.path.join(DATA_DIR, "activity_tracker_state.json")


def persist_data_dir(path):
    config = load_config()
    config["data_dir"] = os.path.expanduser(path)
    save_config(config)


def reset_data_dir_to_default():
    config = load_config()

    if "data_dir" in config:
        del config["data_dir"]

    save_config(config)
    set_data_dir(DEFAULT_BASE_DIR)


def load_target():
    return int(get_config_value("target_seconds", DEFAULT_TARGET_SECONDS))


def persist_target(seconds):
    set_config_value("target_seconds", int(seconds))


def load_weekly_target():
    return int(get_config_value("weekly_target_seconds", DEFAULT_WEEKLY_TARGET_SECONDS))


def persist_weekly_target(seconds):
    set_config_value("weekly_target_seconds", int(seconds))


# Initial settings
set_data_dir(get_configured_data_dir())
TARGET_WORK_SECONDS = load_target()
WEEKLY_TARGET_SECONDS = load_weekly_target()


# ------------------------------------------------------------
# Version Handling
# ------------------------------------------------------------

def get_app_bundle_path():
    executable = Path(sys.executable).resolve()

    for parent in [executable] + list(executable.parents):
        if parent.suffix == ".app":
            return str(parent)

    return None


def get_bundle_info_plist():
    try:
        app_path = get_app_bundle_path()

        if not app_path:
            return None

        plist_path = Path(app_path) / "Contents" / "Info.plist"

        if not plist_path.exists():
            return None

        with open(plist_path, "rb") as f:
            return plistlib.load(f)

    except Exception:
        return None


def get_bundle_version():
    plist = get_bundle_info_plist()

    if plist:
        version = plist.get("CFBundleShortVersionString", "unknown")
        build = plist.get("CFBundleVersion", "")

        if build:
            return f"{version} ({build})"

        return version

    return APP_FULL_VERSION


def get_bundle_build_date():
    plist = get_bundle_info_plist()

    if plist:
        return plist.get("ActivityTrackerBuildDate", APP_BUILD_DATE)

    return APP_BUILD_DATE


# ------------------------------------------------------------
# Enterprise Autostart / LaunchAgent
# ------------------------------------------------------------

LAUNCH_AGENT_LABEL = "com.markus.activitytracker"
LAUNCH_AGENT_DIR = os.path.expanduser("~/Library/LaunchAgents")
LAUNCH_AGENT_FILE = os.path.join(
    LAUNCH_AGENT_DIR,
    f"{LAUNCH_AGENT_LABEL}.plist"
)

LOG_DIR = os.path.expanduser("~/Library/Logs/ActivityTracker")
LAUNCH_AGENT_OUT = os.path.join(LOG_DIR, "activitytracker.out.log")
LAUNCH_AGENT_ERR = os.path.join(LOG_DIR, "activitytracker.err.log")


def launchctl_domain():
    return f"gui/{os.getuid()}"


def get_app_executable_path():
    app_path = get_app_bundle_path()

    if not app_path:
        return None

    executable_dir = Path(app_path) / "Contents" / "MacOS"

    if not executable_dir.exists():
        return None

    executables = [
        item for item in executable_dir.iterdir()
        if item.is_file() and os.access(item, os.X_OK)
    ]

    if not executables:
        return None

    return str(executables[0])


def write_launch_agent_plist():
    app_executable = get_app_executable_path()

    if not app_executable:
        raise RuntimeError(
            "Autostart requires the packaged ActivityTracker.app. "
            "Build with py2app first and run the .app."
        )

    ensure_dir(LAUNCH_AGENT_DIR)
    ensure_dir(LOG_DIR)

    plist = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            app_executable
        ],
        "RunAtLoad": True,
        "KeepAlive": False,
        "LimitLoadToSessionType": "Aqua",
        "StandardOutPath": LAUNCH_AGENT_OUT,
        "StandardErrorPath": LAUNCH_AGENT_ERR,
        "WorkingDirectory": str(Path(app_executable).parent)
    }

    with open(LAUNCH_AGENT_FILE, "wb") as f:
        plistlib.dump(plist, f)


def install_autostart():
    write_launch_agent_plist()

    # These calls can fail temporarily, retry with exponential backoff
    _bootstrap_launchctl()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
def _bootstrap_launchctl():
    """Bootstrap launchctl with retry logic."""
    subprocess.run(
        ["launchctl", "bootout", launchctl_domain(), LAUNCH_AGENT_FILE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    subprocess.run(
        ["launchctl", "bootstrap", launchctl_domain(), LAUNCH_AGENT_FILE],
        check=False
    )

    subprocess.run(
        ["launchctl", "enable", f"{launchctl_domain()}/{LAUNCH_AGENT_LABEL}"],
        check=False
    )


def uninstall_autostart():
    _unbootstrap_launchctl()

    if os.path.isfile(LAUNCH_AGENT_FILE):
        os.remove(LAUNCH_AGENT_FILE)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
def _unbootstrap_launchctl():
    """Unbootstrap launchctl with retry logic."""
    subprocess.run(
        ["launchctl", "bootout", launchctl_domain(), LAUNCH_AGENT_FILE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def is_autostart_installed():
    return os.path.isfile(LAUNCH_AGENT_FILE)


def is_autostart_loaded():
    result = subprocess.run(
        ["launchctl", "print", f"{launchctl_domain()}/{LAUNCH_AGENT_LABEL}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return result.returncode == 0


# ------------------------------------------------------------
# Native macOS Dialogs
# ------------------------------------------------------------

def choose_data_folder():
    panel = NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(False)
    panel.setCanCreateDirectories_(True)
    panel.setTitle_("Select ActivityTracker Data Folder")
    panel.setPrompt_("Use Folder")

    result = panel.runModal()

    if result == NSModalResponseOK:
        url = panel.URLs()[0]
        return url.path()

    return None


def ask_target_with_slider(current_hours, title="Set Target", min_hours=4.0, max_hours=12.0):
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_("Adjust working hours.")
    alert.addButtonWithTitle_("OK")
    alert.addButtonWithTitle_("Cancel")

    container = NSView.alloc().initWithFrame_(((0, 0), (280, 70)))

    slider = NSSlider.alloc().initWithFrame_(((0, 30), (280, 24)))
    slider.setMinValue_(min_hours)
    slider.setMaxValue_(max_hours)
    slider.setFloatValue_(float(current_hours))

    label = NSTextField.alloc().initWithFrame_(((0, 0), (280, 24)))
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setStringValue_(f"{float(current_hours):.2f} hours")

    container.addSubview_(slider)
    container.addSubview_(label)

    alert.setAccessoryView_(container)
    response = alert.runModal()

    if response == NSAlertFirstButtonReturn:
        return float(slider.floatValue())

    return None


# ------------------------------------------------------------
# macOS Idle Time
# ------------------------------------------------------------

def get_idle_time():
    try:
        output = subprocess.check_output(
            ["ioreg", "-c", "IOHIDSystem"],
            stderr=subprocess.DEVNULL
        ).decode()

        for line in output.split("\n"):
            if "HIDIdleTime" in line:
                ns = int(line.split("=")[-1].strip())
                return ns / 1_000_000_000

    except Exception:
        return 0

    return 0


# ------------------------------------------------------------
# Formatting
# ------------------------------------------------------------

def hours(seconds):
    return round(seconds / 3600, 2)

def format_hours_decimal(seconds):
    return f"{seconds / 3600:.2f} h"

def format_hours(seconds):
    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    return f"{hours:02d}:{minutes:02d}"

def format_delta(seconds):
    seconds = int(seconds)

    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    icon = "✅" if sign == "+" else "⚠️"

    return f"{sign}{hours:02d}:{minutes:02d} {icon}"

def format_delta_decimal(seconds):
    value = seconds / 3600
    sign = "+" if value >= 0 else ""
    icon = "✅" if value >= 0 else "⚠️"
    return f"{sign}{value:.2f} h {icon}"

def parse_datetime(value):
    """Parse ISO format datetime strings via stdlib datetime.fromisoformat."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None

def get_status_icon(is_idle, active_today):
    if is_idle:
        return "🔴"

    if active_today < TARGET_WORK_SECONDS:
        return "🟡"

    return "🟢"

# ------------------------------------------------------------
# CSV Handling
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
    "last_updated"
]

CSV_STR_FIELDS = ["date", "start_time", "end_time", "last_updated"]
CSV_NUM_FIELDS = [
    "total_seconds",
    "active_seconds",
    "idle_seconds",
    "total_hours",
    "active_hours",
    "idle_hours"
]


def _pd():
    """Lazy-import pandas to keep it off the latency-sensitive module-load path."""
    import pandas as pd
    return pd


def read_csv_data():
    """Read the daily CSV into a ``dict[date_str -> row_dict]`` via pandas."""
    if not os.path.isfile(CSV_FILE):
        return {}

    pd = _pd()

    try:
        df = pd.read_csv(
            CSV_FILE,
            dtype={col: "string" for col in CSV_STR_FIELDS}
        )
    except Exception as e:
        print(f"Warning: CSV reading error: {e}. Using empty data.")
        return {}

    # Empty strings, not NaN: a NaN start_time reads back truthy and would
    # corrupt add_delta_to_csv's "preserve existing start_time" check.
    for col in CSV_STR_FIELDS:
        if col in df.columns:
            df[col] = df[col].fillna("")

    # Mirror the old float(x or 0) coercion for numeric columns.
    for col in CSV_NUM_FIELDS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "date" in df.columns:
        df = df[df["date"] != ""]

    data = {}
    for record in df.to_dict("records"):
        # Coerce to native float/str so numpy scalar types never leak into
        # downstream round()/strftime()/JSON state.
        row = {}
        for field in CSV_FIELDS:
            if field not in record:
                continue
            if field in CSV_NUM_FIELDS:
                row[field] = float(record[field])
            else:
                row[field] = str(record[field])
        data[row["date"]] = row

    return data


def write_csv_data(data):
    """Write the ``dict[date_str -> row_dict]`` back to CSV, sorted by date."""
    ensure_dir(DATA_DIR)

    pd = _pd()

    df = pd.DataFrame(list(data.values()))
    # Guarantee the exact 10 columns in order even when data is empty.
    df = df.reindex(columns=CSV_FIELDS)

    for col in CSV_STR_FIELDS:
        df[col] = df[col].fillna("")

    if not df.empty:
        # ISO date strings sort chronologically; stable to match sorted(keys).
        df = df.sort_values("date", kind="stable").reset_index(drop=True)

    df.to_csv(CSV_FILE, index=False)


def get_day_from_csv(date_str):
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
            "last_updated": ""
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
        "last_updated": row.get("last_updated", "")
    }


def add_delta_to_csv(date_str, start_time, end_time, delta_total, delta_active, delta_idle):
    if delta_total <= 0:
        return

    data = read_csv_data()
    existing = get_day_from_csv(date_str)

    existing_total = existing["total_seconds"]
    existing_active = existing["active_seconds"]
    existing_idle = existing["idle_seconds"]

    if existing["start_time"]:
        csv_start_time = existing["start_time"]
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
        "last_updated": end_time.strftime("%Y-%m-%d %H:%M:%S")
    }

    write_csv_data(data)


def get_current_week_dates():
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())

    return [
        (monday + timedelta(days=i)).isoformat()
        for i in range(7)
    ]


def get_weekly_seconds_from_csv():
    data = read_csv_data()
    total = 0.0

    for day in get_current_week_dates():
        if day in data:
            total += float(data[day].get("active_seconds", 0) or 0)

    return total


# ------------------------------------------------------------
# State Handling / Session Recovery
# ------------------------------------------------------------

def read_state():
    if not os.path.isfile(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def write_state(state):
    ensure_dir(DATA_DIR)

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def mark_state_clean():
    state = read_state()

    if not state:
        return

    state["dirty"] = False
    state["cleaned_at"] = datetime.now().isoformat()
    write_state(state)


def recover_previous_session_if_needed():
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
            add_delta_to_csv(
                date_str,
                start_time,
                last_seen,
                delta_total,
                delta_active,
                delta_idle
            )

        state["dirty"] = False
        state["recovered_at"] = datetime.now().isoformat()
        write_state(state)

        return {
            "date": date_str,
            "recovered_seconds": delta_total,
            "last_seen": last_seen.strftime("%Y-%m-%d %H:%M:%S") if last_seen else ""
        }

    except Exception as e:
        return {
            "error": str(e)
        }


# ------------------------------------------------------------
# Dashboard script path
# ------------------------------------------------------------

def find_dashboard_script():
    """Locate generate_dashboard.py in the source tree or the py2app bundle.

    Returns the first existing path. If neither exists, falls back to the
    local source path (which may not exist) so the caller can surface a
    "script not found" error against a meaningful location.
    """
    local_path = Path(__file__).resolve().parent / "scripts" / "generate_dashboard.py"

    if local_path.exists():
        return local_path

    app_path = get_app_bundle_path()

    if app_path:
        bundle_path = (
            Path(app_path)
            / "Contents"
            / "Resources"
            / "scripts"
            / "generate_dashboard.py"
        )

        if bundle_path.exists():
            return bundle_path

    # Neither location exists; return the local path as a fallback so the
    # caller's .exists() check fails against a sensible path.
    return local_path


# ------------------------------------------------------------
# Menubar App
# ------------------------------------------------------------

class ActivityTrackerApp(rumps.App):

    def __init__(self):
        super().__init__("🟡 0.00h", quit_button=None)

        # initialize translations
        cfg = load_config()
        i18n.set_locale(cfg.get("locale"))

        self.recovery_result = recover_previous_session_if_needed()

        # Runtime session state
        self.start_time = datetime.now()
        self.total_idle_session = 0.0
        self.idle_start = None

        # Last saved counters
        self.saved_total_session = 0.0
        self.saved_active_session = 0.0
        self.saved_idle_session = 0.0

        self.last_write_time = time.time()
        self.last_save_display = i18n.t("LAST_SAVE_NONE")
        self.dashboard_refresh_event = threading.Event()
        self.dashboard_thread = None

        # Main menu items
        self.menu_active = rumps.MenuItem(i18n.t("MENU_ACTIVE", value="-"))
        self.menu_idle = rumps.MenuItem(i18n.t("MENU_IDLE", value="-"))
        self.menu_total = rumps.MenuItem(i18n.t("MENU_TOTAL", value="-"))

        self.menu_today_target = rumps.MenuItem(i18n.t("MENU_TODAY_TARGET", value="-"))
        self.menu_today_overtime = rumps.MenuItem(i18n.t("TODAY_OVERTIME_NEG", value="-"))

        self.menu_week_total = rumps.MenuItem(i18n.t("WEEK_TOTAL", value="-", target="-"))
        self.menu_week_overtime = rumps.MenuItem(i18n.t("WEEK_OVERTIME_NEG", value="-"))

        self.menu_start = rumps.MenuItem(i18n.t("MENU_START", value="-"))
        self.menu_update = rumps.MenuItem(i18n.t("MENU_UPDATE", value="-"))
        self.menu_saved = rumps.MenuItem(i18n.t("MENU_SAVED", value="-"))
        self.menu_recovery = rumps.MenuItem(i18n.t("MENU_RECOVERY_NONE"))
        self.menu_csv = rumps.MenuItem(i18n.t("MENU_CSV", path=CSV_FILE or "-"))
        self.menu_state = rumps.MenuItem(i18n.t("MENU_STATE", path=STATE_FILE or "-"))

        self.menu_dashboard = rumps.MenuItem(
            i18n.t("ENTERPRISE_DASHBOARD"),
            callback=self.open_enterprise_dashboard
        )

        # Settings menu
        self.settings_menu = rumps.MenuItem(i18n.t("SETTINGS"))

        self.settings_menu.add(
            rumps.MenuItem(i18n.t("SELECT_DATA_FOLDER"), callback=self.select_data_folder)
        )
        self.settings_menu.add(
            rumps.MenuItem(i18n.t("OPEN_DATA_FOLDER"), callback=self.open_data_folder)
        )
        self.settings_menu.add(
            rumps.MenuItem(i18n.t("RESET_DATA_FOLDER"), callback=self.reset_data_folder)
        )

        self.settings_menu.add(None)

        # Daily target menu
        self.target_menu = rumps.MenuItem(i18n.t("DAILY_TARGET"))
        self.target_6h = rumps.MenuItem("6h", callback=self.set_target_6h)
        self.target_8h = rumps.MenuItem("8h", callback=self.set_target_8h)
        self.target_10h = rumps.MenuItem("10h", callback=self.set_target_10h)
        self.target_slider = rumps.MenuItem(
            i18n.t("SET_DAILY_TARGET_SLIDER"),
            callback=self.set_target_slider
        )

        self.target_menu.add(self.target_6h)
        self.target_menu.add(self.target_8h)
        self.target_menu.add(self.target_10h)
        self.target_menu.add(None)
        self.target_menu.add(self.target_slider)

        self.settings_menu.add(self.target_menu)

        # Weekly target menu
        self.weekly_target_menu = rumps.MenuItem(i18n.t("WEEKLY_TARGET"))
        self.weekly_30h = rumps.MenuItem("30h", callback=self.set_weekly_30h)
        self.weekly_40h = rumps.MenuItem("40h", callback=self.set_weekly_40h)
        self.weekly_50h = rumps.MenuItem("50h", callback=self.set_weekly_50h)
        self.weekly_slider = rumps.MenuItem(
            i18n.t("SET_WEEKLY_TARGET_SLIDER"),
            callback=self.set_weekly_slider
        )

        self.weekly_target_menu.add(self.weekly_30h)
        self.weekly_target_menu.add(self.weekly_40h)
        self.weekly_target_menu.add(self.weekly_50h)
        self.weekly_target_menu.add(None)
        self.weekly_target_menu.add(self.weekly_slider)

        self.settings_menu.add(self.weekly_target_menu)

        self.settings_menu.add(None)

        # Autostart
        self.autostart_item = rumps.MenuItem(
            i18n.t("AUTOSTART_DISABLED"),
            callback=self.toggle_autostart
        )

        self.open_autostart_file_item = rumps.MenuItem(
            i18n.t("OPEN_AUTOSTART_FILE"),
            callback=self.open_autostart_file
        )

        self.settings_menu.add(self.autostart_item)
        self.settings_menu.add(self.open_autostart_file_item)

        self.settings_menu.add(None)

        # Version
        self.version_item = rumps.MenuItem(i18n.t("VERSION", value="-"))
        self.build_date_item = rumps.MenuItem(i18n.t("BUILD", value="-"))

        self.settings_menu.add(self.version_item)
        self.settings_menu.add(self.build_date_item)

        self.force_save_item = rumps.MenuItem(i18n.t("FORCE_SAVE"), callback=self.force_save)
        self.quit_item = rumps.MenuItem(i18n.t("QUIT"), callback=self.quit_app)

        self.menu = [
            self.menu_active,
            self.menu_idle,
            self.menu_total,
            None,
            self.menu_today_target,
            self.menu_today_overtime,
            None,
            self.menu_week_total,
            self.menu_week_overtime,
            None,
            self.menu_start,
            self.menu_update,
            self.menu_saved,
            self.menu_recovery,
            None,
            self.menu_csv,
            self.menu_state,
            None,
            self.settings_menu,
            None,
            self.menu_dashboard,
            None,
            self.force_save_item,
            self.quit_item
        ]

        self.update_autostart_ui()
        self.update_version_ui()
        self.update_target_menu()
        self.update_weekly_target_menu()

        self.timer = rumps.Timer(self.update, UPDATE_INTERVAL)
        self.timer.start()

    # --------------------------------------------------------
    # Runtime Calculations
    # --------------------------------------------------------

    def calculate_current_session(self):
        now = datetime.now()
        idle_time = get_idle_time()

        if idle_time > IDLE_THRESHOLD:
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
        is_idle = idle_time > IDLE_THRESHOLD

        return now, total_session, active_session, current_idle, is_idle

    def calculate_unsaved_delta(self, total_session, active_session, idle_session):
        delta_total = max(total_session - self.saved_total_session, 0)
        delta_active = max(active_session - self.saved_active_session, 0)
        delta_idle = max(idle_session - self.saved_idle_session, 0)

        return delta_total, delta_active, delta_idle

    def get_today_report_from_csv_plus_current_delta(
        self,
        now,
        total_session,
        active_session,
        idle_session
    ):
        date_str = now.date().isoformat()
        csv_day = get_day_from_csv(date_str)

        delta_total, delta_active, delta_idle = self.calculate_unsaved_delta(
            total_session,
            active_session,
            idle_session
        )

        return {
            "date": date_str,
            "total_seconds": csv_day["total_seconds"] + delta_total,
            "active_seconds": csv_day["active_seconds"] + delta_active,
            "idle_seconds": csv_day["idle_seconds"] + delta_idle,
            "start_time": csv_day["start_time"] or self.start_time.strftime("%H:%M:%S"),
            "end_time": now.strftime("%H:%M:%S"),
            "last_updated": csv_day["last_updated"]
        }

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    def save_delta(self):
        now, total_session, active_session, idle_session, _ = self.calculate_current_session()

        delta_total, delta_active, delta_idle = self.calculate_unsaved_delta(
            total_session,
            active_session,
            idle_session
        )

        if delta_total <= 0:
            return

        add_delta_to_csv(
            now.date().isoformat(),
            self.start_time,
            now,
            delta_total,
            delta_active,
            delta_idle
        )

        self.saved_total_session = total_session
        self.saved_active_session = active_session
        self.saved_idle_session = idle_session

        self.last_write_time = time.time()
        self.last_save_display = now.strftime("%H:%M:%S")

        self.save_state(dirty=True)

    def save_state(self, dirty=True):
        now, total_session, active_session, idle_session, is_idle = self.calculate_current_session()

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

            "is_idle": is_idle,
            "data_dir": DATA_DIR,
            "csv_file": CSV_FILE,
            "state_file": STATE_FILE
        }

        write_state(state)

    # --------------------------------------------------------
    # Target settings
    # --------------------------------------------------------

    def set_target(self, seconds):
        global TARGET_WORK_SECONDS

        TARGET_WORK_SECONDS = int(seconds)
        persist_target(seconds)
        self.update_target_menu()

        rumps.notification(
            "ActivityTracker",
            i18n.t("NOTIFICATION_DAILY_TARGET_UPDATED"),
            f"{seconds / 3600:.2f} h"
        )

    def set_target_6h(self, _):
        self.set_target(6 * 3600)

    def set_target_8h(self, _):
        self.set_target(8 * 3600)

    def set_target_10h(self, _):
        self.set_target(10 * 3600)

    def set_target_slider(self, _):
        current_hours = TARGET_WORK_SECONDS / 3600
        value = ask_target_with_slider(
            current_hours,
            title=i18n.t("ASK_DAILY_TARGET_TITLE"),
            min_hours=4.0,
            max_hours=12.0
        )

        if value is not None and value > 0:
            self.set_target(int(value * 3600))

    def update_target_menu(self):
        self.target_6h.title = "6h"
        self.target_8h.title = "8h"
        self.target_10h.title = "10h"

        if TARGET_WORK_SECONDS == 6 * 3600:
            self.target_6h.title += " ✅"
        elif TARGET_WORK_SECONDS == 8 * 3600:
            self.target_8h.title += " ✅"
        elif TARGET_WORK_SECONDS == 10 * 3600:
            self.target_10h.title += " ✅"

    def set_weekly_target(self, seconds):
        global WEEKLY_TARGET_SECONDS

        WEEKLY_TARGET_SECONDS = int(seconds)
        persist_weekly_target(seconds)
        self.update_weekly_target_menu()

        rumps.notification(
            "ActivityTracker",
            i18n.t("NOTIFICATION_WEEKLY_TARGET_UPDATED"),
            f"{seconds / 3600:.2f} h"
        )

    def set_weekly_30h(self, _):
        self.set_weekly_target(30 * 3600)

    def set_weekly_40h(self, _):
        self.set_weekly_target(40 * 3600)

    def set_weekly_50h(self, _):
        self.set_weekly_target(50 * 3600)

    def set_weekly_slider(self, _):
        current_hours = WEEKLY_TARGET_SECONDS / 3600
        value = ask_target_with_slider(
            current_hours,
            title=i18n.t("ASK_WEEKLY_TARGET_TITLE"),
            min_hours=20.0,
            max_hours=60.0
        )

        if value is not None and value > 0:
            self.set_weekly_target(int(value * 3600))

    def update_weekly_target_menu(self):
        self.weekly_30h.title = "30h"
        self.weekly_40h.title = "40h"
        self.weekly_50h.title = "50h"

        if WEEKLY_TARGET_SECONDS == 30 * 3600:
            self.weekly_30h.title += " ✅"
        elif WEEKLY_TARGET_SECONDS == 40 * 3600:
            self.weekly_40h.title += " ✅"
        elif WEEKLY_TARGET_SECONDS == 50 * 3600:
            self.weekly_50h.title += " ✅"

    # --------------------------------------------------------
    # Autostart
    # --------------------------------------------------------

    def update_autostart_ui(self):
        if is_autostart_installed():
            if is_autostart_loaded():
                self.autostart_item.title = i18n.t("AUTOSTART_ENABLED")
            else:
                self.autostart_item.title = i18n.t("AUTOSTART_INSTALLED")
        else:
            self.autostart_item.title = i18n.t("AUTOSTART_DISABLED")

    def toggle_autostart(self, _):
        try:
            if is_autostart_installed():
                uninstall_autostart()
                self.update_autostart_ui()

                rumps.notification(
                    "ActivityTracker",
                    i18n.t("NOTIFICATION_AUTOSTART_DISABLED"),
                    i18n.t("AUTOSTART_LAUNCHAGENT_REMOVED")
                )
            else:
                self.save_delta()
                self.save_state(dirty=True)

                install_autostart()
                self.update_autostart_ui()

                rumps.notification(
                    "ActivityTracker",
                    i18n.t("NOTIFICATION_AUTOSTART_ENABLED"),
                    i18n.t("AUTOSTART_LAUNCHAGENT_INSTALLED")
                )

        except Exception as e:
            rumps.alert(
                title="ActivityTracker Autostart Error",
                message=str(e)
            )

    def open_autostart_file(self, _):
        ensure_dir(LAUNCH_AGENT_DIR)

        if os.path.isfile(LAUNCH_AGENT_FILE):
            subprocess.run(["open", "-R", LAUNCH_AGENT_FILE])
        else:
            subprocess.run(["open", LAUNCH_AGENT_DIR])

    # --------------------------------------------------------
    # Version
    # --------------------------------------------------------

    def update_version_ui(self):
        self.version_item.title = i18n.t("VERSION", value=get_bundle_version())
        self.build_date_item.title = i18n.t("BUILD", value=get_bundle_build_date())

    # --------------------------------------------------------
    # Dashboard
    # --------------------------------------------------------

    def open_enterprise_dashboard(self, _):
        script_path = find_dashboard_script()

        if not script_path.exists():
            rumps.alert(
                title=i18n.t("DASHBOARD_ERROR_TITLE"),
                message=i18n.t("DASHBOARD_SCRIPT_NOT_FOUND", path=str(script_path))
            )
            return

        subprocess.Popen([sys.executable, str(script_path)])
        
        if self.dashboard_thread is None or not self.dashboard_thread.is_alive():
            self.dashboard_refresh_event.clear()
            self.dashboard_thread = threading.Thread(
                target=self._dashboard_refresh_loop,
                args=(script_path,),
                daemon=True
            )
            self.dashboard_thread.start()

    def _dashboard_refresh_loop(self, script_path):
        while not self.dashboard_refresh_event.is_set():
            time.sleep(10)
            subprocess.run(
                [sys.executable, str(script_path), "--data-only"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

    # --------------------------------------------------------
    # UI Update
    # --------------------------------------------------------

    def update(self, _):
        now, total_session, active_session, idle_session, is_idle = self.calculate_current_session()

        if time.time() - self.last_write_time >= WRITE_INTERVAL:
            self.save_delta()

        self.save_state(dirty=True)

        report = self.get_today_report_from_csv_plus_current_delta(
            now,
            total_session,
            active_session,
            idle_session
        )

        active_today = report["active_seconds"]
        idle_today = report["idle_seconds"]
        total_today = report["total_seconds"]

        daily_overtime = active_today - TARGET_WORK_SECONDS

        weekly_from_csv = get_weekly_seconds_from_csv()
        _, delta_active, _ = self.calculate_unsaved_delta(
            total_session,
            active_session,
            idle_session
        )

        weekly_total = weekly_from_csv + delta_active
        weekly_overtime = weekly_total - WEEKLY_TARGET_SECONDS

        status_icon = get_status_icon(is_idle, active_today)
        #self.title = f"{status_icon} {active_today / 3600:.2f}h"
        self.title = f"{status_icon} {format_hours(active_today)}"

        self.menu_active.title = i18n.t("MENU_ACTIVE", value=format_hours(active_today))
        self.menu_idle.title = i18n.t("MENU_IDLE", value=format_hours(idle_today))
        self.menu_total.title = i18n.t("MENU_TOTAL", value=format_hours(total_today))

        self.menu_today_target.title = i18n.t("MENU_TODAY_TARGET", value=format_hours(TARGET_WORK_SECONDS))
        if daily_overtime >= 0:
            self.menu_today_overtime.title = i18n.t("TODAY_OVERTIME_POS", value=format_delta(daily_overtime))
        else:
            self.menu_today_overtime.title = i18n.t("TODAY_OVERTIME_NEG", value=format_delta(daily_overtime))

        self.menu_week_total.title = i18n.t(
            "WEEK_TOTAL",
            value=format_hours(weekly_total),
            target=format_hours(WEEKLY_TARGET_SECONDS)
        )
        if weekly_overtime >= 0:
            self.menu_week_overtime.title = i18n.t("WEEK_OVERTIME_POS", value=format_delta(weekly_overtime))
        else:
            self.menu_week_overtime.title = i18n.t("WEEK_OVERTIME_NEG", value=format_delta(weekly_overtime))

        self.menu_start.title = i18n.t("MENU_START", value=self.start_time.strftime('%H:%M:%S'))
        self.menu_update.title = i18n.t("MENU_UPDATE", value=now.strftime('%H:%M:%S'))
        self.menu_saved.title = i18n.t("MENU_SAVED", value=self.last_save_display)

        if self.recovery_result and "recovered_seconds" in self.recovery_result:
            self.menu_recovery.title = i18n.t(
                "MENU_RECOVERY_ADDED",
                value=format_hours(self.recovery_result["recovered_seconds"])
            )
        elif self.recovery_result and "error" in self.recovery_result:
            self.menu_recovery.title = i18n.t("MENU_RECOVERY_ERROR")
        else:
            self.menu_recovery.title = i18n.t("MENU_RECOVERY_NONE")

        self.menu_csv.title = i18n.t("MENU_CSV", path=CSV_FILE or "-")
        self.menu_state.title = i18n.t("MENU_STATE", path=STATE_FILE or "-")

        # Autostart / version / target-menu states only change on user action,
        # so they are refreshed in __init__ and their setters — not every tick.
        # (is_autostart_loaded() spawns a launchctl subprocess; avoid it here.)

        remaining = max(TARGET_WORK_SECONDS - active_today, 0)

        self._tooltip = (
            i18n.t("TOOLTIP_ACTIVE", value=format_hours(active_today)) + "\n"
            + i18n.t("TOOLTIP_IDLE", value=format_hours(idle_today)) + "\n"
            + i18n.t("TOOLTIP_TOTAL", value=format_hours(total_today)) + "\n"
            + i18n.t("TOOLTIP_TARGET", value=format_hours(TARGET_WORK_SECONDS)) + "\n"
            + i18n.t("TOOLTIP_REMAINING", value=format_hours(remaining)) + "\n"
            + i18n.t(
                "TOOLTIP_WEEK",
                value=format_hours(weekly_total),
                target=format_hours(WEEKLY_TARGET_SECONDS)
            ) + "\n"
            + i18n.t("TOOLTIP_VERSION", value=get_bundle_version()) + "\n"
            + i18n.t("TOOLTIP_DATA_FOLDER", path=DATA_DIR)
        )

    # --------------------------------------------------------
    # Settings Actions
    # --------------------------------------------------------

    def select_data_folder(self, _):
        folder = choose_data_folder()

        if not folder:
            return

        self.save_delta()
        self.save_state(dirty=False)
        mark_state_clean()

        set_data_dir(folder)
        persist_data_dir(folder)

        self.save_state(dirty=True)

        self.menu_csv.title = i18n.t("MENU_CSV", path=CSV_FILE)
        self.menu_state.title = i18n.t("MENU_STATE", path=STATE_FILE)

        rumps.notification(
            "ActivityTracker",
            i18n.t("NOTIFICATION_DATA_FOLDER_CHANGED"),
            folder
        )

    def open_data_folder(self, _):
        ensure_dir(DATA_DIR)
        subprocess.run(["open", DATA_DIR])

    def reset_data_folder(self, _):
        self.save_delta()
        self.save_state(dirty=False)
        mark_state_clean()

        reset_data_dir_to_default()

        self.save_state(dirty=True)

        self.menu_csv.title = i18n.t("MENU_CSV", path=CSV_FILE)
        self.menu_state.title = i18n.t("MENU_STATE", path=STATE_FILE)

        rumps.notification(
            "ActivityTracker",
            i18n.t("NOTIFICATION_DATA_FOLDER_RESET"),
            DATA_DIR
        )

    # --------------------------------------------------------
    # Actions
    # --------------------------------------------------------

    def force_save(self, _):
        self.save_delta()
        rumps.notification(
            "ActivityTracker",
            i18n.t("NOTIFICATION_CSV_SAVED"),
            self.last_save_display
        )

    def quit_app(self, _):
        self.dashboard_refresh_event.set()

        self.save_delta()
        self.save_state(dirty=False)
        mark_state_clean()
        rumps.quit_application()


# ------------------------------------------------------------
# START
# ------------------------------------------------------------

if __name__ == "__main__":
    ActivityTrackerApp().run()
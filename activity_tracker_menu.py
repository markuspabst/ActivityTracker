
from PIL import Image, ImageDraw
import os, sys, json, csv, subprocess, plistlib, functools, threading, time
from pathlib import Path
import platformdirs
from datetime import datetime, timedelta
from pystray import Icon, Menu, MenuItem
import i18n

try:
    from version_generated import APP_FULL_VERSION, APP_BUILD_DATE
except Exception:
    APP_FULL_VERSION = "dev"
    APP_BUILD_DATE = "dev"


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

APP_NAME = "ActivityTracker"

UPDATE_INTERVAL = 5         # UI + state update every 5 seconds
WRITE_INTERVAL = 3600       # CSV auto-save every 60 minutes

DEFAULT_TARGET_SECONDS = 8 * 3600
DEFAULT_WEEKLY_TARGET_SECONDS = 40 * 3600
DEFAULT_IDLE_THRESHOLD = 300  # idle after 5 minutes of no input

TARGET_WORK_SECONDS = DEFAULT_TARGET_SECONDS
WEEKLY_TARGET_SECONDS = DEFAULT_WEEKLY_TARGET_SECONDS
IDLE_THRESHOLD = DEFAULT_IDLE_THRESHOLD


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


# Simplified configuration
class AppConfig:
    """Lightweight configuration"""
    def __init__(self):
        self.target_seconds = DEFAULT_TARGET_SECONDS
        self.weekly_target_seconds = DEFAULT_WEEKLY_TARGET_SECONDS
        self.idle_threshold_seconds = DEFAULT_IDLE_THRESHOLD
        
    def validate(self):
        """Basic validation"""
        self.target_seconds = max(3600, min(43200, self.target_seconds))
        self.weekly_target_seconds = max(10*3600, min(168*3600, self.weekly_target_seconds))
        self.idle_threshold_seconds = max(60, min(1800, self.idle_threshold_seconds))


def _config_to_dict(cfg):
    return {
        'target_seconds': cfg.target_seconds,
        'weekly_target_seconds': cfg.weekly_target_seconds,
        'idle_threshold_seconds': cfg.idle_threshold_seconds
    }


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


# Config cache to avoid repeated disk reads
_config_cache = None

def load_config():
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
            config.target_seconds = config_data.get('target_seconds', DEFAULT_TARGET_SECONDS)
            config.weekly_target_seconds = config_data.get('weekly_target_seconds', DEFAULT_WEEKLY_TARGET_SECONDS)
            config.idle_threshold_seconds = config_data.get('idle_threshold_seconds', DEFAULT_IDLE_THRESHOLD)
            config.validate()
            _config_cache = _config_to_dict(config)
            return _config_cache
    except Exception as e:
        print(f"Warning: Invalid config, using defaults: {e}")
        _config_cache = _config_to_dict(config)
        return _config_cache


def save_config(config):
    """Save configuration with validation."""
    global _config_cache
    ensure_dir(CONFIG_DIR)
    
    try:
        # Create config object and validate
        cfg = AppConfig()
        cfg.target_seconds = config.get('target_seconds', DEFAULT_TARGET_SECONDS)
        cfg.weekly_target_seconds = config.get('weekly_target_seconds', DEFAULT_WEEKLY_TARGET_SECONDS)
        cfg.idle_threshold_seconds = config.get('idle_threshold_seconds', DEFAULT_IDLE_THRESHOLD)
        cfg.validate()
        
        _config_cache = _config_to_dict(cfg)
        
        with open(CONFIG_FILE, "w") as f:
            json.dump(_config_cache, f, indent=2)
    except Exception as e:
        print(f"Warning: Invalid config values: {e}")
        # Save defaults if validation fails
        cfg = AppConfig()
        _config_cache = _config_to_dict(cfg)
        with open(CONFIG_FILE, "w") as f:
            json.dump(_config_cache, f, indent=2)


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


# ------------------------------------------------------------
# Config wrappers
# ------------------------------------------------------------
def load_target(): return int(get_config_value("target_seconds", DEFAULT_TARGET_SECONDS))
def persist_target(s): set_config_value("target_seconds", int(s))
def load_weekly_target(): return int(get_config_value("weekly_target_seconds", DEFAULT_WEEKLY_TARGET_SECONDS))
def persist_weekly_target(s): set_config_value("weekly_target_seconds", int(s))
def load_idle_threshold(): return int(get_config_value("idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD))
def persist_idle_threshold(s): set_config_value("idle_threshold_seconds", int(s))


# Initial settings
set_data_dir(get_configured_data_dir())
TARGET_WORK_SECONDS = load_target()
WEEKLY_TARGET_SECONDS = load_weekly_target()
IDLE_THRESHOLD = load_idle_threshold()


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


# Version/build date are immutable for the process lifetime; cache them so the
# per-tick tooltip doesn't re-read and parse the bundle Info.plist from disk.
@functools.lru_cache(maxsize=1)
def get_bundle_version():
    plist = get_bundle_info_plist()

    if plist:
        version = plist.get("CFBundleShortVersionString", "unknown")
        build = plist.get("CFBundleVersion", "")

        if build:
            return f"{version} ({build})"

        return version

    return APP_FULL_VERSION


@functools.lru_cache(maxsize=1)
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
    exec_dir = Path(app_path) / "Contents" / "MacOS"
    if not exec_dir.exists():
        return None
    executables = [str(f) for f in exec_dir.iterdir() if f.is_file() and os.access(f, os.X_OK)]
    return executables[0] if executables else None


def write_launch_agent_plist():
    app_executable = get_app_executable_path()
    if not app_executable:
        raise RuntimeError("Autostart requires packaged ActivityTracker.app. Build with py2app first.")
    ensure_dir(LAUNCH_AGENT_DIR); ensure_dir(LOG_DIR)
    plist = {"Label": LAUNCH_AGENT_LABEL, "ProgramArguments": [app_executable], "RunAtLoad": True,
             "KeepAlive": False, "LimitLoadToSessionType": "Aqua",
             "StandardOutPath": LAUNCH_AGENT_OUT, "StandardErrorPath": LAUNCH_AGENT_ERR,
             "WorkingDirectory": str(Path(app_executable).parent)}
    with open(LAUNCH_AGENT_FILE, "wb") as f:
        plistlib.dump(plist, f)


def _retry_launchctl(cmd):
    write_launch_agent_plist()
    _retry_launchctl(["launchctl", "bootout", launchctl_domain(), LAUNCH_AGENT_FILE])
    _retry_launchctl(["launchctl", "bootstrap", launchctl_domain(), LAUNCH_AGENT_FILE])
    _retry_launchctl(["launchctl", "enable", f"{launchctl_domain()}/{LAUNCH_AGENT_LABEL}"])

def uninstall_autostart():
    _retry_launchctl(["launchctl", "bootout", launchctl_domain(), LAUNCH_AGENT_FILE])
    if os.path.isfile(LAUNCH_AGENT_FILE):
        os.remove(LAUNCH_AGENT_FILE)


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


def bring_app_to_front():
    """Focus the app for dialog input."""
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


def ask_target_with_slider_osascript(current_value, title="", min_value=0, max_value=100):
    """Display an OS dialog and return the entered value as float, or None."""
    bring_app_to_front()
    proc = subprocess.run(
        ["osascript", "-e", f'''tell application "System Events" to set response to display dialog "{title}" default answer "{current_value:.1f}" buttons {{"Cancel", "OK"}} default button "OK"'''],
        capture_output=True, text=True, check=False
    )
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            return max(min(float(proc.stdout.strip()), max_value), min_value)
        except ValueError:
            return None
    return None


# ------------------------------------------------------------
# Idle time cache (1 second TTL to avoid redundant Quartz calls)
# ------------------------------------------------------------
_idle_cache = {'time': 0, 'value': 0}
IDLE_CACHE_TTL = 1.0  # 1 second cache to avoid redundant Quartz calls

def get_idle_time():
    """Seconds since the last HID input event."""
    now = time.time()
    if now - _idle_cache['time'] < IDLE_CACHE_TTL:
        return _idle_cache['value']

    if sys.platform == 'darwin':
        try:
            import Quartz
            value = Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateHIDSystemState,
                Quartz.kCGAnyInputEventType
            )
        except Exception:
            try:
                output = subprocess.check_output(
                    ["ioreg", "-c", "IOHIDSystem"],
                    stderr=subprocess.DEVNULL
                ).decode()
                value = 0
                for line in output.split("\n"):
                    if "HIDIdleTime" in line:
                        value = int(line.split("=")[-1].strip()) / 1_000_000_000
                        break
            except Exception:
                value = 0
    elif sys.platform == 'win32':
        from ctypes import Structure, windll, c_uint, sizeof, byref
        class LASTINPUTINFO(Structure):
            _fields_ = [('cbSize', c_uint), ('dwTime', c_uint)]
        info = LASTINPUTINFO()
        info.cbSize = sizeof(info)
        windll.user32.GetLastInputInfo(byref(info))
        value = (windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
    elif sys.platform.startswith('linux'):
        try:
            from Xlib import X, display
            from Xlib.ext import screensaver
            d = display.Display()
            info = screensaver.Info(d, d.screen().root)
            value = info.idle / 1000.0
        except (ImportError, AttributeError):
            try:
                value = int(subprocess.check_output(['xprintidle']).decode()) / 1000.0
            except (FileNotFoundError, ValueError):
                value = 0
    else:
        value = 0

    _idle_cache.update(time=now, value=value)
    return value

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


@functools.lru_cache(maxsize=8)
def emoji_icon(emoji_char, size=64):
    """Render a colored circle icon."""
    colour = {"🔴": (255,50,50), "🟡": (255,200,30), "🟢": (50,200,50)}.get(emoji_char, (200,200,200))
    img = Image.new("RGBA", (size, size), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    m = 3
    draw.ellipse([m, m, size-m, size-m], fill=colour+(255,))
    return img

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

# CSV cache with expiration
_csv_cache = None
_csv_cache_time = 0
CSV_CACHE_TTL = 10  # seconds before re-reading CSV

def read_csv_data(force=False):
    """Read the daily CSV into a ``dict[date_str -> row_dict]`` via stdlib csv."""
    global _csv_cache, _csv_cache_time
    
    if not force and _csv_cache is not None and (time.time() - _csv_cache_time) < CSV_CACHE_TTL:
        return _csv_cache

    _csv_cache = {}
    if not os.path.isfile(CSV_FILE):
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


def write_csv_data(data):
    """Write the ``dict[date_str -> row_dict]`` back to CSV, sorted by date."""
    ensure_dir(DATA_DIR)

    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for date_key in sorted(data.keys()):
            writer.writerow(data[date_key])


def get_day_from_csv(date_str, data=None):
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


def add_delta_to_csv(app, date_str, start_time, end_time, delta_total, delta_active, delta_idle, first_activity_this_day=None):
    if delta_total <= 0:
        return

    data = read_csv_data()
    existing = get_day_from_csv(date_str, data)

    existing_total = existing["total_seconds"]
    existing_active = existing["active_seconds"]
    existing_idle = existing["idle_seconds"]

    # The start_time arg is the beginning of the *session*.
    # The actual start of work for *this day* might be later, particularly
    # if the session spanned midnight. Get the first-activity time from the app instance.
    first_activity_time = app.first_activity_this_day if app and app.first_activity_this_day else start_time

    if existing["start_time"]:
        csv_start_time = existing["start_time"]
    else:
        csv_start_time = first_activity_time.strftime("%H:%M:%S")

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


def get_weekly_seconds_from_csv(data=None):
    if data is None:
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
                None, # app instance
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
    """Locate generate_dashboard.py in the source tree or py2app bundle."""
    local_path = Path(__file__).resolve().parent / "scripts" / "generate_dashboard.py"
    if local_path.exists():
        return local_path
    app_path = get_app_bundle_path()
    if app_path:
        bundle_path = Path(app_path) / "Contents" / "Resources" / "scripts" / "generate_dashboard.py"
        if bundle_path.exists():
            return bundle_path
    return local_path


def dashboard_python_command():
    """Return (executable, env) for running the dashboard script as a subprocess."""
    app_path = get_app_bundle_path()
    if app_path:
        bundled_python = Path(app_path) / "Contents" / "MacOS" / "python"
        resources = Path(app_path) / "Contents" / "Resources"
        lib_dir = resources / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
        if bundled_python.exists() and lib_dir.exists():
            env = os.environ.copy()
            env["PYTHONHOME"] = str(resources)
            env["PYTHONPATH"] = os.pathsep.join([str(lib_dir), str(lib_dir / "lib-dynload")])
            return str(bundled_python), env
    return sys.executable, None


# ------------------------------------------------------------
# Locale display names
# ------------------------------------------------------------

# Fallback names for locale codes; the native macOS API is preferred when
# available so new locale files get a sensible autonym for free.
_LOCALE_FALLBACK_NAMES = {
    "en": "English",
    "de": "Deutsch",
}


def locale_display_name(code):
    """Human-readable, self-localized name for a locale code (e.g. 'Deutsch')."""
    try:
        from Foundation import NSLocale, NSLocaleIdentifier
        loc = NSLocale.alloc().initWithLocaleIdentifier_(code)
        name = loc.displayNameForKey_value_(NSLocaleIdentifier, code)
        if name:
            return name[:1].upper() + name[1:]
    except Exception:
        pass

    return _LOCALE_FALLBACK_NAMES.get(code, code.upper())


# ------------------------------------------------------------
# Menubar App
# ------------------------------------------------------------
class ActivityTrackerTrayApp:

    def __init__(self):
        # initialize translations
        cfg = load_config()
        i18n.set_locale(cfg.get("locale"))

        self.recovery_result = recover_previous_session_if_needed()

        # Runtime session state
        self.start_time = datetime.now()
        self.last_tick_date = self.start_time.date()
        self.first_activity_this_day = None
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
        self._active_alert = None
        self.timer = None
        self.icon = None
        self._last_status_icon = None

    def update(self):
        now, total_session, active_session, idle_session, is_idle = self.calculate_current_session()

        if now.date() > self.last_tick_date:
            self.first_activity_this_day = None

        if self.first_activity_this_day is None and not is_idle:
            self.first_activity_this_day = now

        self.last_tick_date = now.date()

        if time.time() - self.last_write_time >= WRITE_INTERVAL:
            self._do_save_delta(now, total_session, active_session, idle_session)

        csv_data = read_csv_data()
        report = self._build_report(now, total_session, active_session, idle_session, csv_data)
        active_today = report["active_seconds"]

        status_emoji = get_status_icon(is_idle, active_today)
        if status_emoji != self._last_status_icon:
            self.icon.icon = emoji_icon(status_emoji)
            self._last_status_icon = status_emoji

        self.icon.title = f"{format_hours(active_today)}"
        self.icon.update_menu()

        status_emoji = get_status_icon(is_idle, active_today)
        if status_emoji != self._last_status_icon:
            self.icon.icon = emoji_icon(status_emoji)
            self._last_status_icon = status_emoji

        self.icon.title = f"{format_hours(active_today)}"
        self.icon.update_menu()

    def run(self):
        initial_icon = emoji_icon("🟢")
        self.icon = Icon("ActivityTracker", initial_icon, "ActivityTracker", Menu(self.generate_menu))
        self._running = True
        self._updater = threading.Thread(target=self._update_loop, daemon=True)
        self._updater.start()
        self.icon.run()

    def _update_loop(self):
        while self._running:
            time.sleep(UPDATE_INTERVAL)
            if self._running:
                self.update()

    def quit_app(self):
        self._running = False
        self.dashboard_refresh_event.set()
        now, total, active, idle, _ = self.calculate_current_session()
        self._do_save_delta(now, total, active, idle)
        self._write_state(now, total, active, idle, dirty=False)
        mark_state_clean()
        self.icon.stop()
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

    def _build_report(self, now, total_session, active_session, idle_session, csv_data=None):
        date_str = now.date().isoformat()
        csv_day = get_day_from_csv(date_str, csv_data)
        delta_total, delta_active, delta_idle = self.calculate_unsaved_delta(
            total_session, active_session, idle_session
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
            "last_updated": csv_day["last_updated"]
        }

    def _do_save_delta(self, now, total_session, active_session, idle_session):
        delta_total, delta_active, delta_idle = self.calculate_unsaved_delta(
            total_session, active_session, idle_session
        )
        if delta_total <= 0:
            return
        add_delta_to_csv(self, now.date().isoformat(), self.start_time, now,
                         delta_total, delta_active, delta_idle)
        self.saved_total_session = total_session
        self.saved_active_session = active_session
        self.saved_idle_session = idle_session
        self.last_write_time = time.time()
        self.last_save_display = now.strftime("%H:%M:%S")
        self._write_state(now, total_session, active_session, idle_session, dirty=True)

    def save_delta(self, app, first_activity_this_day=None):
        now, total_session, active_session, idle_session, _ = self.calculate_current_session()
        self._do_save_delta(now, total_session, active_session, idle_session)

    def _write_state(self, now, total_session, active_session, idle_session, dirty=True):
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
            "data_dir": DATA_DIR, "csv_file": CSV_FILE, "state_file": STATE_FILE
        }
        write_state(state)

    def save_state(self, dirty=True):
        now, total_session, active_session, idle_session, is_idle = self.calculate_current_session()
        self._write_state(now, total_session, active_session, idle_session, dirty)

    # --------------------------------------------------------
    # Target settings
    # --------------------------------------------------------
    def _slider(self, title_key, current, factor, min_v, max_v):
        value = ask_target_with_slider_osascript(current, title=i18n.t(title_key), min_value=min_v, max_value=max_v)
        return int(value * factor) if value is not None and value > 0 else None

    def set_target(self, seconds):
        global TARGET_WORK_SECONDS
        TARGET_WORK_SECONDS = int(seconds)
        persist_target(seconds)

    def set_target_slider(self, _):
        v = self._slider("ASK_DAILY_TARGET_TITLE", TARGET_WORK_SECONDS / 3600, 3600, 4.0, 12.0)
        if v: self.set_target(v)

    def set_weekly_target(self, seconds):
        global WEEKLY_TARGET_SECONDS
        WEEKLY_TARGET_SECONDS = int(seconds)
        persist_weekly_target(seconds)

    def set_weekly_slider(self, _):
        v = self._slider("ASK_WEEKLY_TARGET_TITLE", WEEKLY_TARGET_SECONDS / 3600, 3600, 20.0, 60.0)
        if v: self.set_weekly_target(v)

    def set_idle_threshold(self, seconds):
        global IDLE_THRESHOLD
        IDLE_THRESHOLD = int(seconds)
        persist_idle_threshold(seconds)

    def set_idle_slider(self, _):
        v = self._slider("ASK_IDLE_THRESHOLD_TITLE", IDLE_THRESHOLD / 60, 60, 1, 30)
        if v: self.set_idle_threshold(v)

    # --------------------------------------------------------
    # Autostart
    # --------------------------------------------------------

    def toggle_autostart(self, _):
        try:
            if is_autostart_installed():
                uninstall_autostart()
            else:
                self.save_delta()
                self.save_state(dirty=True)
                install_autostart()

        except Exception as e:
            print(f"Autostart error: {e}")

    def open_autostart_file(self, _):
        ensure_dir(LAUNCH_AGENT_DIR)

        if os.path.isfile(LAUNCH_AGENT_FILE):
            subprocess.run(["open", "-R", LAUNCH_AGENT_FILE])
        else:
            subprocess.run(["open", LAUNCH_AGENT_DIR])

    # --------------------------------------------------------
    # Version
    # Language
    # --------------------------------------------------------

    def make_language_callback(self, code):
        def callback(_):
            self.set_language(code)
        return callback

    def set_language(self, code):
        set_config_value("locale", code)
        i18n.set_locale(code)

    # --------------------------------------------------------
    # Dashboard
    # --------------------------------------------------------

    def open_enterprise_dashboard(self, _):
        script_path = find_dashboard_script()

        if not script_path.exists():
            print(f"Dashboard script not found at {script_path}")
            return

        python_exe, env = dashboard_python_command()
        subprocess.Popen([python_exe, str(script_path)], env=env)

        if self.dashboard_thread is None or not self.dashboard_thread.is_alive():
            self.dashboard_refresh_event.clear()
            self.dashboard_thread = threading.Thread(
                target=self._dashboard_refresh_loop,
                args=(script_path,),
                daemon=True
            )
            self.dashboard_thread.start()

    def _dashboard_refresh_loop(self, script_path):
        python_exe, env = dashboard_python_command()
        while not self.dashboard_refresh_event.is_set():
            time.sleep(10)
            subprocess.run([python_exe, str(script_path), "--data-only"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

    # --------------------------------------------------------
    # UI Update
    # --------------------------------------------------------

    def select_data_folder(self, _):
        folder = self.choose_data_folder()

        if not folder:
            return

        self.save_delta(self)
        self.save_state(dirty=False)
        mark_state_clean()

        set_data_dir(folder)
        persist_data_dir(folder)

        self.save_state(dirty=True)

    def open_data_folder(self, _):
        ensure_dir(DATA_DIR)
        subprocess.run(["open", DATA_DIR])

    def reset_data_folder(self, _):
        self.save_delta(self)
        self.save_state(dirty=False)
        mark_state_clean()

        reset_data_dir_to_default()

        self.save_state(dirty=True)

    def choose_data_folder(self):
        """Native macOS folder selection dialog."""
        bring_app_to_front()
        try:
            r = subprocess.run(["osascript", "-e", 'set f to choose folder with prompt "Select a folder for CSV and state data:"\nreturn POSIX path of f'],
                              capture_output=True, text=True, check=False)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception as e:
            print(f"Error opening folder choice dialog: {e}")
            return None


    # --------------------------------------------------------
    # Actions
    # --------------------------------------------------------

    def force_save(self, _):
        self.save_delta(self)
    def generate_menu(self):
        now, total_session, active_session, idle_session, is_idle = self.calculate_current_session()
        csv_data = read_csv_data()
        report = self._build_report(now, total_session, active_session, idle_session, csv_data)
        active_today = report["active_seconds"]
        idle_today = report["idle_seconds"]
        total_today = report["total_seconds"]
        daily_overtime = active_today - TARGET_WORK_SECONDS

        weekly_from_csv = get_weekly_seconds_from_csv(data=csv_data)
        _, delta_active, _ = self.calculate_unsaved_delta(
            total_session,
            active_session,
            idle_session
        )

        weekly_total = weekly_from_csv + delta_active
        weekly_overtime = weekly_total - WEEKLY_TARGET_SECONDS

        settings_items = []
        if sys.platform == 'darwin':
            settings_items.extend([
                MenuItem(i18n.t("SELECT_DATA_FOLDER"), self.select_data_folder),
                MenuItem(i18n.t("OPEN_DATA_FOLDER"), self.open_data_folder),
                MenuItem(i18n.t("RESET_DATA_FOLDER"), self.reset_data_folder),
                Menu.SEPARATOR,
            ])

        target_menu_items = []
        for h in range(4, 13):
            target_menu_items.append(
                MenuItem(
                    f'{h}h',
                    lambda _, h=h: self.set_target(h * 3600),
                    checked=lambda item, h=h: TARGET_WORK_SECONDS == h * 3600
                )
            )
        target_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(
                i18n.t("SET_CUSTOM_VALUE"),
                self.set_target_slider,
                enabled=sys.platform == 'darwin'
            )
        ])
        target_menu = Menu(*target_menu_items)

        weekly_target_menu_items = []
        for h in range(20, 61, 5):
            weekly_target_menu_items.append(
                MenuItem(
                    f'{h}h',
                    lambda _, h=h: self.set_weekly_target(h * 3600),
                    checked=lambda item, h=h: WEEKLY_TARGET_SECONDS == h * 3600
                )
            )
        weekly_target_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(
                i18n.t("SET_CUSTOM_VALUE"),
                self.set_weekly_slider,
                enabled=sys.platform == 'darwin'
            )
        ])
        weekly_target_menu = Menu(*weekly_target_menu_items)

        idle_menu_items = []
        for m in [1, 2, 3, 5, 10, 15, 20, 30]:
            idle_menu_items.append(
                MenuItem(
                    f'{m} min',
                    lambda _, m=m: self.set_idle_threshold(m * 60),
                    checked=lambda item, m=m: IDLE_THRESHOLD == m * 60
                )
            )
        idle_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(
                i18n.t("SET_CUSTOM_VALUE"),
                self.set_idle_slider,
                enabled=sys.platform == 'darwin'
            )
        ])
        idle_menu = Menu(*idle_menu_items)


        language_menu_items = []
        system_item = MenuItem(
            i18n.t("LANGUAGE_SYSTEM_DEFAULT"),
            self.make_language_callback(None),
            checked=lambda item: get_config_value("locale") is None
        )
        language_menu_items.append(system_item)
        language_menu_items.append(Menu.SEPARATOR)

        for code in sorted(i18n.available_locales()):
            item = MenuItem(
                locale_display_name(code),
                self.make_language_callback(code),
                checked=lambda item, c=code: get_config_value("locale") == c
            )
            language_menu_items.append(item)

        language_menu = Menu(*language_menu_items)


        settings_items.extend([
            MenuItem(i18n.t("DAILY_TARGET"), target_menu),
            MenuItem(i18n.t("WEEKLY_TARGET"), weekly_target_menu),
            MenuItem(i18n.t("IDLE_THRESHOLD"), idle_menu),
            Menu.SEPARATOR,
            MenuItem(i18n.t("LANGUAGE"), language_menu),
            Menu.SEPARATOR,
            MenuItem(i18n.t("AUTOSTART_DISABLED"), self.toggle_autostart, checked=lambda item: is_autostart_installed()),
            MenuItem(i18n.t("OPEN_AUTOSTART_FILE"), self.open_autostart_file),
            Menu.SEPARATOR,
            MenuItem(i18n.t("VERSION", value=get_bundle_version()), None, enabled=False),
            MenuItem(i18n.t("BUILD", value=get_bundle_build_date()), None, enabled=False),

        ])


        return (
            MenuItem(i18n.t("MENU_ACTIVE", value=format_hours(active_today)), None, enabled=False),
            MenuItem(i18n.t("MENU_IDLE", value=format_hours(idle_today)), None, enabled=False),
            MenuItem(i18n.t("MENU_TOTAL", value=format_hours(total_today)), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(i18n.t("MENU_TODAY_TARGET", value=format_hours(TARGET_WORK_SECONDS)), None, enabled=False),
            MenuItem(i18n.t("TODAY_OVERTIME_POS" if daily_overtime >= 0 else "TODAY_OVERTIME_NEG", value=format_delta(daily_overtime)), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(i18n.t("WEEK_TOTAL", value=format_hours(weekly_total), target=format_hours(WEEKLY_TARGET_SECONDS)), None, enabled=False),
            MenuItem(i18n.t("WEEK_OVERTIME_POS" if weekly_overtime >= 0 else "WEEK_OVERTIME_NEG", value=format_delta(weekly_overtime)), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(i18n.t("MENU_START", value=self.first_activity_this_day.strftime('%H:%M:%S') if self.first_activity_this_day else 'N/A'), None, enabled=False),
            MenuItem(i18n.t("MENU_UPDATE", value=now.strftime('%H:%M:%S')), None, enabled=False),
            MenuItem(i18n.t("MENU_SAVED", value=self.last_save_display), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(i18n.t("MENU_CSV", path=CSV_FILE or "-"), self.open_data_folder),
            MenuItem(i18n.t("MENU_STATE", path=STATE_FILE or "-"), self.open_data_folder),
            Menu.SEPARATOR,
            MenuItem(i18n.t("SETTINGS"), Menu(*settings_items)),
            Menu.SEPARATOR,
            MenuItem(i18n.t("FORCE_SAVE"), self.force_save),
            MenuItem(i18n.t("QUIT"), self.quit_app),
        )
# ------------------------------------------------------------
# START
# ------------------------------------------------------------

if __name__ == "__main__":
    app = ActivityTrackerTrayApp()
    app.run()

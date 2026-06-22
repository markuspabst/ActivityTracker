
from PIL import Image, ImageDraw
import os, sys, json, subprocess, functools, threading, time
from pathlib import Path
from datetime import datetime, timedelta
from pystray import Icon, Menu, MenuItem

from tracking import (
    APP_NAME,
    TARGET_WORK_SECONDS,
    WEEKLY_TARGET_SECONDS,
    IDLE_THRESHOLD,
    DEFAULT_BASE_DIR,
    DATA_DIR,
    CSV_FILE,
    STATE_FILE,
    load_config,
    save_config,
    get_config_value,
    set_config_value,
    get_configured_data_dir,
    set_data_dir,
    persist_data_dir,
    reset_data_dir_to_default,
    load_target,
    persist_target,
    load_weekly_target,
    persist_weekly_target,
    load_idle_threshold,
    persist_idle_threshold,
    ensure_dir,
    format_hours,
    format_hours_decimal,
    format_delta,
    format_delta_decimal,
    hours,
    parse_datetime,
    get_status_icon,
    read_csv_data,
    write_csv_data,
    get_day_from_csv,
    add_delta_to_csv,
    get_current_week_dates,
    get_weekly_seconds_from_csv,
    read_state,
    write_state,
    mark_state_clean,
    recover_previous_session_if_needed,
    SessionTracker,
    DEFAULT_TARGET_SECONDS,
    DEFAULT_WEEKLY_TARGET_SECONDS,
    DEFAULT_IDLE_THRESHOLD,
)
from platform_layer import get_platform, detect_platform
import i18n

try:
    from version_generated import APP_FULL_VERSION, APP_BUILD_DATE
except Exception:
    APP_FULL_VERSION = "dev"
    APP_BUILD_DATE = "dev"


# Initialise tracking paths and settings
set_data_dir(get_configured_data_dir())

# Load persisted target values into the globals used by the menu
TARGET_WORK_SECONDS = load_target()
WEEKLY_TARGET_SECONDS = load_weekly_target()
IDLE_THRESHOLD = load_idle_threshold()


# ------------------------------------------------------------
# Version Handling (delegated to platform layer)
# ------------------------------------------------------------
plat = get_platform()

# UI update / save intervals (seconds)
WRITE_INTERVAL = 3600
UPDATE_INTERVAL = 5

def get_bundle_version():
    return plat.get_bundle_version(fallback=APP_FULL_VERSION)

def get_bundle_build_date():
    return plat.get_bundle_build_date(fallback=APP_BUILD_DATE)


# ------------------------------------------------------------
# Autostart (delegated to platform layer)
# ------------------------------------------------------------

def install_autostart():
    plat.install_autostart()

def uninstall_autostart():
    plat.uninstall_autostart()

def is_autostart_installed():
    return plat.autostart_installed()

def is_autostart_loaded():
    return plat.autostart_loaded()


# ------------------------------------------------------------
# Native Dialogs (delegated to platform layer)
# ------------------------------------------------------------

def bring_app_to_front():
    plat.bring_app_to_front()

def ask_target_with_slider_osascript(current_value, title="", min_value=0, max_value=100):
    return plat.ask_slider_dialog(title, current_value, min_value, max_value)


# ------------------------------------------------------------
# Idle time (delegated to platform layer)
# ------------------------------------------------------------

def get_idle_time():
    return plat.get_idle_time()


# ------------------------------------------------------------
# Emoji tray icon rendering
# ------------------------------------------------------------

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
# Dashboard script path (delegated to platform layer)
# ------------------------------------------------------------

def find_dashboard_script():
    return plat.find_dashboard_script()


def dashboard_python_command():
    return plat.get_dashboard_python_cmd()


# ------------------------------------------------------------
# Locale display names
# ------------------------------------------------------------

# Fallback names for locale codes; the platform layer can provide a native
# name (macOS uses NSLocale), otherwise we use these fallbacks.
_LOCALE_FALLBACK_NAMES = {
    "en": "English",
    "de": "Deutsch",
}


def locale_display_name(code):
    """Human-readable, self-localized name for a locale code (e.g. 'Deutsch')."""
    name = plat.locale_display_name(code)
    if name:
        return name
    return _LOCALE_FALLBACK_NAMES.get(code, code.upper())


# ------------------------------------------------------------
# Menubar App
# ------------------------------------------------------------
class ActivityTrackerTrayApp:

    def __init__(self):
        # initialize translations
        cfg = load_config()
        i18n.set_locale(cfg.get("locale"))

        self.session = SessionTracker()
        self.recovery_result = recover_previous_session_if_needed()

        self.last_write_time = time.time()
        self.last_save_display = i18n.t("LAST_SAVE_NONE")
        self.dashboard_refresh_event = threading.Event()
        self.dashboard_thread = None
        self._active_alert = None
        self.timer = None
        self.icon = None
        self._last_status_icon = None

    def update(self):
        now, total_session, active_session, idle_session, is_idle = (
            self.session.calculate_current_session(IDLE_THRESHOLD, get_idle_time)
        )
        self.session.on_tick(is_idle)

        if time.time() - self.last_write_time >= WRITE_INTERVAL:
            self._do_save_delta(now, total_session, active_session, idle_session)

        csv_data = read_csv_data()
        report = self.session.build_report(now, total_session, active_session, idle_session, csv_data)
        active_today = report["active_seconds"]

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
        now, total, active, idle, _ = self.session.calculate_current_session(IDLE_THRESHOLD, get_idle_time)
        self._do_save_delta(now, total, active, idle)
        self.session.write_state(now, total, active, idle, dirty=False)
        mark_state_clean()
        self.icon.stop()

    # --------------------------------------------------------
    # Runtime Calculations -> delegated to SessionTracker
    # --------------------------------------------------------

    def calculate_current_session(self):
        return self.session.calculate_current_session(IDLE_THRESHOLD, get_idle_time)

    def _do_save_delta(self, now, total_session, active_session, idle_session):
        delta_total, delta_active, delta_idle = self.session.calculate_unsaved_delta(
            total_session, active_session, idle_session
        )
        if delta_total <= 0:
            return
        add_delta_to_csv(
            self.session.first_activity_this_day,
            now.date().isoformat(),
            self.session.start_time,
            now,
            delta_total, delta_active, delta_idle,
        )
        self.session.mark_saved(total_session, active_session, idle_session)
        self.last_write_time = time.time()
        self.last_save_display = now.strftime("%H:%M:%S")
        self.session.write_state(now, total_session, active_session, idle_session, dirty=True)

    def save_delta(self):
        now, total_session, active_session, idle_session, _ = self.calculate_current_session()
        self._do_save_delta(now, total_session, active_session, idle_session)

    def save_state(self, dirty=True):
        now, total_session, active_session, idle_session, _ = self.calculate_current_session()
        self.session.write_state(now, total_session, active_session, idle_session, dirty)

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
        info = plat.get_autostart_config_path()
        if info:
            config_dir, config_file = info
            if config_file and os.path.isfile(config_file):
                plat.reveal_file_in_manager(config_file)
            elif config_dir:
                os.makedirs(config_dir, exist_ok=True)
                plat.open_file_manager(config_dir)

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

        self.save_delta()
        self.save_state(dirty=False)
        mark_state_clean()

        set_data_dir(folder)
        persist_data_dir(folder)

        # Reset session so it picks up the new location's state
        self.session.reset()
        self.save_state(dirty=True)

    def open_data_folder(self, _):
        path = get_configured_data_dir()
        ensure_dir(path)
        plat.open_file_manager(path)

    def reset_data_folder(self, _):
        self.save_delta()
        self.save_state(dirty=False)
        mark_state_clean()

        reset_data_dir_to_default()

        # Reset session so it picks up the default location's state
        self.session.reset()
        self.save_state(dirty=True)

    def choose_data_folder(self):
        """Native folder selection dialog (delegated to platform layer)."""
        return plat.choose_folder_dialog(prompt="Select a folder for CSV and state data:")


    # --------------------------------------------------------
    # Actions
    # --------------------------------------------------------

    def force_save(self, _):
        self.save_delta()
    def generate_menu(self):
        now, total_session, active_session, idle_session, is_idle = self.calculate_current_session()
        csv_data = read_csv_data()
        report = self.session.build_report(now, total_session, active_session, idle_session, csv_data)
        active_today = report["active_seconds"]
        idle_today = report["idle_seconds"]
        total_today = report["total_seconds"]
        daily_overtime = active_today - TARGET_WORK_SECONDS

        weekly_from_csv = get_weekly_seconds_from_csv(data=csv_data)
        _, delta_active, _ = self.session.calculate_unsaved_delta(
            total_session,
            active_session,
            idle_session
        )

        weekly_total = weekly_from_csv + delta_active
        weekly_overtime = weekly_total - WEEKLY_TARGET_SECONDS

        settings_items = []

        target_menu_items = []
        for h in range(4, 13):
            target_menu_items.append(
                MenuItem(
                    f'{h}h',
                    (lambda h_val: lambda *args: self.set_target(h_val * 3600))(h),
                    checked=(lambda h_val: lambda *args: TARGET_WORK_SECONDS == h_val * 3600)(h)
                )
            )
        target_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(
                i18n.t("SET_CUSTOM_VALUE"),
                self.set_target_slider,
                enabled=plat.supports_native_dialogs()
            )
        ])
        target_menu = Menu(*target_menu_items)

        weekly_target_menu_items = []
        for h in range(20, 61, 5):
            weekly_target_menu_items.append(
                MenuItem(
                    f'{h}h',
                    (lambda h_val: lambda *args: self.set_weekly_target(h_val * 3600))(h),
                    checked=(lambda h_val: lambda *args: WEEKLY_TARGET_SECONDS == h_val * 3600)(h)
                )
            )
        weekly_target_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(
                i18n.t("SET_CUSTOM_VALUE"),
                self.set_weekly_slider,
                enabled=plat.supports_native_dialogs()
            )
        ])
        weekly_target_menu = Menu(*weekly_target_menu_items)

        idle_menu_items = []
        for m in [1, 2, 3, 5, 10, 15, 20, 30]:
            idle_menu_items.append(
                MenuItem(
                    f'{m} min',
                    (lambda m_val: lambda *args: self.set_idle_threshold(m_val * 60))(m),
                    checked=(lambda m_val: lambda *args: IDLE_THRESHOLD == m_val * 60)(m)
                )
            )
        idle_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(
                i18n.t("SET_CUSTOM_VALUE"),
                self.set_idle_slider,
                enabled=plat.supports_native_dialogs()
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


        data_folder_menu = Menu(
            MenuItem(
                get_configured_data_dir(),
                None,
                enabled=False
            ),
            Menu.SEPARATOR,
            MenuItem(i18n.t("OPEN_DATA_FOLDER"), self.open_data_folder),
            MenuItem(i18n.t("SELECT_DATA_FOLDER"), self.select_data_folder, enabled=plat.supports_native_dialogs()),
            MenuItem(i18n.t("RESET_DATA_FOLDER"), self.reset_data_folder),
        )

        settings_items.extend([
            MenuItem(i18n.t("DAILY_TARGET"), target_menu),
            MenuItem(i18n.t("WEEKLY_TARGET"), weekly_target_menu),
            MenuItem(i18n.t("IDLE_THRESHOLD"), idle_menu),
            Menu.SEPARATOR,
            MenuItem(i18n.t("DATA_FOLDER"), data_folder_menu),
            Menu.SEPARATOR,
            MenuItem(i18n.t("LANGUAGE"), language_menu),
            Menu.SEPARATOR,
            MenuItem(i18n.t("AUTOSTART_ENABLED" if is_autostart_installed() else "AUTOSTART_DISABLED"), self.toggle_autostart, checked=lambda item: is_autostart_installed()),
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
            MenuItem(i18n.t("MENU_START", value=self.session.first_activity_this_day.strftime('%H:%M:%S') if self.session.first_activity_this_day else 'N/A'), None, enabled=False),
            MenuItem(i18n.t("MENU_UPDATE", value=now.strftime('%H:%M:%S')), None, enabled=False),
            MenuItem(i18n.t("MENU_SAVED", value=self.last_save_display), None, enabled=False),
            Menu.SEPARATOR,
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

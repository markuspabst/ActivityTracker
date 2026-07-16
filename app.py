from __future__ import annotations
import threading
import time
from datetime import datetime, timedelta
import sys

import i18n
from platform_layer import get_platform
from tracking import (
    SessionTracker,
    get_config_value,
    load_config,
    set_config_value,
    set_data_dir,
    persist_data_dir,
    reset_data_dir_to_default,
    get_configured_data_dir,
)
from persistence import PersistenceManager
from activity_tracker_menu import AppMenu
from single_instance import SingleInstanceLock

class ActivityTrackerApp:
    def __init__(self):
        cfg = load_config()
        i18n.set_locale(cfg.get("locale"))

        self.platform = get_platform()
        self.pm = PersistenceManager(get_configured_data_dir)
        self.session = SessionTracker(self.pm)
        self.session.recover_from_crash()
        self.session.load_current_day_segments()

        self.target_work_seconds = int(get_config_value("target_seconds", 8 * 3600))
        self.weekly_target_seconds = int(get_config_value("weekly_target_seconds", 40 * 3600))
        self.idle_threshold = int(get_config_value("idle_threshold_seconds", 300))
        self.write_interval = int(get_config_value("save_interval_seconds", 3600))

        self.last_write_time = time.time()
        self._running = False

    def run(self):
        self._running = True
        self.menu = AppMenu(self)
        self._updater = threading.Thread(target=self._update_loop, daemon=True)
        self._updater.start()
        self.update()
        self.menu.run()

    def _update_loop(self):
        while self._running:
            time.sleep(5)
            if self._running:
                is_locked = self.platform.is_screen_locked()
                if self.session.is_locked != is_locked:
                    self.session.set_locked(is_locked)

                if not is_locked:
                    self.update()

    def update(self):
        idle_time = self.platform.get_idle_time()
        self.session.on_tick(idle_time, self.idle_threshold)

        if time.time() - self.last_write_time >= self.write_interval:
            self.session.save_all_days()
            self.last_write_time = time.time()

        self.update_ui()

    def update_ui(self):
        today = datetime.now().date()
        current_day_data = self.session.days.get(today)
        active_today = current_day_data.total_active_seconds() if current_day_data else 0
        is_idle = self.session.current_segment.state == 'idle' if self.session.current_segment else False

        week_start_date = today - timedelta(days=today.weekday())
        # Get weekly total from CSV
        weekly_active_minutes, weekly_idle_minutes = self.pm.get_weekly_minutes_cached(week_start_date)
        weekly_idle_minutes_csv = weekly_idle_minutes

        # Include today's ongoing segment (which may not be in CSV yet)
        # The difference between in-memory total and CSV total is the ongoing time
        today_csv_active, today_csv_idle = self.pm.get_minutes_for_date(today)

        # Calculate ongoing time for both active and idle
        active_ongoing_seconds = active_today - (today_csv_active * 60)
        idle_ongoing_minutes = (current_day_data.idle_minutes if current_day_data else 0) - today_csv_idle
        idle_ongoing_seconds = idle_ongoing_minutes * 60

        # Add ongoing seconds to weekly totals
        total_weekly_active = (weekly_active_minutes * 60) + active_ongoing_seconds
        total_weekly_idle = (weekly_idle_minutes_csv * 60) + idle_ongoing_seconds

        self.menu.update_ui(is_idle, active_today, total_weekly_active, self.weekly_target_seconds, total_weekly_idle)

    def quit_app(self):
        self._running = False
        self.session.finalize_session()
        self.menu.stop()

    def force_save(self):
        self.session.save_all_days()
        self.last_write_time = time.time()

    def set_target(self, seconds):
        self.target_work_seconds = int(seconds)
        set_config_value("target_seconds", int(seconds))

    def set_weekly_target(self, seconds):
        self.weekly_target_seconds = int(seconds)
        set_config_value("weekly_target_seconds", int(seconds))

    def set_idle_threshold(self, seconds):
        self.idle_threshold = int(seconds)
        set_config_value("idle_threshold_seconds", int(seconds))

    def set_save_interval(self, seconds):
        self.write_interval = int(seconds)
        set_config_value("save_interval_seconds", int(seconds))
        # Update cache TTL to match save interval for consistent data
        from persistence import set_cache_ttl
        set_cache_ttl(float(seconds))

    def set_language(self, code):
        set_config_value("locale", code)
        i18n.set_locale(code)

    def select_data_folder(self):
        folder = self.platform.choose_folder_dialog(prompt=i18n.t("SELECT_DATA_FOLDER"))
        if not folder:
            return
        self.force_save()
        set_data_dir(folder)
        persist_data_dir(folder)

    def reset_data_folder(self):
        self.force_save()
        reset_data_dir_to_default()
""

if __name__ == "__main__":
    # 1. Acquire single-instance lock
    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        platform = get_platform()
        platform.show_alert(
            "ActivityTracker is already running.",
            "Another instance of the application is already active. Please check your menu bar."
        )
        sys.exit(1)

    # 2. Set up data directory and run the app
    set_data_dir(get_configured_data_dir())
    app = ActivityTrackerApp()
    app.run()
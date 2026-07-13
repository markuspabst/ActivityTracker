from __future__ import annotations
import threading
import time
from datetime import datetime

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

class ActivityTrackerApp:
    def __init__(self):
        cfg = load_config()
        i18n.set_locale(cfg.get("locale"))

        self.platform = get_platform()
        self.pm = PersistenceManager(get_configured_data_dir)
        self.session = SessionTracker(self.pm)
        self.session.recover_from_crash()

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

        self.session.write_state(dirty=True)
        self.update_ui()

    def update_ui(self):
        today = datetime.now().date()
        current_day_data = self.session.days.get(today)

        active_today = current_day_data.active_minutes * 60 if current_day_data else 0
        is_idle = self.session.current_segment.state == 'idle' if self.session.current_segment else False

        self.menu.update_ui(is_idle, active_today)

    def quit_app(self):
        self._running = False
        self.session.finalize_session()
        self.session.mark_state_clean()
        self.menu.stop()

    def force_save(self):
        self.session.save_all_days()
        self.last_write_time = time.time()

    # ... methods for setting config values remain the same ...

    def select_data_folder(self):
        folder = self.platform.choose_folder_dialog(prompt=i18n.t("SELECT_DATA_FOLDER"))
        if not folder:
            return
        self.force_save()
        self.session.mark_state_clean()
        set_data_dir(folder)
        persist_data_dir(folder)
        # No session reset needed, as data is now managed by date

    def reset_data_folder(self):
        self.force_save()
        self.session.mark_state_clean()
        reset_data_dir_to_default()

if __name__ == "__main__":
    set_data_dir(get_configured_data_dir())
    app = ActivityTrackerApp()
    app.run()
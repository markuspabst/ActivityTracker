
from __future__ import annotations
import threading
import time

import i18n
from platform_layer import get_platform
from tracking import (
    SessionTracker,
    add_delta_to_csv,
    get_configured_data_dir,
    get_config_value,
    load_config,
    mark_state_clean,
    persist_data_dir,
    read_csv_data,
    recover_previous_session_if_needed,
    reset_data_dir_to_default,
    set_config_value,
    set_data_dir,
)

from activity_tracker_menu import AppMenu


class ActivityTrackerApp:
    def __init__(self):
        # Load config and set up internationalization
        cfg = load_config()
        i18n.set_locale(cfg.get("locale"))

        # Initialize core components
        self.platform = get_platform()
        self.session = SessionTracker()
        self.recovery_result = recover_previous_session_if_needed()

        # Load settings
        self.target_work_seconds = int(get_config_value("target_seconds", 8 * 3600))
        self.weekly_target_seconds = int(get_config_value("weekly_target_seconds", 40 * 3600))
        self.idle_threshold = int(get_config_value("idle_threshold_seconds", 300))
        self.write_interval = int(get_config_value("save_interval_seconds", 3600))

        # State variables
        self.last_write_time = time.time()
        self.last_save_display = i18n.t("LAST_SAVE_NONE")
        self._running = False

    def run(self):
        """Starts the application, including the menu and the update loop."""
        self._running = True
        self.menu = AppMenu(self)

        # Start the background update thread
        self._updater = threading.Thread(target=self._update_loop, daemon=True)
        self._updater.start()

        # Run the menu bar app
        self.menu.run()

    def _update_loop(self):
        """Periodically calls the update method."""
        while self._running:
            time.sleep(5)  # Update interval
            if self._running:
                self.update()

    def update(self):
        """Main update logic for the application."""
        now, total, active, idle, is_idle = self.calculate_current_session()
        prev_date = self.session.on_tick(is_idle)

        # Midnight rollover — save remaining delta to the *previous* day,
        # then reset the session so the new day starts with fresh counters
        # and a correct start_time.
        if prev_date is not None:
            self._do_save_delta(now, total, active, idle, date_str=prev_date.isoformat())
            self.session.reset()
            now, total, active, idle, is_idle = self.calculate_current_session()
            self.session.write_state(now, total, active, idle, dirty=True)

        # Check if it's time to save
        if time.time() - self.last_write_time >= self.write_interval:
            self._do_save_delta(now, total, active, idle)

        # Build the report (combines CSV data + unsaved delta for today)
        csv_data = read_csv_data()
        report = self.session.build_report(now, total, active, idle, csv_data)
        active_today = report["active_seconds"]

        # Update the UI
        self.menu.update_ui(is_idle, active_today)

    def quit_app(self):
        """Shuts down the application gracefully."""
        self._running = False
        now, total, active, idle, _ = self.calculate_current_session()
        self._do_save_delta(now, total, active, idle)
        self.session.write_state(now, total, active, idle, dirty=False)
        mark_state_clean()
        self.menu.stop()

    def calculate_current_session(self):
        """Delegates session calculation to the session tracker."""
        return self.session.calculate_current_session(self.idle_threshold, self.platform.get_idle_time)

    def _do_save_delta(self, now, total_session, active_session, idle_session, date_str=None):
        """Saves the unsaved time delta to the CSV file.

        If *date_str* is provided (e.g. during midnight rollover) the delta
        is written to that day's row instead of *now*'s date.
        """
        delta_total, delta_active, delta_idle = self.session.calculate_unsaved_delta(
            total_session, active_session, idle_session
        )
        if delta_total <= 0:
            return

        csv_end_time = self.session.last_active_time or now

        add_delta_to_csv(
            self.session.first_activity_this_day,
            date_str or now.date().isoformat(),
            self.session.start_time,
            csv_end_time,
            delta_total,
            delta_active,
            delta_idle,
        )
        self.session.mark_saved(total_session, active_session, idle_session)
        self.last_write_time = time.time()
        self.last_save_display = now.strftime("%H:%M:%S")
        self.session.write_state(now, total_session, active_session, idle_session, dirty=True)

    def force_save(self):
        """Forces an immediate save of the current session delta."""
        now, total, active, idle, _ = self.calculate_current_session()
        self._do_save_delta(now, total, active, idle)

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

    def set_language(self, code):
        set_config_value("locale", code)
        i18n.set_locale(code)

    def select_data_folder(self):
        folder = self.platform.choose_folder_dialog(prompt=i18n.t("SELECT_DATA_FOLDER"))
        if not folder:
            return

        self.force_save()
        self.session.write_state(*self.calculate_current_session()[:4], dirty=False)
        mark_state_clean()

        set_data_dir(folder)
        persist_data_dir(folder)

        self.session.reset()
        self.session.write_state(*self.calculate_current_session()[:4], dirty=True)

    def reset_data_folder(self):
        self.force_save()
        self.session.write_state(*self.calculate_current_session()[:4], dirty=False)
        mark_state_clean()
        reset_data_dir_to_default()
        self.session.reset()
        self.session.write_state(*self.calculate_current_session()[:4], dirty=True)


if __name__ == "__main__":
    set_data_dir(get_configured_data_dir())
    app = ActivityTrackerApp()
    app.run()

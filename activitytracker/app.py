from __future__ import annotations
import csv
import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta
import sys
from typing import Callable

from activitytracker import i18n
from activitytracker.platform_layer import get_platform
from activitytracker.tracking import (
    SessionTracker,
    get_config_value,
    load_config,
    set_config_value,
    set_data_dir,
    reset_data_dir_to_default,
    get_configured_data_dir,
    get_state_file_path,
    DEFAULT_TARGET_SECONDS,
    DEFAULT_WEEKLY_TARGET_SECONDS,
    DEFAULT_SAVE_INTERVAL_SECONDS,
)
from activitytracker.persistence import (
    PersistenceManager,
    PersistenceWriteError,
    DEFAULT_IDLE_THRESHOLD_SECONDS,
)
from activitytracker.activity_tracker_menu import AppMenu
from activitytracker.single_instance import SingleInstanceLock

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 10
# Throttle background CSV optimization so the whole year file is not rewritten
# on every periodic save. User-initiated saves still optimize immediately.
OPTIMIZE_INTERVAL_SECONDS = 4 * 3600


class ActivityTrackerApp:
    def __init__(self):
        cfg = load_config()
        i18n.set_locale(cfg.get("locale"))

        self.platform = get_platform()
        self.pm = PersistenceManager(get_configured_data_dir, get_state_file_path)
        self.session = SessionTracker(self.pm)
        self.session.load_current_day_segments()

        self.target_work_seconds = int(
            get_config_value("target_seconds", DEFAULT_TARGET_SECONDS)
        )
        self.weekly_target_seconds = int(
            get_config_value("weekly_target_seconds", DEFAULT_WEEKLY_TARGET_SECONDS)
        )
        self.idle_threshold = int(
            get_config_value("idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD_SECONDS)
        )
        self.write_interval = int(
            get_config_value("save_interval_seconds", DEFAULT_SAVE_INTERVAL_SECONDS)
        )
        self.session.idle_threshold = self.idle_threshold

        self.last_write_time = time.time()
        self._last_optimize_time = 0.0
        self._running = False
        self._stop_event = threading.Event()
        self._save_failure_shown = False
        self._idle_detection_failure_shown = False

    def run(self):
        self._running = True
        self._stop_event.clear()
        self.menu = AppMenu(self)
        self._updater = threading.Thread(target=self._update_loop, daemon=True)
        self._updater.start()
        self.update()
        self.menu.run()

    def _update_loop(self):
        while self._running:
            if self._stop_event.wait(POLL_INTERVAL_SECONDS):
                break
            is_locked = self.platform.is_screen_locked()
            if self.session.is_locked != is_locked:
                self.session.set_locked(is_locked)

            # Continue polling/saving while locked. SessionTracker.is_locked
            # forces the sampled state to idle, while update() also performs
            # the configured periodic persistence.
            self.update()

    def update(self):
        try:
            idle_time = self.platform.get_idle_time()
            if idle_time is not None:
                idle_time = float(idle_time)
                if not math.isfinite(idle_time) or idle_time < 0:
                    idle_time = None
        except Exception as exc:
            logger.warning("Idle-time detection failed: %s", exc)
            idle_time = None

        if idle_time is None:
            self._handle_idle_detection_failure()
            self.update_ui()
            return

        self._idle_detection_failure_shown = False
        try:
            self.session.on_tick(idle_time, self.idle_threshold)
        except PersistenceWriteError:
            self._alert_save_failure()
            return

        if time.time() - self.last_write_time >= self.write_interval:
            self._save_and_optimize()

        self.update_ui()

    def _handle_idle_detection_failure(self):
        logger.error(
            "Idle-time detection is unavailable; tracking is paused until it recovers."
        )
        if not self._idle_detection_failure_shown:
            self._idle_detection_failure_shown = True
            self.platform.show_alert(
                i18n.t("IDLE_DETECTION_ERROR_TITLE"),
                i18n.t("IDLE_DETECTION_ERROR_MSG"),
            )
        try:
            self.session.pause_tracking()
        except PersistenceWriteError:
            self._alert_save_failure()

    def _alert_save_failure(self, force_show: bool = False):
        # NFR-5.2: data is retained in memory; alert once per failure episode.
        logger.error(
            "Saving tracking data failed; data is retained in memory and will retry."
        )
        if force_show or not getattr(self, "_save_failure_shown", False):
            self._save_failure_shown = True
            self.platform.show_alert(
                i18n.t("SAVE_ERROR_TITLE"),
                i18n.t("SAVE_ERROR_MSG"),
            )

    def _clear_save_failure(self):
        self._save_failure_shown = False
        self.update_ui()

    def update_ui(self):
        today = datetime.now().date()
        week_start_date = today - timedelta(days=today.weekday())

        # Guard shared session state: the updater thread mutates
        # self.session.days / current_segment while this thread reads it.
        with self.session._lock:
            current_day_data = self.session.days.get(today)
            active_today = (
                current_day_data.total_active_seconds() if current_day_data else 0
            )
            is_idle = (
                self.session.current_segment.state == "idle"
                if self.session.current_segment
                else False
            )
            idle_today = (current_day_data.idle_minutes * 60) if current_day_data else 0
            session_start = current_day_data.session_start if current_day_data else None

        # Get cached weekly totals from the totals_cache (already cached per year)
        # This avoids reading CSV on every UI update
        weekly_active_minutes, weekly_idle_minutes = self.pm.get_weekly_minutes(
            week_start_date
        )

        # Get cached daily totals (already cached per year in totals_cache)
        today_csv_active, today_csv_idle = self.pm.get_minutes_for_date(today)

        # Calculate ongoing time for both active and idle.
        # Clamp to zero so the weekly totals can never go negative.
        active_ongoing_seconds = self._ongoing_seconds(active_today, today_csv_active)
        idle_ongoing_seconds = self._ongoing_seconds(idle_today, today_csv_idle)

        # Add ongoing seconds to weekly totals
        total_weekly_active = (weekly_active_minutes * 60) + active_ongoing_seconds
        total_weekly_idle = (weekly_idle_minutes * 60) + idle_ongoing_seconds

        self.menu.update_ui(
            is_idle,
            active_today,
            total_weekly_active,
            self.weekly_target_seconds,
            total_weekly_idle,
            idle_today,
            session_start,
        )

    def _ongoing_seconds(self, session_seconds: float, csv_minutes: int) -> float:
        """Return the live seconds not yet persisted to CSV, clamped to zero."""
        return max(0.0, session_seconds - csv_minutes * 60)

    def quit_app(self):
        try:
            self.session.finalize_session()
        except PersistenceWriteError:
            self._alert_save_failure(force_show=True)
            return
        self._running = False
        self._stop_event.set()
        self.menu.stop()

    def force_save(self):
        # A user-initiated save should always make the failure visible,
        # even if an automatic save already alerted during this episode.
        return self._save_and_optimize(force_alert=True, force_optimize=True)

    def _save_and_optimize(
        self,
        force_alert: bool = False,
        force_optimize: bool = False,
    ) -> bool:
        try:
            self.session.save_all_days()
            now = time.time()
            if (
                force_optimize
                or (now - self._last_optimize_time) >= OPTIMIZE_INTERVAL_SECONDS
            ):
                self.optimize_csv(silent=True)
                self._last_optimize_time = now
            self.last_write_time = now
            self._clear_save_failure()
            return True
        except PersistenceWriteError:
            self._alert_save_failure(force_show=force_alert)
            return False

    def set_target(self, seconds: int | float) -> None:
        self._set_config_int("target_work_seconds", "target_seconds", seconds)

    def set_weekly_target(self, seconds: int | float) -> None:
        self._set_config_int("weekly_target_seconds", "weekly_target_seconds", seconds)

    def set_idle_threshold(self, seconds: int | float) -> None:
        self._set_config_int(
            "idle_threshold",
            "idle_threshold_seconds",
            seconds,
            side_effect=lambda value: setattr(self.session, "idle_threshold", value),
        )

    def set_save_interval(self, seconds: int | float) -> None:
        self._set_config_int("write_interval", "save_interval_seconds", seconds)

    def set_language(self, code: str) -> None:
        set_config_value("locale", code)
        i18n.set_locale(code)

    def _set_config_int(
        self,
        attr: str,
        key: str,
        value: int | float,
        side_effect=None,
    ) -> None:
        """Store an integer config value, update the matching attribute, and
        optionally run a side effect with the normalized value."""
        normalized = int(value)
        setattr(self, attr, normalized)
        set_config_value(key, normalized)
        if side_effect is not None:
            side_effect(normalized)

    def select_data_folder(self):
        folder = self.platform.choose_folder_dialog(prompt=i18n.t("SELECT_DATA_FOLDER"))
        if folder is None:
            return
        self._switch_data_folder(lambda: set_data_dir(folder, persist=True))

    def reset_data_folder(self):
        self._switch_data_folder(reset_data_dir_to_default)

    def _switch_data_folder(self, change_data_dir: Callable[[], None]) -> None:
        """Persist current state, switch the data directory, and reload the session."""
        if not self.force_save():
            return
        change_data_dir()
        self.pm.clear_last_segment_write()
        self._reload_from_current_data_folder()

    def _reload_from_current_data_folder(self):
        """Reload in-memory session/weekly view from the current data folder."""
        # Clear cached paths/aggregates that were computed against the old folder.
        self.pm.invalidate_caches()

        # Rebuild today's in-memory segments from the new folder's file.
        with self.session._lock:
            self.session.days = {}
            self.session.current_segment = None
            self.session.load_current_day_segments()

        self.update_ui()

    def optimize_csv(self, silent: bool = False):
        # Serialize the file transaction, then release it before acquiring the
        # session lock for the in-memory reload. This avoids lock inversion with
        # save_all_days(), which takes the session lock before the CSV lock.
        with self.pm.csv_transaction():
            result = self._optimize_csv_locked(silent)
        if result is None:
            return

        today, original_count, merged_count, reduced_count = result
        self.session.load_current_day_segments(preserve_current_segment=True)

        msg = i18n.t("OPTIMIZE_SUCCESS_MSG").format(
            original=original_count, merged=merged_count, reduced=reduced_count
        )
        success_msg = i18n.t("OPTIMIZE_SUCCESS")

        if not silent:
            time.sleep(0.1)
            self.platform.bring_app_to_front()
            self.platform.show_alert(success_msg, msg)

    def _optimize_csv_locked(self, silent: bool = False):
        """Optimize one year's CSV log by normalizing every day and compacting.

        Optimization runs after successful interval-triggered saves and Force
        Save actions. When *silent* is True no alert is shown and the app is not
        brought to the front.
        """
        today = datetime.now().date()
        segments_file = self.pm.get_log_file_path("activities", today.year)

        if not os.path.exists(segments_file):
            if not silent:
                self.platform.show_alert(
                    i18n.t("OPTIMIZE_ERROR_NO_FILE"),
                    i18n.t("OPTIMIZE_ERROR_NO_FILE_MSG"),
                )
            return

        idle_threshold = get_config_value(
            "idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD_SECONDS
        )

        try:
            original_count, optimized_count = self.pm.optimize_year_file(
                today.year, int(idle_threshold)
            )
        except (OSError, csv.Error, UnicodeError) as exc:
            logger.error("Optimize failed for %s: %s", segments_file, exc)
            if not silent:
                self.platform.show_alert(
                    i18n.t("OPTIMIZE_READ_ERROR"),
                    i18n.t("OPTIMIZE_READ_ERROR_MSG"),
                )
            return

        if original_count == 0:
            if not silent:
                self.platform.show_alert(
                    i18n.t("OPTIMIZE_EMPTY"), i18n.t("OPTIMIZE_EMPTY_MSG")
                )
            return

        reduced_count = original_count - optimized_count
        return today, original_count, optimized_count, reduced_count


def main():
    """Entry point for Briefcase and direct execution."""
    # 1. Acquire single-instance lock
    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        platform = get_platform()  # Use the platform for the alert
        platform.show_alert(
            "ActivityTracker is already running.",
            "Another instance is already active. Please check your menu bar.",
        )
        sys.exit(1)

    # 2. Set up data directory and run the app
    set_data_dir(get_configured_data_dir())
    app = ActivityTrackerApp()
    app.run()


if __name__ == "__main__":
    main()

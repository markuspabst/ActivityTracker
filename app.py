from __future__ import annotations
import logging
import os
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
from models import TimeSegment
from persistence import PersistenceManager, PersistenceWriteError
from activity_tracker_menu import AppMenu
from single_instance import SingleInstanceLock

logger = logging.getLogger(__name__)

class ActivityTrackerApp:
    def __init__(self):
        cfg = load_config()
        i18n.set_locale(cfg.get("locale"))

        self.platform = get_platform()
        self.pm = PersistenceManager(get_configured_data_dir)
        self.session = SessionTracker(self.pm)
        self.session.load_current_day_segments()

        self.target_work_seconds = int(get_config_value("target_seconds", 8 * 3600))
        self.weekly_target_seconds = int(get_config_value("weekly_target_seconds", 40 * 3600))
        self.idle_threshold = int(get_config_value("idle_threshold_seconds", 300))
        self.write_interval = int(get_config_value("save_interval_seconds", 3600))

        self.last_write_time = time.time()
        self._running = False
        self._save_failure_shown = False

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
        try:
            self.session.on_tick(idle_time, self.idle_threshold)
        except PersistenceWriteError:
            self._alert_save_failure()
            return

        if time.time() - self.last_write_time >= self.write_interval:
            try:
                self.session.save_all_days()
                self.optimize_csv(silent=True)
                self.last_write_time = time.time()
                self._clear_save_failure()
            except PersistenceWriteError:
                self._alert_save_failure()

        self.update_ui()

    def _alert_save_failure(self):
        # NFR-5.2: data is retained in memory; alert once per failure episode.
        logger.error("Saving tracking data failed; data is retained in memory and will retry.")
        if not getattr(self, "_save_failure_shown", False):
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
        current_day_data = self.session.days.get(today)
        active_today = current_day_data.total_active_seconds() if current_day_data else 0
        is_idle = self.session.current_segment.state == 'idle' if self.session.current_segment else False

        week_start_date = today - timedelta(days=today.weekday())
        # Get weekly total from CSV
        weekly_active_minutes, weekly_idle_minutes = self.pm.get_weekly_minutes(week_start_date)

        # Include today's ongoing segment (which may not be in CSV yet)
        # The difference between in-memory total and CSV total is the ongoing time
        today_csv_active, today_csv_idle = self.pm.get_minutes_for_date(today)

        # Calculate ongoing time for both active and idle.
        # Clamp to zero so the weekly totals can never go negative (e.g. after
        # optimize/merge reduces the in-memory total, or due to clock skew).
        active_ongoing_seconds = max(0, active_today - (today_csv_active * 60))
        idle_ongoing_minutes = max(0, (current_day_data.idle_minutes if current_day_data else 0) - today_csv_idle)
        idle_ongoing_seconds = idle_ongoing_minutes * 60

        # Add ongoing seconds to weekly totals
        total_weekly_active = (weekly_active_minutes * 60) + active_ongoing_seconds
        total_weekly_idle = (weekly_idle_minutes * 60) + idle_ongoing_seconds

        self.menu.update_ui(is_idle, active_today, total_weekly_active, self.weekly_target_seconds, total_weekly_idle)

    def quit_app(self):
        self._running = False
        try:
            self.session.finalize_session()
        except PersistenceWriteError:
            self._alert_save_failure()
        self.menu.stop()

    def force_save(self):
        try:
            self.session.save_all_days()
            self.optimize_csv(silent=True)
            self.last_write_time = time.time()
            self._clear_save_failure()
        except PersistenceWriteError:
            self._alert_save_failure()

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
        set_data_dir(folder)
        persist_data_dir(folder)

    def reset_data_folder(self):
        self.force_save()
        reset_data_dir_to_default()

    def optimize_csv(self, silent: bool = False):
        """Merge consecutive same-state segments with small gaps in the CSV file.

        Optimization runs automatically after every successful save (see
        ``update`` / ``force_save``), so the on-disk log stays compact without
        user action. When *silent* is True no alert is shown and the app is not
        brought to the front.
        """
        import csv
        from datetime import datetime
        from tracking import get_config_value

        today = datetime.now().date()
        segments_file = self.pm.get_log_file_path('activities', today.year)

        if not os.path.exists(segments_file):
            if not silent:
                self.platform.show_alert(
                    i18n.t("OPTIMIZE_ERROR_NO_FILE"),
                    i18n.t("OPTIMIZE_ERROR_NO_FILE_MSG")
                )
            return

        # Get idle threshold from config (default 300 sec)
        idle_threshold = get_config_value("idle_threshold_seconds", 300)

        # Read all segments from the year file
        all_segments = []
        original_count = 0
        with open(segments_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                original_count += 1
                try:
                    parts = row['start'].split(':')
                    start_dt = datetime(int(row['date'][:4]), int(row['date'][5:7]),
                                      int(row['date'][8:10]),
                                      int(parts[0]), int(parts[1]),
                                      int(parts[2]) if len(parts) > 2 else 0)

                    end_dt = None
                    if row['end']:
                        parts = row['end'].split(':')
                        end_dt = datetime(int(row['date'][:4]), int(row['date'][5:7]),
                                        int(row['date'][8:10]),
                                        int(parts[0]), int(parts[1]),
                                        int(parts[2]) if len(parts) > 2 else 0)

                    all_segments.append(TimeSegment(
                        state=row['state'],
                        start_time=start_dt,
                        end_time=end_dt
                    ))
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue

        if not all_segments:
            if not silent:
                self.platform.show_alert(
                    i18n.t("OPTIMIZE_EMPTY"),
                    i18n.t("OPTIMIZE_EMPTY_MSG")
                )
            return

        # Merge segments
        merged_segments = self.pm.merge_segments_to_save(all_segments, int(idle_threshold))
        merged_count = len(merged_segments)
        reduced_count = original_count - merged_count

        # Write merged segments back to CSV
        try:
            with open(segments_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["date", "state", "start", "end", "duration_min", "duration_seconds"])
                writer.writeheader()
                for seg in merged_segments:
                    writer.writerow({
                        "date": seg.start_time.strftime("%Y-%m-%d"),
                        "state": seg.state,
                        "start": seg.start_time.strftime("%H:%M:%S"),
                        "end": seg.end_time.strftime("%H:%M:%S") if seg.end_time else "",
                        "duration_min": seg.duration_minutes,
                        "duration_seconds": int((seg.end_time - seg.start_time).total_seconds()) if seg.end_time else 0,
                    })
        except OSError as exc:
            logger.error("Optimize failed to write %s: %s", segments_file, exc)
            if not silent:
                self.platform.show_alert(
                    i18n.t("SAVE_ERROR_TITLE"),
                    i18n.t("SAVE_ERROR_MSG"),
                )
            return

        # Reload the optimized segments into memory (the file is now authoritative).
        # The optimized file already contains every day/segment, so re-writing it
        # via save_all_days() would be a redundant second pass; load_current_day_segments
        # repopulates in-memory state (including the live ongoing segment) directly.
        self.session.load_current_day_segments()

        # Show success message with optimization results
        msg = i18n.t("OPTIMIZE_SUCCESS_MSG").format(
            original=original_count,
            merged=merged_count,
            reduced=reduced_count
        )
        success_msg = i18n.t("OPTIMIZE_SUCCESS")

        print(f"Optimization complete: {success_msg} - {msg}")
        print(f"  Original: {original_count}, Merged: {merged_count}, Reduced: {reduced_count}")

        if not silent:
            # Bring app to front to ensure alert is visible
            import time
            time.sleep(0.1)  # Brief delay to ensure file write completes
            self.platform.bring_app_to_front()
            # Show alert with brief delay
            time.sleep(0.1)  # Brief delay before showing alert
            self.platform.show_alert(success_msg, msg)

if __name__ == "__main__":
    # 1. Acquire single-instance lock
    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        platform = get_platform()  # Use the platform for the alert
        platform.show_alert(
            "ActivityTracker is already running.",
            "Another instance of the application is already active. Please check your menu bar."
        )
        sys.exit(1)

    # 2. Set up data directory and run the app
    set_data_dir(get_configured_data_dir())
    app = ActivityTrackerApp()
    app.run()
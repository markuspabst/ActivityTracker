
from __future__ import annotations
import functools
from datetime import datetime, timedelta

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

import i18n
from platform_layer import get_platform
from tracking import (
    format_delta,
    format_hours,
    get_current_week_dates,
    get_status_icon,
    read_csv_data,
    get_day_from_csv,
    get_weekly_seconds_from_csv,
    get_configured_data_dir,
)


class AppMenu:
    def __init__(self, app_controller):
        self.app = app_controller
        self.platform = get_platform()
        self._last_status_icon = None

        initial_icon = self._create_icon("🔴")
        self.icon = Icon("ActivityTracker", initial_icon, "ActivityTracker", Menu(self._generate_menu_items))

    def run(self):
        self.icon.run()

    def stop(self):
        self.icon.stop()

    @functools.lru_cache(maxsize=8)
    def _create_icon(self, emoji_char, size=64):
        """Renders a colored circle icon for the menu bar."""
        color_map = {"🔴": (255, 50, 50), "🟡": (255, 200, 30), "🟢": (50, 200, 50)}
        color = color_map.get(emoji_char, (200, 200, 200))
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        margin = 3
        draw.ellipse([margin, margin, size - margin, size - margin], fill=color + (255,))
        return img

    def update_ui(self, is_idle, active_today):
        status_emoji = get_status_icon(is_idle, active_today, self.app.target_work_seconds)
        if status_emoji != self._last_status_icon:
            self.icon.icon = self._create_icon(status_emoji)
            self._last_status_icon = status_emoji

        self.icon.title = f"{format_hours(active_today)}"
        self.icon.update_menu()

    def _generate_menu_items(self):
        # Main stats
        now, total_session, active_session, idle_session, is_idle = self.app.calculate_current_session()
        csv_data = read_csv_data()
        report = self.app.session.build_report(now, total_session, active_session, idle_session, csv_data)

        active_today = report["active_seconds"]
        idle_today = report["idle_seconds"]
        total_today = report["total_seconds"]
        daily_overtime = active_today - self.app.target_work_seconds

        weekly_from_csv = get_weekly_seconds_from_csv(data=csv_data)
        _, delta_active, _ = self.app.session.calculate_unsaved_delta(total_session, active_session, idle_session)
        weekly_total = weekly_from_csv + delta_active
        weekly_overtime = weekly_total - self.app.weekly_target_seconds

        yield MenuItem(i18n.t("MENU_ACTIVE", value=format_hours(active_today)), None, enabled=False)
        yield MenuItem(i18n.t("MENU_IDLE", value=format_hours(idle_today)), None, enabled=False)
        yield MenuItem(i18n.t("MENU_TOTAL", value=format_hours(total_today)), None, enabled=False)
        yield Menu.SEPARATOR
        yield MenuItem(i18n.t("MENU_START_TIME", value=report["start_time"]), None, enabled=False)
        yield Menu.SEPARATOR

        # Daily target
        yield MenuItem(i18n.t("MENU_TODAY_TARGET", value=format_hours(self.app.target_work_seconds)), None, enabled=False)
        overtime_key = "TODAY_OVERTIME_POS" if daily_overtime >= 0 else "TODAY_OVERTIME_NEG"
        yield MenuItem(i18n.t(overtime_key, value=format_delta(daily_overtime)), None, enabled=False)
        yield Menu.SEPARATOR

        # Weekly target
        weekly_target_formatted = format_hours(self.app.weekly_target_seconds)
        yield MenuItem(i18n.t("WEEK_TOTAL", value=format_hours(weekly_total), target=weekly_target_formatted), None, enabled=False)
        weekly_overtime_key = "WEEK_OVERTIME_POS" if weekly_overtime >= 0 else "WEEK_OVERTIME_NEG"
        yield MenuItem(i18n.t(weekly_overtime_key, value=format_delta(weekly_overtime)), None, enabled=False)
        yield Menu.SEPARATOR

        start_display = self.app.session.first_activity_this_day.strftime('%H:%M:%S') if self.app.session.first_activity_this_day else 'N/A'
        yield MenuItem(i18n.t("MENU_START", value=start_display), None, enabled=False)
        yield MenuItem(i18n.t("MENU_UPDATE", value=now.strftime('%H:%M:%S')), None, enabled=False)
        yield MenuItem(i18n.t("MENU_SAVED", value=self.app.last_save_display), None, enabled=False)
        yield Menu.SEPARATOR

        # Settings submenu
        yield MenuItem(i18n.t("SETTINGS"), self._generate_settings_menu())
        yield Menu.SEPARATOR
        yield MenuItem(i18n.t("FORCE_SAVE"), self.app.force_save)
        yield MenuItem(i18n.t("QUIT"), self.app.quit_app)

    def _generate_settings_menu(self):
        """Creates the settings submenu."""

        def _slider_callback(setter, title_key, current, factor, min_v, max_v):
            def _callback(_):
                value = self.platform.ask_slider_dialog(i18n.t(title_key), current, min_v, max_v)
                if value is not None and value > 0:
                    setter(int(value * factor))
            return _callback

        # Daily Target
        target_menu_items = []
        for h in range(1, 25):
            target_menu_items.append(MenuItem(f'{h}h', (lambda h_val: lambda *args: self.app.set_target(h_val * 3600))(h), checked=lambda item, h_val=h: self.app.target_work_seconds == h_val * 3600))
        target_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(i18n.t("SET_CUSTOM_VALUE"), _slider_callback(self.app.set_target, "ASK_DAILY_TARGET_TITLE", self.app.target_work_seconds / 3600, 3600, 1.0, 24.0), enabled=self.platform.supports_native_dialogs())
        ])

        # Weekly Target
        weekly_target_menu_items = []
        weekly_target_menu_items.append(MenuItem('1h', (lambda *args: self.app.set_weekly_target(1 * 3600)), checked=lambda item: self.app.weekly_target_seconds == 1 * 3600))
        for h in range(5, 169, 5):
            weekly_target_menu_items.append(MenuItem(f'{h}h', (lambda h_val: lambda *args: self.app.set_weekly_target(h_val * 3600))(h), checked=lambda item, h_val=h: self.app.weekly_target_seconds == h_val * 3600))
        weekly_target_menu_items.append(MenuItem('168h', (lambda *args: self.app.set_weekly_target(168 * 3600)), checked=lambda item: self.app.weekly_target_seconds == 168 * 3600))
        weekly_target_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(i18n.t("SET_CUSTOM_VALUE"), _slider_callback(self.app.set_weekly_target, "ASK_WEEKLY_TARGET_TITLE", self.app.weekly_target_seconds / 3600, 3600, 1.0, 168.0), enabled=self.platform.supports_native_dialogs())
        ])

        # Idle Threshold
        idle_menu_items = []
        for m in [1, 2, 3, 5, 10, 15, 20, 30]:
            idle_menu_items.append(MenuItem(f'{m} min', (lambda m_val: lambda *args: self.app.set_idle_threshold(m_val * 60))(m), checked=lambda item, m_val=m: self.app.idle_threshold == m_val * 60))
        idle_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(i18n.t("SET_CUSTOM_VALUE"), _slider_callback(self.app.set_idle_threshold, "ASK_IDLE_THRESHOLD_TITLE", self.app.idle_threshold / 60, 60, 1, 30), enabled=self.platform.supports_native_dialogs())
        ])

        # Save Interval
        save_interval_menu_items = []
        for m in [1, 5, 15, 30, 60, 120]:
            save_interval_menu_items.append(MenuItem(f'{m} min', (lambda m_val: lambda *args: self.app.set_save_interval(m_val * 60))(m), checked=lambda item, m_val=m: self.app.write_interval == m_val * 60))
        save_interval_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(i18n.t("SET_CUSTOM_VALUE"), _slider_callback(self.app.set_save_interval, "ASK_SAVE_INTERVAL_TITLE", self.app.write_interval / 60, 60, 1, 120), enabled=self.platform.supports_native_dialogs())
        ])

        # Data Folder
        data_folder_menu = Menu(
            MenuItem(get_configured_data_dir(), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(i18n.t("OPEN_DATA_FOLDER"), lambda: self.platform.open_file_manager(get_configured_data_dir())),
            MenuItem(i18n.t("SELECT_DATA_FOLDER"), self.app.select_data_folder, enabled=self.platform.supports_native_dialogs()),
            MenuItem(i18n.t("RESET_DATA_FOLDER"), self.app.reset_data_folder),
        )


        return Menu(
            MenuItem(i18n.t("DAILY_TARGET"), Menu(*target_menu_items)),
            MenuItem(i18n.t("WEEKLY_TARGET"), Menu(*weekly_target_menu_items)),
            MenuItem(i18n.t("IDLE_THRESHOLD"), Menu(*idle_menu_items)),
            MenuItem(i18n.t("SAVE_INTERVAL"), Menu(*save_interval_menu_items)),
            Menu.SEPARATOR,
            MenuItem(i18n.t("DATA_FOLDER"), data_folder_menu),
            # ... Add other settings menus for Language, Autostart, Version etc. here
        )


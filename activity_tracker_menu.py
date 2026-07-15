
from __future__ import annotations
from datetime import datetime, timedelta

from pystray import Icon, Menu, MenuItem

import i18n
from platform_layer import get_platform
from tray_icon import create_icon, get_status_icon
from tracking import (
    format_hours,
)

class AppMenu:
    def __init__(self, app_controller):
        self.app = app_controller
        self.platform = get_platform()
        self._last_status_icon = None
        self._active_today_session = 0
        self._idle_today_session = 0
        self._session_start = None
        self._total_weekly_active = 0
        self._total_weekly_idle = 0

        # The icon is created here but will be updated immediately by the first UI update
        self.icon = Icon("ActivityTracker", create_icon("🟡"), "ActivityTracker", Menu(self._generate_menu_items))

    def run(self):
        self.icon.run()

    def stop(self):
        self.icon.stop()

    def update_ui(self, is_idle, active_today, active_week, weekly_target):
        today_date = datetime.now().date()
        today_data = self.app.session.days.get(today_date)

        # Use the correctly calculated active_today value passed from app.py
        self._active_today_session = active_today
        self._idle_today_session = today_data.idle_minutes if today_data else 0
        self._session_start = today_data.session_start if today_data else None

        self._total_weekly_active = active_week

        # Calculate weekly idle time, avoiding double-counting
        week_start_date = today_date - timedelta(days=today_date.weekday())
        current_week_idle_total_minutes = 0
        for i in range(7):
            day_in_week = week_start_date + timedelta(days=i)
            if day_in_week < today_date:
                # For past days in the week, read idle summary from CSV
                _, idle_minutes_for_day = self.app.pm.read_daily_summary_for_day(day_in_week)
                current_week_idle_total_minutes += idle_minutes_for_day
            elif day_in_week == today_date:
                # For today, use the current in-memory data
                if today_data:
                    current_week_idle_total_minutes += today_data.idle_minutes
            # Future days (day_in_week > today_date) will contribute 0, which is correct

        self._total_weekly_idle = current_week_idle_total_minutes * 60

        # Update icon status and title
        status_emoji = get_status_icon(is_idle, active_today, self.app.target_work_seconds, active_week, weekly_target)
        if status_emoji != self._last_status_icon:
            self.icon.icon = create_icon(status_emoji)
            self._last_status_icon = status_emoji

        self.icon.title = f"{format_hours(active_today)}"
        self.icon.update_menu()

    def _generate_menu_items(self):
        # These yields use the pre-calculated values from the last UI update
        yield MenuItem(i18n.t("MENU_START_TIME", value=self._session_start.strftime("%H:%M") if self._session_start else "N/A"), None, enabled=False)
        yield MenuItem(i18n.t("MENU_ACTIVE", value=format_hours(self._active_today_session)), None, enabled=False)
        yield MenuItem(i18n.t("MENU_IDLE", value=format_hours(self._idle_today_session * 60)), None, enabled=False)
        yield Menu.SEPARATOR

        # Weekly Summary
        yield MenuItem(i18n.t("WEEK_ACTIVE", value=format_hours(self._total_weekly_active)), None, enabled=False)
        yield MenuItem(i18n.t("WEEK_IDLE", value=format_hours(self._total_weekly_idle)), None, enabled=False)
        yield Menu.SEPARATOR

        yield MenuItem(i18n.t("SETTINGS"), self._generate_settings_menu())
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
            MenuItem(self.app.pm.get_data_dir(), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(i18n.t("OPEN_DATA_FOLDER"), lambda: self.platform.open_file_manager(self.app.pm.get_data_dir())),
            MenuItem(i18n.t("SELECT_DATA_FOLDER"), self.app.select_data_folder, enabled=self.platform.supports_native_dialogs()),
            MenuItem(i18n.t("RESET_DATA_FOLDER"), self.app.reset_data_folder),
        )

        # Autostart
        autostart_installed = self.platform.autostart_installed()
        autostart_label = "AUTOSTART_ENABLED" if autostart_installed else "AUTOSTART_DISABLED"



        # Language
        lang_menu_items = []
        lang_menu_items.append(MenuItem(i18n.t("LANGUAGE_SYSTEM_DEFAULT"), lambda *args: self.app.set_language(None), checked=lambda item: i18n._lang is None))
        for code in i18n.available_locales():
            lang_menu_items.append(MenuItem(code.upper(), (lambda c: lambda *args: self.app.set_language(c))(code), checked=lambda item, c=code: i18n._lang == c))

        return Menu(
            MenuItem(i18n.t("LANGUAGE"), Menu(*lang_menu_items)),
            Menu.SEPARATOR,
            MenuItem(i18n.t("DAILY_TARGET"), Menu(*target_menu_items)),
            MenuItem(i18n.t("WEEKLY_TARGET"), Menu(*weekly_target_menu_items)),
            MenuItem(i18n.t("IDLE_THRESHOLD"), Menu(*idle_menu_items)),
            MenuItem(i18n.t("SAVE_INTERVAL"), Menu(*save_interval_menu_items)),
            Menu.SEPARATOR,
            MenuItem(i18n.t("DATA_FOLDER"), data_folder_menu),
            MenuItem(i18n.t(autostart_label), self._toggle_autostart, checked=lambda item: self.platform.autostart_installed()),
        )

    def _toggle_autostart(self):
        """Toggle the launch-at-login autostart on/off."""
        try:
            if self.platform.autostart_installed():
                self.platform.uninstall_autostart()
            else:
                self.app.force_save()
                self.platform.install_autostart()
        except Exception as e:
            print(f"Autostart error: {e}")

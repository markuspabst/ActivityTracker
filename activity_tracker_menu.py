
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

    def update_ui(self, is_idle, active_today, active_week, weekly_target, weekly_idle_week=None):
        today_date = datetime.now().date()
        today_data = self.app.session.days.get(today_date)

        # Use the correctly calculated active_today value passed from app.py (already in seconds)
        self._active_today_session = active_today
        # Convert idle_minutes to seconds to match active_today units
        self._idle_today_session = (today_data.idle_minutes * 60) if today_data else 0
        self._session_start = today_data.session_start if today_data else None

        # Use pre-calculated weekly values from app.py (includes ongoing segments)
        self._total_weekly_active = active_week
        self._total_weekly_idle = weekly_idle_week if weekly_idle_week is not None else 0

        # Update icon status and title
        status_emoji = get_status_icon(is_idle, active_today, self.app.target_work_seconds, active_week, weekly_target)
        if status_emoji != self._last_status_icon:
            self.icon.icon = create_icon(status_emoji)
            self._last_status_icon = status_emoji

        # Update tray icon title with status emoji and time
        if is_idle:
            status_indicator = "⏸️"  # Paused
        elif active_today >= self.app.target_work_seconds:
            status_indicator = "✅"  # Target met
        elif (self._total_weekly_active / self.app.weekly_target_seconds * 100) >= 50:
            status_indicator = "🟢"  # On track
        else:
            status_indicator = "⏱️"  # In progress

        self.icon.title = f"{status_indicator} {format_hours(active_today)}"
        self.icon.update_menu()

    def _generate_menu_items(self):
        # Calculate today's progress percentage
        today_progress = (self._active_today_session / self.app.target_work_seconds * 100) if self.app.target_work_seconds > 0 else 0
        # Calculate weekly progress percentage
        weekly_progress = (self._total_weekly_active / self.app.weekly_target_seconds * 100) if self.app.weekly_target_seconds > 0 else 0

        # Use formatted progress strings
        if 0 < today_progress <= 100:
            today_progress_str = i18n.t("TODAY_PROGRESS", active=format_hours(self._active_today_session),
                                        target=format_hours(self.app.target_work_seconds), percentage=today_progress)
        else:
            today_progress_str = f"{i18n.t('MENU_ACTIVE', value=format_hours(self._active_today_session))} ({today_progress:.0f}%)"

        if 0 < weekly_progress < 100:
            weekly_progress_str = i18n.t("WEEKLY_PROGRESS", active=format_hours(self._total_weekly_active),
                                        target=format_hours(self.app.weekly_target_seconds), percentage=weekly_progress)
        else:
            weekly_progress_str = f"{i18n.t('WEEK_ACTIVE', value=format_hours(self._total_weekly_active))} / {format_hours(self.app.weekly_target_seconds)}"

        # Session start
        yield MenuItem(i18n.t("MENU_SESSION_STARTED", value=self._session_start.strftime("%H:%M") if self._session_start else "N/A"), None, enabled=False)

        # Today's progress
        yield MenuItem(today_progress_str, None, enabled=False)

        # Today's idle (only if active time > 0)
        if self._active_today_session > 0:
            yield MenuItem(i18n.t("MENU_IDLE", value=format_hours(self._idle_today_session)), None, enabled=False)

        yield Menu.SEPARATOR

        # Weekly progress
        yield MenuItem(weekly_progress_str, None, enabled=False)

        # Weekly idle (only if there's any data)
        if self._total_weekly_active > 0 and self._total_weekly_idle > 0:
            yield MenuItem(i18n.t("WEEK_IDLE", value=format_hours(self._total_weekly_idle)), None, enabled=False)

        yield Menu.SEPARATOR

        yield MenuItem(i18n.t("GENERAL_SETTINGS"), self._generate_general_settings_menu())
        yield MenuItem(i18n.t("GLOBAL_SETTINGS"), self._generate_global_settings_menu())
        yield MenuItem(i18n.t("QUIT"), self.app.quit_app)

    def _create_daily_settings_submenu(self):
        """Creates the daily settings submenu with target, threshold, and interval options."""

        def _slider_callback(setter, title_key, current, factor, min_v, max_v):
            def _callback(_):
                value = self.platform.ask_slider_dialog(i18n.t(title_key), current, min_v, max_v)
                if value is not None and value > 0:
                    setter(int(value * factor))
            return _callback

        # Daily Target with Smart Presets
        daily_target_menu_items = []
        # Presets: 2h (min), 4h (light), 6h (recommended), 8h (standard), 10h (heavy) + custom
        daily_presets = [
            (2, i18n.t("TARGET_2H_MIN")),
            (4, i18n.t("TARGET_4H_SHORT")),
            (6, i18n.t("TARGET_6H_RECOMMENDED")),
            (8, i18n.t("TARGET_8H_STANDARD")),
            (10, i18n.t("TARGET_10H_HEAVY")),
        ]
        for hours, display_text in daily_presets:
            daily_target_menu_items.append(MenuItem(display_text,
                (lambda h_val: lambda *args: self.app.set_target(h_val * 3600))(hours),
                checked=lambda item, h_val=hours: self.app.target_work_seconds == h_val * 3600))
        daily_target_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(i18n.t("SET_CUSTOM_VALUE"),
                _slider_callback(self.app.set_target, "ASK_DAILY_TARGET_TITLE",
                               self.app.target_work_seconds / 3600, 3600, 1.0, 24.0),
                enabled=self.platform.supports_native_dialogs())
        ])

        # Create submenu for Daily Target
        daily_target_submenu = Menu(*daily_target_menu_items)

        # Weekly Target with Smart Presets
        weekly_target_menu_items = []
        weekly_presets = [
            (20, i18n.t("WEEK_TARGET_20H_LIGHT")),
            (40, i18n.t("WEEK_TARGET_40H_STANDARD")),
            (60, i18n.t("WEEK_TARGET_60H_HEAVY")),
            (84, i18n.t("WEEK_TARGET_84H_MAX")),
        ]
        for hours, display_text in weekly_presets:
            weekly_target_menu_items.append(MenuItem(display_text,
                (lambda h_val: lambda *args: self.app.set_weekly_target(h_val * 3600))(hours),
                checked=lambda item, h_val=hours: self.app.weekly_target_seconds == h_val * 3600))
        weekly_target_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(i18n.t("SET_CUSTOM_VALUE"),
                _slider_callback(self.app.set_weekly_target, "ASK_WEEKLY_TARGET_TITLE",
                               self.app.weekly_target_seconds / 3600, 3600, 1.0, 168.0),
                enabled=self.platform.supports_native_dialogs())
        ])

        # Create submenu for Weekly Target
        weekly_target_submenu = Menu(*weekly_target_menu_items)

        # Idle Threshold with Presets
        idle_menu_items = []
        idle_presets = [1, 2, 3, 5, 10, 15, 20, 30]
        for m in idle_presets:
            idle_menu_items.append(MenuItem(f'{m} min',
                (lambda m_val: lambda *args: self.app.set_idle_threshold(m_val * 60))(m),
                checked=lambda item, m_val=m: self.app.idle_threshold == m_val * 60))
        idle_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(i18n.t("SET_CUSTOM_VALUE"),
                _slider_callback(self.app.set_idle_threshold, "ASK_IDLE_THRESHOLD_TITLE",
                               self.app.idle_threshold / 60, 60, 1, 30),
                enabled=self.platform.supports_native_dialogs())
        ])

        # Create submenu for Idle Threshold
        idle_submenu = Menu(*idle_menu_items)

        # Save Interval with Presets
        save_interval_menu_items = []
        save_presets = [1, 5, 15, 30, 60, 120]
        for m in save_presets:
            save_interval_menu_items.append(MenuItem(f'{m} min',
                (lambda m_val: lambda *args: self.app.set_save_interval(m_val * 60))(m),
                checked=lambda item, m_val=m: self.app.write_interval == m_val * 60))
        save_interval_menu_items.extend([
            Menu.SEPARATOR,
            MenuItem(i18n.t("SET_CUSTOM_VALUE"),
                _slider_callback(self.app.set_save_interval, "ASK_SAVE_INTERVAL_TITLE",
                               self.app.write_interval / 60, 60, 1, 120),
                enabled=self.platform.supports_native_dialogs())
        ])

        # Create submenu for Save Interval
        save_interval_submenu = Menu(*save_interval_menu_items)

        # Main daily settings menu
        # Add separators for cleaner organization
        return Menu(
            MenuItem(i18n.t("DAILY_TARGET"), daily_target_submenu),
            MenuItem(i18n.t("WEEKLY_TARGET"), weekly_target_submenu),
            Menu.SEPARATOR,
            MenuItem(i18n.t("IDLE_THRESHOLD"), idle_submenu),
            Menu.SEPARATOR,
            MenuItem(i18n.t("SAVE_INTERVAL"), save_interval_submenu),
            Menu.SEPARATOR,
            MenuItem(i18n.t("SAVE_NOW"), self.app.force_save),
        )

    def _create_global_settings_submenu(self):
        """Creates the global settings submenu with language, data folder, and autostart options."""

        # Language
        lang_menu_items = []
        lang_menu_items.append(MenuItem(i18n.t("LANGUAGE_SYSTEM_DEFAULT"),
            lambda *args: self.app.set_language(None),
            checked=lambda item: i18n._lang is None))
        for code in i18n.available_locales():
            lang_menu_items.append(MenuItem(code.upper(),
                (lambda c: lambda *args: self.app.set_language(c))(code),
                checked=lambda item, c=code: i18n._lang == c))

        # Create submenu for Language
        language_submenu = Menu(*lang_menu_items)

        # Data Folder
        data_folder_menu = Menu(
            MenuItem(self.app.pm.get_data_dir(), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(i18n.t("OPEN_DATA_FOLDER"), lambda: self.platform.open_file_manager(self.app.pm.get_data_dir())),
            MenuItem(i18n.t("SELECT_DATA_FOLDER"), self.app.select_data_folder,
                   enabled=self.platform.supports_native_dialogs()),
            MenuItem(i18n.t("RESET_DATA_FOLDER"), self.app.reset_data_folder),
            Menu.SEPARATOR,
            MenuItem(i18n.t("OPTIMIZE_DATA_FILE"), lambda item: self.app.optimize_csv()),
        )

        # Autostart
        autostart_item = MenuItem(i18n.t("AUTOSTART_ENABLED"), self._toggle_autostart,
                                 checked=lambda item: self.platform.autostart_installed())

        # Main global settings menu
        return Menu(
            MenuItem(i18n.t("LANGUAGE"), language_submenu),
            Menu.SEPARATOR,
            MenuItem(i18n.t("DATA_FOLDER"), data_folder_menu),
            Menu.SEPARATOR,
            autostart_item,
        )

    def _generate_general_settings_menu(self):
        """Creates the general settings submenu."""
        return self._create_daily_settings_submenu()

    def _generate_global_settings_menu(self):
        """Creates the global settings submenu."""
        return self._create_global_settings_submenu()

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

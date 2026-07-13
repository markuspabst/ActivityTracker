
from __future__ import annotations
import functools
from datetime import datetime, timedelta

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

import i18n
from platform_layer import get_platform
from tracking import (
    format_hours,
    get_status_icon,
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
        now = datetime.now()
        today_date = now.date()
        today_data = self.app.session.days.get(today_date)

        # Daily stats from current session
        active_today_session = today_data.active_minutes if today_data else 0
        idle_today_session = today_data.idle_minutes if today_data else 0
        session_start = today_data.session_start if today_data else None

        # Get historical weekly totals from CSV
        week_start_date = today_date - timedelta(days=today_date.weekday())
        weekly_active_from_csv, weekly_idle_from_csv = self.app.pm.read_daily_summaries_for_week(week_start_date)

        # Get totals for any tracked days in the current session (that might not be saved yet)
        weekly_active_session = 0
        weekly_idle_session = 0
        for i in range(7):
            day_in_week = week_start_date + timedelta(days=i)
            day_data = self.app.session.days.get(day_in_week)
            if day_data:
                weekly_active_session += day_data.active_minutes
                weekly_idle_session += day_data.idle_minutes

        # Final totals
        total_weekly_active = weekly_active_from_csv + weekly_active_session
        total_weekly_idle = weekly_idle_from_csv + weekly_idle_session

        yield MenuItem(i18n.t("MENU_START_TIME", value=session_start.strftime("%H:%M") if session_start else "N/A"), None, enabled=False)
        yield MenuItem(i18n.t("MENU_ACTIVE", value=format_hours(active_today_session * 60)), None, enabled=False)
        yield MenuItem(i18n.t("MENU_IDLE", value=format_hours(idle_today_session * 60)), None, enabled=False)
        yield Menu.SEPARATOR

        # Weekly Summary
        yield MenuItem(i18n.t("WEEK_ACTIVE", value=format_hours(total_weekly_active * 60)), None, enabled=False)
        yield MenuItem(i18n.t("WEEK_IDLE", value=format_hours(total_weekly_idle * 60)), None, enabled=False)
        yield Menu.SEPARATOR

        # ... (Settings and other menu items as before)

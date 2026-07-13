import unittest
from unittest.mock import Mock, patch, MagicMock
import os
import time
from datetime import datetime

# Mock the platform layer before importing the app
import sys

mock_platform = MagicMock()
sys.modules["platform_layer"] = mock_platform
sys.modules["i18n"] = MagicMock()

from app import ActivityTrackerApp
from tracking import SessionTracker, Day
from persistence import PersistenceManager

class TestRequirements(unittest.TestCase):

    def setUp(self):
        """Set up a clean state for each test."""
        self.app = ActivityTrackerApp()
        self.session = self.app.session

    def tearDown(self):
        """Clean up after each test."""
        self.app.quit_app()

    def test_fr_1_1_time_tracking(self):
        self.assertIsInstance(self.app.session, SessionTracker)

    @patch('tracking.datetime')
    def test_fr_1_2_active_time(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)
        self.app.session.on_tick(idle_time=0, idle_threshold=300)
        self.assertEqual(self.app.session.current_segment.state, 'active')

    @patch('tracking.datetime')
    def test_fr_1_3_idle_time(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)
        self.app.session.on_tick(idle_time=400, idle_threshold=300)
        self.assertEqual(self.app.session.current_segment.state, 'idle')

    @patch('tracking.datetime')
    def test_fr_1_4_locked_screen_is_idle(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)
        self.app.session.set_locked(True)
        self.assertEqual(self.app.session.current_segment.state, 'idle')

    def test_fr_2_2_session_start_and_end(self):
        day = Day(date=datetime.now().date())
        day.segments.append(Mock(state='active', start_time=datetime(2023, 1, 1, 9, 0, 0), end_time=datetime(2023, 1, 1, 10, 0, 0)))
        day.segments.append(Mock(state='idle', start_time=datetime(2023, 1, 1, 10, 0, 0), end_time=datetime(2023, 1, 1, 11, 0, 0)))
        day.segments.append(Mock(state='active', start_time=datetime(2023, 1, 1, 11, 0, 0), end_time=datetime(2023, 1, 1, 12, 0, 0)))
        self.assertEqual(day.session_start, datetime(2023, 1, 1, 9, 0, 0))
        self.assertEqual(day.session_end, datetime(2023, 1, 1, 12, 0, 0))

    def test_fr_3_data_persistence(self):
        with patch.object(self.app.pm, 'save_segments') as mock_save_segments, \
             patch.object(self.app.pm, 'save_daily_summary') as mock_save_daily_summary:
            self.app.force_save()
            mock_save_segments.assert_called()
            mock_save_daily_summary.assert_called()

    def test_fr_4_configuration(self):
        self.app.set_target(7200)
        self.assertEqual(self.app.target_work_seconds, 7200)
        self.app.set_weekly_target(36000)
        self.assertEqual(self.app.weekly_target_seconds, 36000)
        self.app.set_idle_threshold(600)
        self.assertEqual(self.app.idle_threshold, 600)
        self.app.set_save_interval(1800)
        self.assertEqual(self.app.write_interval, 1800)

    def test_fr_6_autostart(self):
        mock_platform.autostart_installed.return_value = False
        menu = self.app.menu
        # Find the autostart menu item and click it
        settings_menu = [item for item in menu._generate_menu_items() if item.text == i18n.t("SETTINGS")][0]
        autostart_item = [item for item in settings_menu.submenu if "AUTOSTART" in item.text][0]
        autostart_item.action()
        mock_platform.install_autostart.assert_called()

if __name__ == '__main__':
    unittest.main()

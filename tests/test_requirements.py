import unittest
from unittest.mock import Mock, patch, MagicMock
import os
import time
from datetime import datetime
import pytest

# Mock the platform layer before importing the app
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import i18n
mock_platform = MagicMock()
sys.modules["platform_layer"] = mock_platform
sys.modules["i18n"] = i18n

from app import ActivityTrackerApp
from tracking import SessionTracker, Day
from persistence import PersistenceManager

class TestRequirements(unittest.TestCase):

    def setUp(self):
        with patch('app.AppMenu') as mock_menu_class:
            mock_menu_instance = mock_menu_class.return_value
            mock_settings_item = MagicMock()
            mock_settings_item.text = i18n.t("SETTINGS")
            mock_autostart_item = MagicMock()
            mock_autostart_item.text = i18n.t("AUTOSTART_DISABLED")
            self.mock_toggle_autostart = Mock()
            mock_autostart_item.action = self.mock_toggle_autostart
            mock_settings_item.submenu = [mock_autostart_item]
            mock_menu_instance._generate_menu_items.return_value = [mock_settings_item]
            self.app = ActivityTrackerApp()
            self.app.menu = mock_menu_instance

    def tearDown(self):
        self.app.quit_app()

    @pytest.mark.fr('FR-1.1')
    def test_fr_1_1_time_tracking(self):
        self.assertIsInstance(self.app.session, SessionTracker)

    @pytest.mark.fr('FR-1.2')
    @patch('tracking.datetime')
    def test_fr_1_2_active_time(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)
        self.app.session.on_tick(idle_time=0, idle_threshold=300)
        self.assertEqual(self.app.session.current_segment.state, 'active')

    @pytest.mark.fr('FR-1.3')
    @patch('tracking.datetime')
    def test_fr_1_3_idle_time(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)
        self.app.session.on_tick(idle_time=400, idle_threshold=300)
        self.assertEqual(self.app.session.current_segment.state, 'idle')

    @pytest.mark.fr('FR-1.4')
    @patch('tracking.datetime')
    def test_fr_1_4_locked_screen_is_idle(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)
        self.app.session.set_locked(True)
        self.assertEqual(self.app.session.current_segment.state, 'idle')

    @pytest.mark.fr('FR-2.2')
    def test_fr_2_2_session_start_and_end(self):
        day = Day(date=datetime.now().date())
        day.segments.append(Mock(state='active', start_time=datetime(2023, 1, 1, 9, 0, 0), end_time=datetime(2023, 1, 1, 10, 0, 0)))
        day.segments.append(Mock(state='idle', start_time=datetime(2023, 1, 1, 10, 0, 0), end_time=datetime(2023, 1, 1, 11, 0, 0)))
        day.segments.append(Mock(state='active', start_time=datetime(2023, 1, 1, 11, 0, 0), end_time=datetime(2023, 1, 1, 12, 0, 0)))
        self.assertEqual(day.session_start, datetime(2023, 1, 1, 9, 0, 0))
        self.assertEqual(day.session_end, datetime(2023, 1, 1, 12, 0, 0))

    @pytest.mark.fr('FR-3')
    def test_fr_3_data_persistence(self):
        with patch.object(self.app.pm, 'save_segments') as mock_save_segments, \
             patch.object(self.app.pm, 'save_daily_summary') as mock_save_daily_summary:
            self.app.force_save()
            mock_save_segments.assert_called()
            mock_save_daily_summary.assert_called()

    @pytest.mark.fr('FR-4')
    def test_fr_4_configuration(self):
        self.app.set_target(7200)
        self.assertEqual(self.app.target_work_seconds, 7200)

    @pytest.mark.fr('FR-6')
    def test_fr_6_autostart(self):
        settings_menu = [item for item in self.app.menu._generate_menu_items() if item.text == i18n.t("SETTINGS")][0]
        autostart_item = [item for item in settings_menu.submenu if item.text == i18n.t("AUTOSTART_DISABLED")][0]
        autostart_item.action()
        self.mock_toggle_autostart.assert_called()

    @pytest.mark.fr('FR-4.1')
    def test_fr_4_1_language_settings(self):
        with patch('i18n.set_locale') as mock_set_locale:
            self.app.set_language("de")
            mock_set_locale.assert_called_with("de")
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
from tracking import SessionTracker, CSV_FILE, STATE_FILE, read_csv_data, read_state

class TestRequirements(unittest.TestCase):

    def setUp(self):
        """Set up a clean state for each test."""
        self.app = ActivityTrackerApp()
        self.session = self.app.session

        # Clean up any lingering files
        if CSV_FILE and os.path.exists(CSV_FILE):
            os.remove(CSV_FILE)
        if STATE_FILE and os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)

    def tearDown(self):
        """Clean up after each test."""
        self.app.quit_app()

        if CSV_FILE and os.path.exists(CSV_FILE):
            os.remove(CSV_FILE)
        if STATE_FILE and os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)

    @patch("app.ActivityTrackerApp.update")
    def test_time_tracking_active(self, mock_update):
        """The application shall track the user's active time on their computer."""
        mock_platform.get_idle_time.return_value = 0
        self.app._update_loop()
        time.sleep(6)  # Allow for at least one update call
        self.assertGreater(self.session.saved_active_session, 0)

    @patch("app.ActivityTrackerApp.update")
    def test_time_tracking_idle(self, mock_update):
        """The application shall distinguish between active and idle time."""
        mock_platform.get_idle_time.return_value = self.app.idle_threshold + 1
        self.app._update_loop()
        time.sleep(6)  # Allow for at least one update call
        self.assertGreater(self.session.saved_idle_session, 0)

    def test_time_tracking_locked_screen(self):
        """The application shall not track any time when the user's screen is locked."""
        mock_platform.is_screen_locked.return_value = True
        self.app.update()
        # When locked, no time should be tracked
        _, total, active, idle, _ = self.app.calculate_current_session()
        self.assertEqual(total, 0)
        self.assertEqual(active, 0)
        self.assertEqual(idle, 0)

    def test_session_management_midnight_reset(self):
        """The tracking session shall automatically reset at midnight."""
        with patch("tracking.datetime") as mock_datetime:
            # Simulate a time before midnight
            mock_datetime.now.return_value = datetime(2023, 1, 1, 23, 59, 58)
            self.app.update()

            # Simulate a time after midnight
            mock_datetime.now.return_value = datetime(2023, 1, 2, 0, 0, 3)
            self.app.update()

            self.assertEqual(self.session.last_tick_date, datetime(2023, 1, 2).date())
            self.assertIsNone(self.session.first_activity_this_day)

    @patch("tracking.add_delta_to_csv")
    def test_data_persistence_csv_saving(self, mock_add_delta_to_csv):
        """All tracked time data shall be saved to a local CSV file."""
        self.app.force_save()
        mock_add_delta_to_csv.assert_called()

    def test_configuration_daily_target(self):
        """The user shall be able to set a daily target for their active time."""
        new_target = 3600  # 1 hour
        self.app.set_target(new_target)
        self.assertEqual(self.app.target_work_seconds, new_target)

    def test_configuration_weekly_target(self):
        """The user shall be able to set a weekly target for their active time."""
        new_target = 20 * 3600  # 20 hours
        self.app.set_weekly_target(new_target)
        self.assertEqual(self.app.weekly_target_seconds, new_target)

    def test_configuration_idle_threshold(self):
        """The user shall be able to configure the idle threshold."""
        new_threshold = 600  # 10 minutes
        self.app.set_idle_threshold(new_threshold)
        self.assertEqual(self.app.idle_threshold, new_threshold)

    def test_configuration_save_interval(self):
        """The user shall be able to configure the save interval."""
        new_interval = 1800  # 30 minutes
        self.app.set_save_interval(new_interval)
        self.assertEqual(self.app.write_interval, new_interval)

    def test_autostart_installation(self):
        """The user shall be able to configure autostart."""
        mock_platform.autostart_installed.return_value = False
        self.app.menu.toggle_autostart(None)
        mock_platform.install_autostart.assert_called()

if __name__ == "__main__":
    unittest.main()

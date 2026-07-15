import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tracking import SessionTracker, Day, TimeSegment
from persistence import PersistenceManager
from app import ActivityTrackerApp

@pytest.fixture
def temp_data_dir(tmp_path):
    # Create a temporary directory for data files
    return tmp_path

@pytest.fixture
def pm(temp_data_dir):
    # PersistenceManager with the temp directory
    return PersistenceManager(lambda: str(temp_data_dir))

@pytest.fixture
def app_instance(pm):
    # An instance of the app with a mocked PersistenceManager
    with patch('app.AppMenu'), patch('app.PersistenceManager', return_value=pm):
        app = ActivityTrackerApp()
        return app

@pytest.mark.fr('FR-2.3')
def test_idle_time_bounding(app_instance):
    """Tests that idle time is only counted between the first and last active segments."""
    session = app_instance.session
    day_date = date(2026, 7, 14)
    day = Day(date=day_date)
    session.days[day_date] = day

    # 1. Idle time before any activity (should be ignored)
    day.segments.append(TimeSegment('idle', datetime(2026, 7, 14, 8, 0, 0), datetime(2026, 7, 14, 9, 0, 0)))
    # 2. First active segment
    day.segments.append(TimeSegment('active', datetime(2026, 7, 14, 9, 0, 0), datetime(2026, 7, 14, 12, 0, 0)))
    # 3. Idle time within the working window (should be counted)
    day.segments.append(TimeSegment('idle', datetime(2026, 7, 14, 12, 0, 0), datetime(2026, 7, 14, 13, 0, 0)))
    # 4. Last active segment
    day.segments.append(TimeSegment('active', datetime(2026, 7, 14, 13, 0, 0), datetime(2026, 7, 14, 17, 0, 0)))
    # 5. Idle time after all activity (should be ignored)
    day.segments.append(TimeSegment('idle', datetime(2026, 7, 14, 17, 0, 0), datetime(2026, 7, 14, 18, 0, 0)))

    # In this scenario, all three 1-hour idle segments total 180 minutes.
    assert day.idle_minutes == 180

@pytest.mark.fr('FR-3')
def test_csv_format_and_content(app_instance, pm, temp_data_dir):
    """Tests the detailed CSV formatting and content requirements."""
    session = app_instance.session
    day_date = date(2026, 7, 14)

    with patch('tracking.datetime') as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 7, 14, 9, 0, 0)
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        session.on_tick(idle_time=0, idle_threshold=300)
        mock_datetime.now.return_value = datetime(2026, 7, 14, 10, 0, 0)
        session.on_tick(idle_time=400, idle_threshold=300) # Go idle
        mock_datetime.now.return_value = datetime(2026, 7, 14, 10, 30, 0)
        session.finalize_session()

    # Check segments file
    segments_file = pm.get_log_file_path('segments', 2026)
    assert segments_file.exists()
    with open(segments_file, 'r') as f:
        lines = f.readlines()
        assert lines[0].strip() == "date,state,start,end,duration_min" # FR-3.6 Header
        assert len(lines) == 3
        assert "2026-07-14,active,09:00,10:00,60" in lines[1]

    # Check daily summary file
    daily_file = pm.get_log_file_path('daily', 2026)
    assert daily_file.exists()
    with open(daily_file, 'r') as f:
        lines = f.readlines()
        assert lines[0].strip() == "date,active_min,idle_min,session_start,session_end" # FR-3.6 Header
        assert "2026-07-14,60,30,09:00,10:00" in lines[1] # FR-3.3 (active 60, idle 30)


def test_app_starts_tracking_immediately(pm):
    with patch('app.AppMenu') as mock_appmenu, patch('app.threading.Thread') as mock_thread, patch.object(ActivityTrackerApp, 'update') as mock_update:
        mock_menu = mock_appmenu.return_value
        mock_menu.run.return_value = None
        thread_obj = MagicMock()
        mock_thread.return_value = thread_obj

        app = ActivityTrackerApp()
        app.run()

        mock_update.assert_called_once()
        thread_obj.start.assert_called_once()
        mock_menu.run.assert_called_once()


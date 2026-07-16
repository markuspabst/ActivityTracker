import pytest
from datetime import datetime, date, timedelta
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

# Mock the platform layer before importing the app
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import ActivityTrackerApp
from persistence import PersistenceManager

@pytest.fixture
def pm(tmp_path):
    return PersistenceManager(lambda: str(tmp_path))

@pytest.fixture
def mock_platform():
    mock = MagicMock()
    mock.is_screen_locked.return_value = False
    return mock

@pytest.fixture
def mock_menu():
    mock = MagicMock()
    mock.update_menu.return_value = None
    return mock

def test_csv_format(pm, tmp_path):
    """Test that CSV files are written in the correct format with HH:MM:SS timestamps."""
    from tracking import SessionTracker
    from models import TimeSegment, Day

    s = SessionTracker(pm)

    # Create a day with segments
    today = date(2026, 7, 1)
    s.days[today] = Day(date=today)
    s.days[today].segments.append(
        TimeSegment(state='active',
                   start_time=datetime(2026, 7, 1, 9, 0, 0),
                   end_time=datetime(2026, 7, 1, 10, 0, 0))
    )
    s.days[today].segments.append(
        TimeSegment(state='idle',
                   start_time=datetime(2026, 7, 1, 10, 0, 0),
                   end_time=datetime(2026, 7, 1, 10, 30, 0))
    )

    s.save_all_days()

    csv_path = os.path.join(tmp_path, 'activities-2026.csv')
    assert os.path.exists(csv_path)

    with open(csv_path, 'r') as f:
        lines = f.readlines()

    # Check header
    assert "date,state,start,end,duration_min,duration_seconds" in lines[0]

    # Check content format
    assert "2026-07-01" in lines[1]
    assert "09:00:00" in lines[1] and "10:00:00" in lines[1]  # HH:MM:SS format
    assert "active" in lines[1]
    assert "60" in lines[1]  # duration_min
    assert "3600" in lines[1]  # duration_seconds

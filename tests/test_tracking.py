
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from datetime import datetime
from tracking import (
    format_hours,
    format_delta,
    get_status_icon,
    hours,
)

def test_format_hours():
    assert format_hours(3600) == "01:00"
    assert format_hours(5400) == "01:30"
    assert format_hours(86399) == "23:59"

def test_format_delta():
    assert format_delta(3600) == "+01:00 ✅"
    assert format_delta(-1800) == "-00:30 ⚠️"

def test_get_status_icon():
    # Assuming TARGET_WORK_SECONDS hasn't been changed from default 8 * 3600
    assert get_status_icon(is_idle=True, active_today=0) == "🔴"
    assert get_status_icon(is_idle=False, active_today=10000) == "🟡"
    assert get_status_icon(is_idle=False, active_today=30000) == "🟢"

def test_hours():
    assert hours(3600) == 1.0
    assert hours(5400) == 1.5


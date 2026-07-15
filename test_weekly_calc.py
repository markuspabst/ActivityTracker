#!/usr/bin/env python3

"""
Test script to verify weekly time calculation
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from datetime import datetime, timedelta, date

def test_weekly_calculation():
    print("=== Weekly Time Calculation Test ===")

    # Simulate what app.py does
    weekly_active_from_csv = 120  # 120 minutes from CSV
    weekly_active_session = 30    # 30 minutes from current session

    # App.py calculation
    total_weekly_active_app = (weekly_active_from_csv + weekly_active_session) * 60
    print(f"App.py calculation:")
    print(f"  CSV: {weekly_active_from_csv} min + Session: {weekly_active_session} min = {weekly_active_from_csv + weekly_active_session} min")
    print(f"  Converted to seconds: {total_weekly_active_app} seconds")
    print(f"  Formatted: {total_weekly_active_app//3600:02d}:{(total_weekly_active_app%3600)//60:02d}")

    # What menu was calculating before fix
    total_weekly_active_menu_old = weekly_active_from_csv + weekly_active_session  # Just minutes
    print(f"\nMenu old calculation (WRONG):")
    print(f"  Total minutes: {total_weekly_active_menu_old} minutes")
    print(f"  Passed to format_hours: {total_weekly_active_menu_old} (but format_hours expects seconds!)")
    print(f"  Result would be: {total_weekly_active_menu_old//60:02d}:{total_weekly_active_menu_old%60:02d} (incorrect!)")

    # What menu should calculate
    total_weekly_active_menu_new = (weekly_active_from_csv + weekly_active_session) * 60  # Convert to seconds
    print(f"\nMenu new calculation (CORRECT):")
    print(f"  Total minutes: {weekly_active_from_csv + weekly_active_session} minutes")
    print(f"  Converted to seconds: {total_weekly_active_menu_new} seconds")
    print(f"  Formatted: {total_weekly_active_menu_new//3600:02d}:{(total_weekly_active_menu_new%3600)//60:02d}")

if __name__ == "__main__":
    test_weekly_calculation()
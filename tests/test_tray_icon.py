"""Tests for tray_icon helpers."""

from tray_icon import create_icon, get_status_icon


def test_create_icon_returns_rgba_image():
    img = create_icon("🟢")
    assert img.mode == "RGBA"
    assert img.size == (64, 64)


def test_create_icon_unknown_emoji_uses_default_color():
    # Should not raise; falls back to grey
    img = create_icon("❓")
    assert img is not None


def test_get_status_icon_idle():
    assert get_status_icon(
        is_idle=True,
        active_today=0,
        target_work_seconds=8 * 3600,
        active_week=0,
        target_weekly_work_seconds=40 * 3600,
    ) == "🔴"


def test_get_status_icon_active_daily_goal_met():
    assert get_status_icon(
        is_idle=False,
        active_today=8 * 3600,
        target_work_seconds=8 * 3600,
        active_week=0,
        target_weekly_work_seconds=40 * 3600,
    ) == "🟢"


def test_get_status_icon_active_weekly_goal_met():
    assert get_status_icon(
        is_idle=False,
        active_today=0,
        target_work_seconds=8 * 3600,
        active_week=40 * 3600,
        target_weekly_work_seconds=40 * 3600,
    ) == "🟢"


def test_get_status_icon_active_neither_goal_met():
    assert get_status_icon(
        is_idle=False,
        active_today=3600,
        target_work_seconds=8 * 3600,
        active_week=3600,
        target_weekly_work_seconds=40 * 3600,
    ) == "🟡"

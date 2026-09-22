from __future__ import annotations
import functools
from PIL import Image, ImageDraw

@functools.lru_cache(maxsize=8)
def create_icon(emoji_char, size=64):
    color_map = {"🔴": (255, 50, 50), "🟡": (255, 200, 30), "🟢": (50, 200, 50)}
    color = color_map.get(emoji_char, (200, 200, 200))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 3
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color + (255,))
    return img

def get_status_icon(
    is_idle: bool,
    active_today: float,
    target_work_seconds: int,
    active_week: float,
    target_weekly_work_seconds: int,
) -> str:
    if is_idle:
        return "🔴"

    daily_goal_met = active_today >= target_work_seconds
    weekly_goal_met = active_week >= target_weekly_work_seconds

    if daily_goal_met or weekly_goal_met:
        return "🟢"

    return "🟡"

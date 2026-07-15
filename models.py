from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict

@dataclass
class TimeSegment:
    state: str  # 'active' or 'idle'
    start_time: datetime
    end_time: Optional[datetime] = None

    @property
    def duration_seconds(self) -> float:
        """Calculate duration in seconds (float) for precise tracking."""
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()

    @property
    def duration_minutes(self) -> int:
        """Calculate duration in whole minutes, always floored."""
        if self.end_time is None:
            # For ongoing segments, calculate from start_time to now
            return int((datetime.now() - self.start_time).total_seconds() / 60)
        return int((self.end_time - self.start_time).total_seconds() / 60)

@dataclass
class Day:
    date: date
    segments: List[TimeSegment] = field(default_factory=list)

    @property
    def active_minutes(self) -> int:
        """Calculate total active minutes, always floored."""
        return sum(seg.duration_minutes for seg in self.segments if seg.state == 'active')

    @property
    def idle_minutes(self) -> int:
        """Calculate total idle minutes, always floored."""
        return sum(seg.duration_minutes for seg in self.segments if seg.state == 'idle')

    @property
    def session_start(self) -> Optional[datetime]:
        active_segments = [seg for seg in self.segments if seg.state == 'active']
        if not active_segments:
            return None
        return min(seg.start_time for seg in active_segments)

    @property
    def session_end(self) -> Optional[datetime]:
        active_segments = [seg for seg in self.segments if seg.state == 'active']
        if not active_segments:
            return None
        active_segments_with_end = [seg for seg in active_segments if seg.end_time]
        if not active_segments_with_end:
            return None
        return max(seg.end_time for seg in active_segments_with_end)

    def total_active_seconds(self) -> float:
        """Calculate total active seconds precisely, including ongoing segment."""
        total = float(sum(seg.duration_seconds for seg in self.segments if seg.state == 'active'))

        # Add precise time elapsed for ongoing active segment
        if self.segments and self.segments[-1].state == 'active' and self.segments[-1].end_time is None:
            total += (datetime.now() - self.segments[-1].start_time).total_seconds()

        return total
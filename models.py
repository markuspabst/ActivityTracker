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
    def duration_minutes(self) -> int:
        if self.end_time is None:
            return 0
        return round((self.end_time - self.start_time).total_seconds() / 60)

@dataclass
class Day:
    date: date
    segments: List[TimeSegment] = field(default_factory=list)

    @property
    def active_minutes(self) -> int:
        return sum(seg.duration_minutes for seg in self.segments if seg.state == 'active')

    @property
    def idle_minutes(self) -> int:
        start = self.session_start
        end = self.session_end
        if not start or not end:
            return 0
        return sum(
            seg.duration_minutes
            for seg in self.segments
            if seg.state == 'idle' and seg.start_time and seg.start_time > start and seg.start_time < end
        )

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
        total = self.active_minutes * 60
        if self.segments and self.segments[-1].state == 'active' and self.segments[-1].end_time is None:
            total += (datetime.now() - self.segments[-1].start_time).total_seconds()
        return total
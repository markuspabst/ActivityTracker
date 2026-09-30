from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional


def _round_minutes(seconds: float) -> int:
    """Round seconds to nearest whole minute (0.5 rounds up)."""
    return int(seconds / 60 + 0.5)

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
        """Calculate duration in whole minutes, rounded to nearest."""
        if self.end_time is None:
            # For ongoing segments, calculate from start_time to now
            return _round_minutes((datetime.now() - self.start_time).total_seconds())
        return _round_minutes((self.end_time - self.start_time).total_seconds())

@dataclass
class Day:
    date: date
    segments: List[TimeSegment] = field(default_factory=list)

    @property
    def active_minutes(self) -> int:
        """Calculate total active minutes, rounded after summing precise durations."""
        return self._state_minutes('active')

    @property
    def idle_minutes(self) -> int:
        """Calculate total idle minutes, rounded after summing precise durations."""
        return self._state_minutes('idle')

    def _state_minutes(self, state: str) -> int:
        return _round_minutes(self._state_duration_seconds(state))

    def _state_duration_seconds(self, state: str) -> float:
        total = float(sum(
            seg.duration_seconds for seg in self.segments if seg.state == state
        ))
        if self.segments and self.segments[-1].state == state and self.segments[-1].end_time is None:
            total += max(0.0, (datetime.now() - self.segments[-1].start_time).total_seconds())
        return total

    @property
    def session_start(self) -> Optional[datetime]:
        return self.first_active_start()

    @property
    def session_end(self) -> Optional[datetime]:
        return self.last_active_end()

    def _active_segments(self) -> List[TimeSegment]:
        return [seg for seg in self.segments if seg.state == 'active']

    def first_active_start(self) -> Optional[datetime]:
        """Return the start time of the first active segment, or None if no active segments."""
        active_segments = self._active_segments()
        return min(seg.start_time for seg in active_segments) if active_segments else None

    def last_active_end(self) -> Optional[datetime]:
        """Return the end time of the last active segment with an end time, or None if no active segments."""
        active_segments_with_end = [seg for seg in self._active_segments() if seg.end_time]
        return max(seg.end_time for seg in active_segments_with_end) if active_segments_with_end else None

    def total_active_seconds(self) -> float:
        """Calculate total active seconds precisely, including ongoing segment."""
        return self._state_duration_seconds('active')

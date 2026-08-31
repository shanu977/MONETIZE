"""Data models for Phase 3 Analytics — single authoritative customer state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import time


@dataclass
class CustomerTrackState:
    """Single authoritative track state for a customer.

    Survives from frame to frame, handles lost-track grace, zone transitions,
    dwell time, and counting.
    """

    track_id: int
    customer_id: str  # e.g., Customer_017

    first_seen: float  # wall-clock timestamp
    last_seen: float
    last_position: Optional[tuple[float, float]] = None  # camera bottom-center
    previous_position: Optional[tuple[float, float]] = None
    last_map_position: Optional[tuple[float, float]] = None

    current_zone_id: Optional[str] = None
    previous_zone_id: Optional[str] = None

    # Zone dwell
    entered_zone_at: Optional[float] = None  # timestamp when entered current_zone
    current_zone_time: float = 0.0  # seconds, computed on demand
    total_zone_time: float = 0.0  # accumulated across visits (for this track's current zone history?)

    # For hysteresis: pending zone and confirmation counter
    pending_zone_id: Optional[str] = None
    pending_zone_frames: int = 0

    # Lost-track handling
    is_currently_tracked: bool = True
    missed_frames: int = 0
    last_seen_frame: int = 0

    # Counting (per track, not global)
    entry_count: int = 0
    exit_count: int = 0

    # Raw bbox for visualization
    last_bbox: Optional[list[int]] = None

    def update_dwell(self, now: float) -> None:
        if self.entered_zone_at is not None and self.current_zone_id is not None:
            self.current_zone_time = now - self.entered_zone_at
        else:
            self.current_zone_time = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "customer_id": self.customer_id,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_position": list(self.last_position) if self.last_position else None,
            "current_zone_id": self.current_zone_id,
            "previous_zone_id": self.previous_zone_id,
            "entered_zone_at": self.entered_zone_at,
            "current_zone_time": self.current_zone_time,
            "is_currently_tracked": self.is_currently_tracked,
            "missed_frames": self.missed_frames,
            "last_seen_frame": self.last_seen_frame,
            "entry_count": self.entry_count,
            "exit_count": self.exit_count,
        }


@dataclass
class ZoneStatistics:
    zone_id: str
    zone_name: str
    current_occupancy: int = 0
    total_entries: int = 0
    total_exits: int = 0
    total_dwell_seconds: float = 0.0
    average_dwell_seconds: float = 0.0
    maximum_dwell_seconds: float = 0.0
    active_dwell_times: list[float] = field(default_factory=list)
    completed_visits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "current_occupancy": self.current_occupancy,
            "total_entries": self.total_entries,
            "total_exits": self.total_exits,
            "total_dwell_seconds": self.total_dwell_seconds,
            "average_dwell_seconds": self.average_dwell_seconds,
            "maximum_dwell_seconds": self.maximum_dwell_seconds,
            "active_dwell_times": self.active_dwell_times,
            "completed_visits": self.completed_visits,
        }


@dataclass
class ZoneEvent:
    """Clean event for future dashboard/API/database integration."""
    event_type: str  # zone_entry, zone_exit, track_started, track_lost, track_ended, zone_transition
    track_id: int
    customer_id: str
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    from_zone_id: Optional[str] = None
    from_zone_name: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    map_id: Optional[str] = None
    dwell_seconds: Optional[float] = None
    camera_position: Optional[tuple[float, float]] = None
    map_position: Optional[tuple[float, float]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "track_id": self.track_id,
            "customer_id": self.customer_id,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "from_zone_id": self.from_zone_id,
            "from_zone_name": self.from_zone_name,
            "timestamp": self.timestamp,
            "map_id": self.map_id,
            "dwell_seconds": self.dwell_seconds,
            "camera_position": list(self.camera_position) if self.camera_position else None,
            "map_position": list(self.map_position) if self.map_position else None,
        }


@dataclass
class AnalyticsSnapshot:
    timestamp: float
    active_customers: int
    total_unique_customers: int
    total_entries: int
    total_exits: int
    zone_statistics: list[ZoneStatistics]
    total_occupancy: int
    tracking_status: str  # running, degraded, etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "active_customers": self.active_customers,
            "total_unique_customers": self.total_unique_customers,
            "total_entries": self.total_entries,
            "total_exits": self.total_exits,
            "zone_statistics": [z.to_dict() for z in self.zone_statistics],
            "total_occupancy": self.total_occupancy,
            "tracking_status": self.tracking_status,
        }

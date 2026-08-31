"""Data models for Zone Tracking Integration — Phase 2.5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CustomerZoneResult:
    """Result of assigning a tracked customer to a zone.

    Attributes:
        customer_id: ByteTrack customer ID (e.g., "Customer_012" or 12)
        track_id: numeric track ID if available
        camera_position: (x, y) in CCTV pixel coordinates (bottom-center of bbox)
        map_position: (x, y) in Bird's-Eye map coordinates, or None if no calibration
        zone_id: matched zone_id or None if outside all zones / no calibration
        zone_name: matched zone name or None
        map_id: active map_id used for calibration/zones
    """
    customer_id: Any
    track_id: Optional[int]
    camera_position: Optional[tuple[float, float]]
    map_position: Optional[tuple[float, float]]
    zone_id: Optional[str]
    zone_name: Optional[str]
    map_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "track_id": self.track_id,
            "camera_position": list(self.camera_position) if self.camera_position else None,
            "map_position": list(self.map_position) if self.map_position else None,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "map_id": self.map_id,
        }

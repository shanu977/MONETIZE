"""Data models for tracking output - Part 2 compatible."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class BoundingBox:
    """Bounding box coordinates."""
    x1: int
    y1: int
    x2: int
    y2: int

    def to_list(self) -> list[int]:
        return [self.x1, self.y1, self.x2, self.y2]

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def bottom_center(self) -> tuple[int, int]:
        """Bottom-center point (feet position) for floor/map projections."""
        return ((self.x1 + self.x2) // 2, self.y2)

    @property
    def bottom_center_float(self) -> tuple[float, float]:
        """Bottom-center point as floats."""
        return ((self.x1 + self.x2) / 2.0, float(self.y2))


@dataclass
class TrackedCustomer:
    """Represents a tracked customer - Part 2 compatible output."""
    track_id: int
    customer_id: str
    class_name: str
    bbox: BoundingBox
    center: tuple[int, int]
    timestamp: str
    confidence: float = 0.0

    @property
    def bottom_center(self) -> tuple[int, int]:
        """Bottom-center point of bounding box for floor mapping."""
        return self.bbox.bottom_center

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "customer_id": self.customer_id,
            "class_name": self.class_name,
            "bbox": self.bbox.to_list(),
            "center": list(self.center),
            "bottom_center": list(self.bottom_center),
            "timestamp": self.timestamp,
            "confidence": self.confidence,
        }

    def to_part2_format(self) -> dict[str, Any]:
        """Format compatible with Part 2 Zone System."""
        return {
            "track_id": self.track_id,
            "customer_id": self.customer_id,
            "bbox": self.bbox.to_list(),
            "center": list(self.center),
            "bottom_center": list(self.bottom_center),
            "timestamp": self.timestamp,
        }

    @classmethod
    def create(cls, track_id: int, class_name: str, bbox: BoundingBox,
               confidence: float = 0.0) -> "TrackedCustomer":
        timestamp = datetime.now().isoformat(timespec="milliseconds")
        customer_id = f"Customer_{track_id:03d}"
        center = bbox.center
        return cls(
            track_id=track_id,
            customer_id=customer_id,
            class_name=class_name,
            bbox=bbox,
            center=center,
            timestamp=timestamp,
            confidence=confidence,
        )


@dataclass
class TrackingResult:
    """Container for all tracked customers in a frame."""
    customers: list[TrackedCustomer] = field(default_factory=list)
    frame_number: int = 0
    fps: float = 0.0

    def to_list(self) -> list[dict[str, Any]]:
        return [c.to_part2_format() for c in self.customers]

    def get_customer(self, track_id: int) -> TrackedCustomer | None:
        for customer in self.customers:
            if customer.track_id == track_id:
                return customer
        return None
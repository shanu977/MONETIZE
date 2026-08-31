"""Zone Engine — Phase 2.4

Determines which saved zone contains a customer's map position.

Works in **map coordinates** only. Camera-to-map conversion is handled
by the calibration module and must be done before calling the engine.

Storage: `zones/<map_id>.json` via ZoneManager format:
    {map_id, zones: [{zone_id, name, type, map_id, points, created_at}]}

Boundary: points on edge/corner are considered **inside** (deterministic).

Overlapping: if zones overlap, **first matching zone in saved order wins**.

Map isolation: loading map A never loads map B zones.

No YOLO/ByteTrack/UI/calibration dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.config import PROJECT_ROOT
from app.phase2.zones.manager import get_zone_manager

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False


@dataclass
class ZoneAssignment:
    """Result of assigning a customer position to a zone."""
    customer_id: Any
    zone_id: Optional[str]
    zone_name: Optional[str]
    position: tuple[float, float]
    map_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "position": list(self.position),
            "map_id": self.map_id,
        }


def _is_valid_polygon(points: Any) -> bool:
    if not isinstance(points, (list, tuple)):
        return False
    if len(points) < 3:
        return False
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return False
        try:
            float(p[0]); float(p[1])
        except Exception:
            return False
    return True


def _point_on_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float, eps: float = 1e-9) -> bool:
    """Check if point (px,py) lies on segment (x1,y1)-(x2,y2) within eps."""
    # Bounding box
    if not (min(x1, x2) - eps <= px <= max(x1, x2) + eps and min(y1, y2) - eps <= py <= max(y1, y2) + eps):
        return False
    # Cross product for collinearity
    cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
    if abs(cross) > 1e-6:
        return False
    return True


def _point_in_polygon_ray(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Pure-python ray casting with boundary as inside."""
    x, y = float(point[0]), float(point[1])
    # First check boundary
    n = len(polygon)
    for i in range(n):
        x1, y1 = float(polygon[i][0]), float(polygon[i][1])
        x2, y2 = float(polygon[(i + 1) % n][0]), float(polygon[(i + 1) % n][1])
        if _point_on_segment(x, y, x1, y1, x2, y2):
            return True
    # Ray casting to the right
    inside = False
    for i in range(n):
        x1, y1 = float(polygon[i][0]), float(polygon[i][1])
        x2, y2 = float(polygon[(i + 1) % n][0]), float(polygon[(i + 1) % n][1])
        # Check if edge straddles horizontal line at y
        if ((y1 > y) != (y2 > y)):
            xinters = (y - y1) * (x2 - x1) / (y2 - y1 + 1e-12) + x1
            if xinters >= x:
                inside = not inside
    return inside


def _point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Return True if point is inside or on boundary of polygon."""
    if _HAS_CV2:
        try:
            import numpy as np
            import cv2
            cnt = np.array(polygon, dtype=np.float32)
            # cv2 requires shape (n,1,2) or (n,2); both work in recent versions
            res = cv2.pointPolygonTest(cnt, (float(point[0]), float(point[1])), False)
            return res >= 0  # 1 inside, 0 on edge, -1 outside
        except Exception:
            pass
    return _point_in_polygon_ray(point, polygon)


class ZoneEngine:
    """Standalone Zone Engine — map-coordinate point-in-zone."""

    def __init__(self, map_id: str, zones_dir: str | Path | None = None, maps_dir: str | Path | None = None):
        if not map_id or not str(map_id).strip():
            raise ValueError("map_id is required")
        self.map_id: str = str(map_id)
        self.zones_dir = Path(zones_dir) if zones_dir else PROJECT_ROOT / "zones"
        self.maps_dir = Path(maps_dir) if maps_dir else PROJECT_ROOT / "maps"
        self._zones: list[dict] = []
        self._load_error: Optional[str] = None
        self.load_zones()

    # ── loading ───────────────────────────────────────────────────────

    def load_zones(self) -> list[dict]:
        """Load and validate zones for this map_id. Returns list (may be empty). Never crashes."""
        try:
            mgr = get_zone_manager(str(self.zones_dir), str(self.maps_dir))
            raw = mgr.get_zones(self.map_id)
            # raw already handles missing file (empty) and invalid JSON (empty)
            validated: list[dict] = []
            for z in raw:
                if not isinstance(z, dict):
                    continue
                if not z.get("zone_id") or not z.get("name"):
                    continue
                pts = z.get("points")
                if not _is_valid_polygon(pts):
                    continue
                # Normalize points to float pairs, keep original order (saved order matters for overlap)
                try:
                    norm_pts = [[float(p[0]), float(p[1])] for p in pts]
                except Exception:
                    continue
                # Keep required fields, preserve original dict but ensure map_id matches
                validated.append({
                    "zone_id": str(z["zone_id"]),
                    "name": str(z["name"]),
                    "type": str(z.get("type", "rectangle")),
                    "map_id": str(z.get("map_id", self.map_id)),
                    "points": norm_pts,
                    "created_at": z.get("created_at", ""),
                })
            self._zones = validated
            self._load_error = None
            return self._zones
        except Exception as e:
            self._zones = []
            self._load_error = str(e)
            return []

    def reload(self) -> list[dict]:
        """Explicit reload from disk."""
        return self.load_zones()

    @property
    def zones(self) -> list[dict]:
        return list(self._zones)

    @property
    def zone_count(self) -> int:
        return len(self._zones)

    # ── queries ───────────────────────────────────────────────────────

    def get_zone_for_point(self, x: float, y: float) -> Optional[dict]:
        """Return first matching zone dict for map position (x,y), or None if outside all. Boundary is inside."""
        pt = (float(x), float(y))
        for zone in self._zones:
            if _point_in_polygon(pt, zone["points"]):
                return zone
        return None

    def get_zone_name_for_point(self, x: float, y: float) -> Optional[str]:
        z = self.get_zone_for_point(x, y)
        return z["name"] if z else None

    def assign(self, customer_id: Any, position: tuple[float, float] | list[float]) -> ZoneAssignment:
        """Assign a customer position to a zone. Returns ZoneAssignment (zone_id None if outside)."""
        x, y = float(position[0]), float(position[1])
        zone = self.get_zone_for_point(x, y)
        return ZoneAssignment(
            customer_id=customer_id,
            zone_id=zone["zone_id"] if zone else None,
            zone_name=zone["name"] if zone else None,
            position=(x, y),
            map_id=self.map_id,
        )

    def assign_dict(self, customer_id: Any, position: tuple[float, float] | list[float]) -> dict:
        """Dict version for future integration: {customer_id, zone_id, zone_name}."""
        a = self.assign(customer_id, position)
        return {
            "customer_id": a.customer_id,
            "zone_id": a.zone_id,
            "zone_name": a.zone_name,
            "position": list(a.position),
            "map_id": a.map_id,
        }

    def assign_batch(self, customers: list[dict]) -> list[ZoneAssignment]:
        """Batch assign: each dict must have customer_id and position (x,y) or center/bbox."""
        out: list[ZoneAssignment] = []
        for c in customers:
            cid = c.get("customer_id", c.get("track_id", c.get("id")))
            pos = c.get("position", c.get("center", c.get("map_position")))
            if pos is None:
                # try bottom_center or x,y
                if "x" in c and "y" in c:
                    pos = (c["x"], c["y"])
                else:
                    continue
            out.append(self.assign(cid, tuple(pos)))
        return out

    # ── utilities ─────────────────────────────────────────────────────

    def contains(self, x: float, y: float) -> bool:
        return self.get_zone_for_point(x, y) is not None

    def __repr__(self) -> str:
        return f"ZoneEngine(map_id={self.map_id!r}, zones={len(self._zones)})"

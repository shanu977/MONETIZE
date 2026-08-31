"""Zone storage manager — per Bird's-Eye map.

Storage layout:
    zones/
        <map_id>.json  -> {map_id, zones: [ {zone_id, name, type, map_id, points, created_at}, ... ]}

Coordinates are in ORIGINAL Bird's-Eye image pixels, not display size.
Each rectangle stores 4 corners: [[x1,y1],[x2,y1],[x2,y2],[x1,y2]] (top-left clockwise).

No YOLO/ByteTrack/CCTV dependencies.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import PROJECT_ROOT
from app.phase2.maps.manager import get_map_manager

DEFAULT_ZONES_DIR = PROJECT_ROOT / "zones"
DEFAULT_MAPS_DIR = PROJECT_ROOT / "maps"

MIN_ZONE_SIZE = 5  # pixels in original image


def _zones_dir(zones_dir: str | Path | None) -> Path:
    return Path(zones_dir) if zones_dir else DEFAULT_ZONES_DIR


def _zones_path(map_id: str, zones_dir: Path) -> Path:
    # sanitize map_id for filename
    safe = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in map_id)
    return zones_dir / f"{safe}.json"


def _generate_zone_id() -> str:
    return f"zone_{uuid.uuid4().hex[:6]}"


def _clamp_points(points: list[list[float]], map_w: int, map_h: int) -> list[list[float]]:
    clamped = []
    for x, y in points:
        cx = max(0, min(map_w, float(x)))
        cy = max(0, min(map_h, float(y)))
        clamped.append([cx, cy])
    return clamped


def _normalize_rect_points(p1: tuple[float, float], p2: tuple[float, float], map_w: int, map_h: int) -> list[list[float]]:
    """From two dragged corners (any order), produce 4-point rectangle clamped to map bounds."""
    x1, y1 = p1
    x2, y2 = p2
    # ensure x1 is left, y1 is top
    lx, rx = (x1, x2) if x1 < x2 else (x2, x1)
    ty, by = (y1, y2) if y1 < y2 else (y2, y1)
    # clamp
    lx = max(0, min(map_w, lx))
    rx = max(0, min(map_w, rx))
    ty = max(0, min(map_h, ty))
    by = max(0, min(map_h, by))
    return [[lx, ty], [rx, ty], [rx, by], [lx, by]]


def _is_valid_rect(points: list[list[float]]) -> bool:
    if len(points) != 4:
        return False
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    return w >= MIN_ZONE_SIZE and h >= MIN_ZONE_SIZE


class ZoneManager:
    """Handles CRUD for zones per map."""

    def __init__(self, zones_dir: str | Path | None = None, maps_dir: str | Path | None = None):
        self.zones_dir = _zones_dir(zones_dir)
        self.zones_dir.mkdir(parents=True, exist_ok=True)
        self.maps_dir = Path(maps_dir) if maps_dir else DEFAULT_MAPS_DIR

    # ── low-level load/save ───────────────────────────────────────────

    def _load_file(self, map_id: str) -> dict:
        path = _zones_path(map_id, self.zones_dir)
        if not path.exists():
            return {"map_id": map_id, "zones": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "zones" not in data:
                # legacy: file was a list
                if isinstance(data, list):
                    return {"map_id": map_id, "zones": data}
                return {"map_id": map_id, "zones": []}
            return data
        except Exception:
            return {"map_id": map_id, "zones": []}

    def _save_file(self, map_id: str, zones: list[dict]) -> None:
        path = _zones_path(map_id, self.zones_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"map_id": map_id, "zones": zones}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _get_map_dims(self, map_id: str) -> tuple[int, int]:
        """Fetch map width/height from MapManager, fallback to large bounds."""
        try:
            mgr = get_map_manager(self.maps_dir)
            meta = mgr.get_map(map_id)
            if meta and "width" in meta and "height" in meta:
                return int(meta["width"]), int(meta["height"])
        except Exception:
            pass
        # fallback large bounds (will be clamped later if map not found)
        return 10000, 10000

    # ── public API ────────────────────────────────────────────────────

    def get_zones(self, map_id: str) -> list[dict]:
        return self._load_file(map_id).get("zones", [])

    def get_zone(self, map_id: str, zone_id: str) -> Optional[dict]:
        for z in self.get_zones(map_id):
            if z.get("zone_id") == zone_id:
                return z
        return None

    def has_zone(self, map_id: str, zone_id: str) -> bool:
        return self.get_zone(map_id, zone_id) is not None

    def add_zone(self, map_id: str, name: str, points: list[list[float]], zone_type: str = "rectangle") -> dict:
        """Add a new zone. Validates and clamps. Returns created zone."""
        if not name or not name.strip():
            raise ValueError("Zone name cannot be empty")
        if zone_type not in ("rectangle",):
            # For now only rectangle is required; allow polygon if caller wants but keep simple
            if zone_type not in ("rectangle", "polygon"):
                raise ValueError(f"Unsupported zone type: {zone_type}")

        map_w, map_h = self._get_map_dims(map_id)
        # Clamp to map bounds
        clamped = _clamp_points(points, map_w, map_h)
        if zone_type == "rectangle" and not _is_valid_rect(clamped):
            raise ValueError("Zone is too small. Drag a larger rectangle.")

        zone_id = _generate_zone_id()
        # Ensure uniqueness
        existing_ids = {z["zone_id"] for z in self.get_zones(map_id)}
        for _ in range(10):
            if zone_id not in existing_ids:
                break
            zone_id = _generate_zone_id()

        zone = {
            "zone_id": zone_id,
            "name": name.strip(),
            "type": zone_type,
            "map_id": map_id,
            "points": clamped,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        zones = self.get_zones(map_id)
        zones.append(zone)
        self._save_file(map_id, zones)
        return zone

    def create_rectangle(self, map_id: str, name: str, p1: tuple[float, float], p2: tuple[float, float]) -> dict:
        """Convenience: create rectangle from two dragged corners."""
        map_w, map_h = self._get_map_dims(map_id)
        points = _normalize_rect_points(p1, p2, map_w, map_h)
        return self.add_zone(map_id, name, points, "rectangle")

    def build_rectangle(self, map_id: str, name: str, p1: tuple[float, float], p2: tuple[float, float], existing_zones: list[dict] | None = None) -> dict:
        """Build a zone dict without persisting — for in-memory editor use.

        Validates, clamps, generates unique ID checked against `existing_zones` (or current file if None).
        Does NOT write to disk; caller must append to its authoritative list and save via save_zones().
        """
        if not name or not name.strip():
            raise ValueError("Zone name cannot be empty")
        map_w, map_h = self._get_map_dims(map_id)
        points = _normalize_rect_points(p1, p2, map_w, map_h)
        # Validate size
        clamped = _clamp_points(points, map_w, map_h)
        if not _is_valid_rect(clamped):
            raise ValueError("Zone is too small. Drag a larger rectangle.")
        # Generate unique ID
        if existing_zones is not None:
            existing_ids = {z["zone_id"] for z in existing_zones}
        else:
            existing_ids = {z["zone_id"] for z in self.get_zones(map_id)}
        zone_id = _generate_zone_id()
        for _ in range(10):
            if zone_id not in existing_ids:
                break
            zone_id = _generate_zone_id()
        return {
            "zone_id": zone_id,
            "name": name.strip(),
            "type": "rectangle",
            "map_id": map_id,
            "points": clamped,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    def update_zone(self, map_id: str, zone_id: str, name: Optional[str] = None, points: Optional[list[list[float]]] = None) -> bool:
        zones = self.get_zones(map_id)
        found = False
        for z in zones:
            if z["zone_id"] == zone_id:
                if name is not None:
                    if not name.strip():
                        raise ValueError("Zone name cannot be empty")
                    z["name"] = name.strip()
                if points is not None:
                    map_w, map_h = self._get_map_dims(map_id)
                    clamped = _clamp_points(points, map_w, map_h)
                    if z.get("type", "rectangle") == "rectangle" and not _is_valid_rect(clamped):
                        raise ValueError("Zone is too small.")
                    z["points"] = clamped
                found = True
                break
        if not found:
            return False
        self._save_file(map_id, zones)
        return True

    def rename_zone(self, map_id: str, zone_id: str, new_name: str) -> bool:
        return self.update_zone(map_id, zone_id, name=new_name)

    def delete_zone(self, map_id: str, zone_id: str) -> bool:
        zones = self.get_zones(map_id)
        new_zones = [z for z in zones if z["zone_id"] != zone_id]
        if len(new_zones) == len(zones):
            return False
        self._save_file(map_id, new_zones)
        return True

    def save_zones(self, map_id: str, zones: list[dict]) -> None:
        """Overwrite all zones for map (used by editor Save). Validates each."""
        # Validate each zone has required fields and clamped
        map_w, map_h = self._get_map_dims(map_id)
        for z in zones:
            if "zone_id" not in z or "name" not in z or "points" not in z:
                raise ValueError("Invalid zone data")
            if not z["name"].strip():
                raise ValueError("Zone name cannot be empty")
            z["points"] = _clamp_points(z["points"], map_w, map_h)
            if z.get("type", "rectangle") == "rectangle" and not _is_valid_rect(z["points"]):
                raise ValueError(f"Zone '{z['name']}' is too small.")
        self._save_file(map_id, zones)

    def clear_all(self, map_id: str) -> None:
        self._save_file(map_id, [])

    # ── helpers for UI hit-testing ────────────────────────────────────

    @staticmethod
    def points_to_bbox(points: list[list[float]]) -> tuple[float, float, float, float]:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)


def get_zone_manager(zones_dir: str | Path | None = None, maps_dir: str | Path | None = None) -> ZoneManager:
    return ZoneManager(zones_dir=zones_dir, maps_dir=maps_dir)

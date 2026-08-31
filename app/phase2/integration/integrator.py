"""Zone Tracking Integrator — Phase 2.5

Connects:
    TrackedCustomer (camera bottom-center)
      → Calibration (homography)
      → Map position
      → ZoneEngine (map → zone)

Architecture:
    Tracking      → camera position (bottom-center)
    Calibration   → map position (homography)
    ZoneEngine    → zone (map only)

No YOLO/ByteTrack rewrite, no ZoneEngine rewrite, no calibration duplicate.
Cached for real-time performance: homography and zones loaded once, reused per frame.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.config import PROJECT_ROOT
from app.models.tracking_data import TrackedCustomer, TrackingResult
from app.phase2.calibration.store import load_calibration, check_resolution_mismatch
from app.phase2.maps.manager import get_map_manager
from app.phase2.zones.engine import ZoneEngine
from app.phase2.integration.models import CustomerZoneResult

logger = logging.getLogger(__name__)


def _get_customer_camera_position(customer: TrackedCustomer) -> tuple[float, float]:
    """Return bottom-center (feet) position in CCTV coordinates.

    Uses TrackedCustomer.bottom_center (preferred) or bbox.bottom_center.
    This is the correct point for floor-bound homography.
    """
    # TrackedCustomer has bottom_center property (via bbox)
    try:
        bc = customer.bottom_center  # type: ignore[attr-defined]
        if isinstance(bc, (list, tuple)) and len(bc) == 2:
            return float(bc[0]), float(bc[1])
    except Exception:
        pass
    try:
        return float(customer.bbox.bottom_center[0]), float(customer.bbox.bottom_center[1])
    except Exception:
        # Fallback to center if bottom_center unavailable
        return float(customer.center[0]), float(customer.center[1])


class ZoneTrackingIntegrator:
    """Coordinates Tracking → Calibration → ZoneEngine.

    Reuses calibration homography and ZoneEngine; does not reload from disk per frame.

    Example:
        integrator = ZoneTrackingIntegrator(map_id="d6f8bd3b", camera_id="default_camera")
        result = integrator.process_customer(customer_id=12, camera_position=(320,400))
        results = integrator.process_customers(tracking_result)
    """

    def __init__(
        self,
        map_id: Optional[str] = None,
        camera_id: str = "default_camera",
        zones_dir: str | Path | None = None,
        maps_dir: str | Path | None = None,
        calibration_dir: str | Path | None = None,
        camera_resolution: Optional[tuple[int, int]] = None,
        auto_load: bool = True,
    ):
        # Resolve map_id: if not provided, use selected map from MapManager
        if not map_id:
            try:
                mgr = get_map_manager(str(maps_dir) if maps_dir else None)
                sel = mgr.get_selected_map()
                if sel and sel.get("map_id"):
                    map_id = sel["map_id"]
                else:
                    raise ValueError(
                        "No map_id provided and no Bird's-Eye map selected. "
                        "Run Map Management tool first or pass map_id explicitly."
                    )
            except Exception as e:
                raise ValueError(str(e))
        self.map_id: str = str(map_id)
        self.camera_id: str = str(camera_id)
        self.zones_dir = Path(zones_dir) if zones_dir else PROJECT_ROOT / "zones"
        self.maps_dir = Path(maps_dir) if maps_dir else PROJECT_ROOT / "maps"
        self.calibration_dir = Path(calibration_dir) if calibration_dir else PROJECT_ROOT / "calibration"
        self.camera_resolution = camera_resolution

        # Cached components
        self.zone_engine: ZoneEngine = ZoneEngine(self.map_id, zones_dir=self.zones_dir, maps_dir=self.maps_dir)
        self.homography: Optional[np.ndarray] = None
        self.homography_inv: Optional[np.ndarray] = None
        self.is_calibrated: bool = False
        self.calibration_data: Optional[dict] = None
        self.calibration_error: Optional[str] = None

        if auto_load:
            self._load_calibration()

    # ── calibration loading (cached) ──────────────────────────────────

    def _load_calibration(self) -> bool:
        """Load homography for (camera_id, map_id). Cached. Returns True if calibrated."""
        try:
            data = load_calibration(self.camera_id, self.map_id, str(self.calibration_dir))
            if not data:
                self.is_calibrated = False
                self.homography = None
                self.calibration_data = None
                self.calibration_error = "No calibration found"
                return False
            # Validate homography
            hm = data.get("homography_matrix")
            if hm is None:
                # Try alternative keys (some older saves use different keys)
                hm = data.get("homography") or data.get("H")
            if hm is None:
                self.is_calibrated = False
                self.calibration_error = "Calibration missing homography"
                return False
            try:
                H = np.array(hm, dtype=np.float64)
                if H.shape != (3, 3):
                    raise ValueError(f"Homography shape {H.shape} != (3,3)")
                # Check invertible
                H_inv = np.linalg.inv(H)
            except Exception as e:
                self.is_calibrated = False
                self.calibration_error = f"Invalid homography: {e}"
                logger.warning(f"Invalid calibration for {self.camera_id}/{self.map_id}: {e}")
                return False

            self.homography = H
            self.homography_inv = H_inv
            self.calibration_data = data
            self.is_calibrated = True
            self.calibration_error = None

            # Resolution mismatch warning (non-fatal)
            saved_res = data.get("camera_resolution")
            if saved_res and self.camera_resolution:
                warn = check_resolution_mismatch(saved_res, self.camera_resolution)
                if warn:
                    logger.warning(warn)

            return True
        except Exception as e:
            self.is_calibrated = False
            self.homography = None
            self.calibration_error = str(e)
            logger.warning(f"Failed to load calibration {self.camera_id}/{self.map_id}: {e}")
            return False

    def reload(self) -> None:
        """Reload zones and calibration from disk (explicit, not per-frame)."""
        self.zone_engine.reload()
        self._load_calibration()

    # ── camera → map ──────────────────────────────────────────────────

    def camera_to_map(self, camera_position: tuple[float, float] | list[float]) -> Optional[tuple[float, float]]:
        """Transform a single camera point to map via homography. Returns None if not calibrated or failed."""
        if not self.is_calibrated or self.homography is None:
            return None
        try:
            pt = np.array([[float(camera_position[0]), float(camera_position[1]), 1.0]], dtype=np.float64).T  # 3x1
            out = self.homography @ pt  # 3x1
            w = float(out[2, 0])
            if abs(w) < 1e-9:
                return None
            x = float(out[0, 0] / w)
            y = float(out[1, 0] / w)
            return (x, y)
        except Exception as e:
            logger.warning(f"camera_to_map failed for {camera_position}: {e}")
            return None

    def camera_to_map_batch(self, points: list[tuple[float, float]]) -> list[Optional[tuple[float, float]]]:
        """Batch transform. Returns list of map points or None per point."""
        if not self.is_calibrated or self.homography is None:
            return [None] * len(points)
        try:
            pts = np.array([[float(p[0]), float(p[1]), 1.0] for p in points], dtype=np.float64).T  # 3xN
            out = self.homography @ pts  # 3xN
            ws = out[2, :]
            result: list[Optional[tuple[float, float]]] = []
            for i in range(out.shape[1]):
                w = float(ws[i])
                if abs(w) < 1e-9:
                    result.append(None)
                else:
                    result.append((float(out[0, i] / w), float(out[1, i] / w)))
            return result
        except Exception as e:
            logger.warning(f"camera_to_map_batch failed: {e}")
            return [None] * len(points)

    # ── customer → zone ───────────────────────────────────────────────

    def process_customer(
        self,
        customer_id: Any,
        camera_position: tuple[float, float] | list[float],
        track_id: Optional[int] = None,
    ) -> CustomerZoneResult:
        """Assign a single customer camera position to zone.

        Steps:
            camera_position → (homography) → map_position → ZoneEngine → zone

        If no calibration: map_position=None, zone=None (not crash).
        If outside all zones: zone_id=None (valid).
        """
        cam_pos = (float(camera_position[0]), float(camera_position[1]))
        map_pos = self.camera_to_map(cam_pos)
        zone_id = None
        zone_name = None
        if map_pos is not None:
            try:
                zone = self.zone_engine.get_zone_for_point(map_pos[0], map_pos[1])
                if zone:
                    zone_id = zone["zone_id"]
                    zone_name = zone["name"]
            except Exception as e:
                logger.warning(f"Zone lookup failed for {map_pos}: {e}")
        return CustomerZoneResult(
            customer_id=customer_id,
            track_id=track_id,
            camera_position=cam_pos,
            map_position=map_pos,
            zone_id=zone_id,
            zone_name=zone_name,
            map_id=self.map_id,
        )

    def process_tracked_customer(self, customer: TrackedCustomer) -> CustomerZoneResult:
        """Convenience: from TrackedCustomer (uses bottom-center)."""
        cam_pos = _get_customer_camera_position(customer)
        return self.process_customer(
            customer_id=customer.customer_id,
            camera_position=cam_pos,
            track_id=customer.track_id,
        )

    def process_customers(self, tracking_result: TrackingResult) -> list[CustomerZoneResult]:
        """Batch for TrackingResult (typical live frame). Reuses cached homography/zones."""
        out: list[CustomerZoneResult] = []
        for cust in tracking_result.customers:
            out.append(self.process_tracked_customer(cust))
        return out

    def process_tracked_customers(self, customers: list[TrackedCustomer]) -> list[CustomerZoneResult]:
        return [self.process_tracked_customer(c) for c in customers]

    def process_batch_dicts(self, customers: list[dict]) -> list[CustomerZoneResult]:
        """Batch for list of dicts with customer_id and camera_position or bbox."""
        out: list[CustomerZoneResult] = []
        for c in customers:
            cid = c.get("customer_id", c.get("track_id", c.get("id")))
            # Prefer explicit camera_position, else derive from bbox
            if "camera_position" in c:
                pos = tuple(c["camera_position"])
            elif "bottom_center" in c:
                pos = tuple(c["bottom_center"])
            elif "bbox" in c:
                bb = c["bbox"]
                # bbox is [x1,y1,x2,y2]
                pos = ((bb[0] + bb[2]) / 2.0, float(bb[2] if len(bb) > 3 else bb[1]))
                # Actually y2 is bottom
                if len(bb) >= 4:
                    pos = ((bb[0] + bb[2]) / 2.0, float(bb[3]))
            elif "position" in c:
                pos = tuple(c["position"])
            else:
                continue
            tid = c.get("track_id")
            out.append(self.process_customer(cid, pos, track_id=tid))
        return out

    # ── utilities ─────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        """True if calibration loaded and zones available (zones may be 0, still ready for outside checks)."""
        return self.is_calibrated

    def __repr__(self) -> str:
        return f"ZoneTrackingIntegrator(map_id={self.map_id!r}, camera_id={self.camera_id!r}, calibrated={self.is_calibrated}, zones={self.zone_engine.zone_count})"

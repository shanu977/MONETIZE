"""Homography calibration logic — no UI, pure math + validation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

# Thresholds for validation
DUPLICATE_THRESH = 8.0  # pixels
COLLINEAR_THRESH = 1e-3
MIN_PAIRS = 4
MAX_PAIRS = 32  # generous


@dataclass
class CalibrationResult:
    homography: np.ndarray  # 3x3
    inverse: np.ndarray  # 3x3
    reprojection_error: float  # mean
    per_point_errors: list[float]
    cctv_points: list[list[float]]
    map_points: list[list[float]]


def _euclidean(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _has_duplicates(points: list[list[float] | tuple[float, float]], thresh: float = DUPLICATE_THRESH) -> bool:
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            if _euclidean(points[i], points[j]) < thresh:
                return True
    return False


def _is_collinear(points: list[list[float] | tuple[float, float]]) -> bool:
    """Check if all points are collinear (degenerate). Uses area method."""
    if len(points) < 3:
        return False
    # Use first 3 points to estimate line, then check remaining distance to line
    # Compute area of triangle for first 3 points
    # If area ~0 for all combinations, collinear
    pts = np.array(points, dtype=np.float64)
    # Check rank via SVD of centered points: if rank <2, collinear
    centered = pts - pts.mean(axis=0)
    # SVD
    try:
        _, s, _ = np.linalg.svd(centered)
        # s[1] is second singular value; if very small, all points on line
        if s[1] < 1e-2:
            return True
    except Exception:
        pass
    # Also check convex hull area very small
    # Triangulation area check for 4 points: if all on line, hull area ~0
    # Approximate by checking max distance from line defined by first two points
    p0 = np.array(points[0], dtype=float)
    p1 = np.array(points[1], dtype=float)
    line_vec = p1 - p0
    line_len = np.linalg.norm(line_vec)
    if line_len < 1e-6:
        return True
    line_unit = line_vec / line_len
    for p in points[2:]:
        v = np.array(p, dtype=float) - p0
        # distance to line = |v x line_unit|
        cross = abs(v[0] * line_unit[1] - v[1] * line_unit[0])
        # Actually need projection distance: cross is area parallelogram / len
        # Simpler: compute perpendicular distance
        proj = np.dot(v, line_unit)
        perp = v - proj * line_unit
        if np.linalg.norm(perp) > 5.0:  # at least one point off line by 5px
            return False
    return True


def _check_degenerate(cctv_pts, map_pts) -> Optional[str]:
    if len(cctv_pts) < MIN_PAIRS:
        return f"Need at least {MIN_PAIRS} point pairs (have {len(cctv_pts)})"
    if _has_duplicates(cctv_pts):
        return "Duplicate CCTV points detected. Please choose distinct locations."
    if _has_duplicates(map_pts):
        return "Duplicate map points detected. Please choose distinct locations."
    if _is_collinear(cctv_pts):
        return "These points cannot be used. Please choose points that cover different parts of the floor. (CCTV points are collinear)"
    if _is_collinear(map_pts):
        return "These points cannot be used. Please choose points that cover different parts of the floor. (Map points are collinear)"
    return None


class HomographyCalibrator:
    """Manages point pairs and homography computation."""

    def __init__(self):
        self.cctv_points: list[list[float]] = []
        self.map_points: list[list[float]] = []
        self.homography: Optional[np.ndarray] = None
        self.inverse: Optional[np.ndarray] = None
        self.result: Optional[CalibrationResult] = None
        self.camera_id: str = "default_camera"
        self.map_id: str = ""
        self.camera_resolution: Optional[tuple[int, int]] = None

    # ── point management ──────────────────────────────────────────────

    def add_pair(self, cctv_pt: tuple[float, float], map_pt: tuple[float, float]) -> None:
        self.cctv_points.append([float(cctv_pt[0]), float(cctv_pt[1])])
        self.map_points.append([float(map_pt[0]), float(map_pt[1])])
        self._invalidate()

    def add_cctv_point(self, pt: tuple[float, float]) -> None:
        """Add pending CCTV point (used by UI step logic)."""
        self.cctv_points.append([float(pt[0]), float(pt[1])])

    def add_map_point(self, pt: tuple[float, float]) -> None:
        self.map_points.append([float(pt[0]), float(pt[1])])

    def has_pending(self) -> bool:
        return len(self.cctv_points) > len(self.map_points)

    def pairs_count(self) -> int:
        return min(len(self.cctv_points), len(self.map_points))

    def total_cctv(self) -> int:
        return len(self.cctv_points)

    def undo(self) -> bool:
        """Remove last complete pair or pending point. Returns False if nothing to undo."""
        if self.has_pending():
            # Remove pending CCTV point
            self.cctv_points.pop()
            self._invalidate()
            return True
        if self.cctv_points and self.map_points:
            self.cctv_points.pop()
            self.map_points.pop()
            self._invalidate()
            return True
        return False

    def reset(self) -> None:
        self.cctv_points.clear()
        self.map_points.clear()
        self._invalidate()

    def _invalidate(self):
        self.homography = None
        self.inverse = None
        self.result = None

    def is_ready(self) -> bool:
        return len(self.cctv_points) >= MIN_PAIRS and len(self.cctv_points) == len(self.map_points)

    def can_calibrate(self) -> bool:
        return self.is_ready() and not self.has_pending()

    # ── validation ────────────────────────────────────────────────────

    def validate(self) -> Optional[str]:
        """Return error string if invalid, else None."""
        if self.has_pending():
            return "Please complete the current pair by clicking the corresponding point on the other side."
        return _check_degenerate(self.cctv_points, self.map_points)

    # ── calibration ───────────────────────────────────────────────────

    def calibrate(self, camera_id: str = "default_camera", map_id: str = "", camera_resolution: tuple[int, int] | None = None) -> CalibrationResult:
        """Compute homography. Raises ValueError on failure."""
        err = self.validate()
        if err:
            raise ValueError(err)
        if not self.can_calibrate():
            raise ValueError(f"Need at least {MIN_PAIRS} complete pairs")

        cctv = np.array(self.cctv_points, dtype=np.float64)
        mmap = np.array(self.map_points, dtype=np.float64)

        # Compute homography: use RANSAC for >4, 0 method for 4
        # For reproducibility, use 0 (least squares) unless outliers expected
        H, mask = cv2.findHomography(cctv, mmap, 0)
        if H is None:
            # Try perspective (4 points) explicitly
            if len(cctv) == 4:
                H = cv2.getPerspectiveTransform(np.float32(cctv), np.float32(mmap))
                if H is None or H.shape != (3, 3):
                    raise ValueError("These points cannot be used. Please choose points that cover different parts of the floor.")
            else:
                raise ValueError("These points cannot be used. Please choose points that cover different parts of the floor.")

        # Compute inverse
        try:
            H_inv = np.linalg.inv(H)
        except np.linalg.LinAlgError:
            raise ValueError("Computed transformation is not invertible. Choose less collinear points.")

        # Quality: reprojection error
        per_errors: list[float] = []
        cctv_h = np.hstack([cctv, np.ones((len(cctv), 1))])  # Nx3
        projected = (H @ cctv_h.T).T  # Nx3
        projected = projected[:, :2] / projected[:, 2:3]
        for i in range(len(mmap)):
            e = float(np.linalg.norm(projected[i] - mmap[i]))
            per_errors.append(e)
        mean_err = float(np.mean(per_errors)) if per_errors else 0.0

        self.homography = H
        self.inverse = H_inv
        self.camera_id = camera_id
        self.map_id = map_id
        self.camera_resolution = camera_resolution
        self.result = CalibrationResult(
            homography=H, inverse=H_inv, reprojection_error=mean_err,
            per_point_errors=per_errors,
            cctv_points=[list(p) for p in self.cctv_points],
            map_points=[list(p) for p in self.map_points],
        )
        return self.result

    def is_calibrated(self) -> bool:
        return self.homography is not None and self.inverse is not None

    # ── transforms ────────────────────────────────────────────────────

    def cctv_to_map(self, points: np.ndarray) -> np.ndarray:
        """Transform Nx2 CCTV points to map. Requires calibrated."""
        if self.homography is None:
            raise RuntimeError("Not calibrated")
        pts = np.asarray(points, dtype=np.float64)
        single = pts.ndim == 1
        if single:
            pts = pts.reshape(1, 2)
        h = np.hstack([pts, np.ones((len(pts), 1))])
        out = (self.homography @ h.T).T
        out = out[:, :2] / out[:, 2:3]
        return out[0] if single else out

    def map_to_cctv(self, points: np.ndarray) -> np.ndarray:
        if self.inverse is None:
            raise RuntimeError("Not calibrated")
        pts = np.asarray(points, dtype=np.float64)
        single = pts.ndim == 1
        if single:
            pts = pts.reshape(1, 2)
        h = np.hstack([pts, np.ones((len(pts), 1))])
        out = (self.inverse @ h.T).T
        out = out[:, :2] / out[:, 2:3]
        return out[0] if single else out

    # ── serialization helpers ─────────────────────────────────────────

    def to_dict(self) -> dict:
        if self.result is None or self.homography is None:
            raise RuntimeError("Not calibrated")
        return {
            "camera_id": self.camera_id,
            "map_id": self.map_id,
            "camera_resolution": list(self.camera_resolution) if self.camera_resolution else None,
            "cctv_points": self.cctv_points,
            "bird_eye_points": self.map_points,  # legacy key
            "map_points": self.map_points,
            "homography_matrix": self.homography.tolist(),
            "reprojection_error": self.result.reprojection_error,
            "per_point_errors": self.result.per_point_errors,
            "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "status": "valid",
        }

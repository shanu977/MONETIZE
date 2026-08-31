"""Calibration persistence — per camera + map isolation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.config import PROJECT_ROOT

DEFAULT_CALIB_DIR = PROJECT_ROOT / "calibration"


def _calib_dir(calibration_dir: str | Path | None) -> Path:
    d = Path(calibration_dir) if calibration_dir else DEFAULT_CALIB_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize(s: str) -> str:
    # allow alphanum, underscore, dash
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in s)


def get_calibration_path(camera_id: str, map_id: str, calibration_dir: str | Path | None = None) -> Path:
    d = _calib_dir(calibration_dir)
    cam = _sanitize(camera_id)
    mp = _sanitize(map_id)
    return d / f"calibration_{cam}__{mp}.json"


def save_calibration(data: dict, calibration_dir: str | Path | None = None) -> Path:
    """Save calibration dict. Requires camera_id and map_id keys."""
    camera_id = data.get("camera_id", "default_camera")
    map_id = data.get("map_id", "")
    if not map_id:
        raise ValueError("map_id required to save calibration")
    path = get_calibration_path(camera_id, map_id, calibration_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_calibration(camera_id: str, map_id: str, calibration_dir: str | Path | None = None) -> Optional[dict]:
    p = get_calibration_path(camera_id, map_id, calibration_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def calibration_exists(camera_id: str, map_id: str, calibration_dir: str | Path | None = None) -> bool:
    return get_calibration_path(camera_id, map_id, calibration_dir).exists()


def check_resolution_mismatch(saved_resolution: list[int] | tuple[int, int] | None, current_resolution: tuple[int, int]) -> Optional[str]:
    """Return warning string if mismatch, else None."""
    if not saved_resolution:
        return None
    try:
        sr = tuple(saved_resolution)  # type: ignore
        cr = tuple(current_resolution)
        if sr != cr:
            return f"Calibration was done at {sr[0]}×{sr[1]}, now camera is {cr[0]}×{cr[1]}. Recalibration recommended."
    except Exception:
        return None
    return None

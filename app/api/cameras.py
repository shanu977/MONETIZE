"""Camera management — RTSP + Demo modes with persistent config."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import cv2

from app.config import PROJECT_ROOT

CAMERAS_FILE = PROJECT_ROOT / "cameras.json"
DEMO_STATE_FILE = PROJECT_ROOT / ".demo_state.json"

# Camera status values
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
STATUS_CONNECTING = "CONNECTING"
STATUS_CONNECTED = "CONNECTED"
STATUS_DISCONNECTED = "DISCONNECTED"
STATUS_ERROR = "ERROR"
STATUS_DEMO = "DEMO"

def _load_cameras() -> list[dict]:
    if not CAMERAS_FILE.exists():
        return []
    try:
        data = json.loads(CAMERAS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return data.get("cameras", [])
    except:
        return []

def _save_cameras(cameras: list[dict]) -> None:
    CAMERAS_FILE.write_text(json.dumps(cameras, indent=2), encoding="utf-8")

def _sanitize_camera(c: dict) -> dict:
    # Never expose password
    out = {k: v for k, v in c.items() if k != "password"}
    # Also hide rtsp url password part?
    if "rtsp_url" in out and "password" in c and c["password"]:
        out["rtsp_url"] = out["rtsp_url"].replace(c["password"], "****")
    return out

def list_cameras() -> list[dict]:
    cams = _load_cameras()
    return [_sanitize_camera(c) for c in cams]

def get_camera(camera_id: str) -> Optional[dict]:
    for c in _load_cameras():
        if c["id"] == camera_id:
            return _sanitize_camera(c)
    return None

def _get_raw(camera_id: str) -> Optional[dict]:
    for c in _load_cameras():
        if c["id"] == camera_id:
            return c
    return None

def create_camera(data: dict) -> dict:
    cams = _load_cameras()
    cid = data.get("id") or f"cam_{uuid.uuid4().hex[:6]}"
    # Ensure unique
    if any(c["id"] == cid for c in cams):
        cid = f"cam_{uuid.uuid4().hex[:6]}"
    cam = {
        "id": cid,
        "name": data.get("name", "Unnamed Camera"),
        "source_type": data.get("source_type", "rtsp"),  # rtsp or demo
        "rtsp_url": data.get("rtsp_url", ""),
        "username": data.get("username", ""),
        "password": data.get("password", ""),  # stored, but not exposed
        "fps": int(data.get("fps", 15)),
        "enabled": bool(data.get("enabled", True)),
        "status": STATUS_DISCONNECTED,
        "resolution": data.get("resolution", None),
        "last_connected": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # Demo camera special
    if cam["source_type"] == "demo":
        cam["rtsp_url"] = "test 1.mp4"
        cam["status"] = STATUS_DEMO
    cams.append(cam)
    _save_cameras(cams)
    return _sanitize_camera(cam)

def update_camera(camera_id: str, data: dict) -> Optional[dict]:
    cams = _load_cameras()
    for i, c in enumerate(cams):
        if c["id"] == camera_id:
            # Update fields (keep password if not provided)
            for k in ["name", "source_type", "rtsp_url", "username", "fps", "enabled", "resolution"]:
                if k in data and data[k] is not None:
                    c[k] = data[k]
            if "password" in data and data["password"]:
                c["password"] = data["password"]
            cams[i] = c
            _save_cameras(cams)
            return _sanitize_camera(c)
    return None

def delete_camera(camera_id: str) -> bool:
    cams = _load_cameras()
    new = [c for c in cams if c["id"] != camera_id]
    if len(new) == len(cams):
        return False
    _save_cameras(new)
    # Also clear active selection if it was this camera
    try:
        from app.api.cctv import get_active_camera_id, set_active_camera_id
        if get_active_camera_id() == camera_id:
            set_active_camera_id(None)
    except: pass
    return True

def test_camera_connection(camera_id: str, timeout: float = 5.0) -> dict:
    cam = _get_raw(camera_id)
    if not cam:
        return {"success": False, "error": "Camera not found"}
    url = cam.get("rtsp_url", "")
    # Build URL with credentials if provided
    if cam.get("username") and cam.get("password"):
        # Simple injection: rtsp://user:pass@host/...
        # Only if url doesn't already contain @
        if "@" not in url and "://" in url:
            proto, rest = url.split("://", 1)
            url = f"{proto}://{cam['username']}:{cam['password']}@{rest}"
    # For demo camera, just check file exists
    if cam.get("source_type") == "demo" or url == "test 1.mp4" or url.endswith("test 1.mp4"):
        p = PROJECT_ROOT / "test 1.mp4"
        if p.exists():
            return {"success": True, "message": "Demo camera reachable (test 1.mp4 found)", "resolution": [848, 478]}
        return {"success": False, "error": "Demo file not found"}

    # Try to open with OpenCV
    cap = cv2.VideoCapture(url)
    # Try to read with timeout
    start = time.time()
    success = False
    error = "Unable to connect"
    while time.time() - start < timeout:
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                success = True
                error = ""
                break
            else:
                error = "Camera opened but no frames received"
                break
        time.sleep(0.3)
    cap.release()
    if success:
        return {"success": True, "message": "Camera reachable", "resolution": [w, h] if 'w' in locals() else None}
    else:
        return {"success": False, "error": error or "Connection timeout. Check RTSP URL, credentials, network."}

def set_camera_status(camera_id: str, status: str) -> None:
    cams = _load_cameras()
    for c in cams:
        if c["id"] == camera_id:
            c["status"] = status
            if status == STATUS_CONNECTED:
                c["last_connected"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _save_cameras(cams)
            break

# Demo mode state
def get_demo_status() -> dict:
    if DEMO_STATE_FILE.exists():
        try:
            return json.loads(DEMO_STATE_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {"active": False, "camera_id": None}

def set_demo_active(active: bool, camera_id: Optional[str] = None) -> dict:
    state = {"active": active, "camera_id": camera_id, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    DEMO_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state

def is_demo_active() -> bool:
    return get_demo_status().get("active", False)

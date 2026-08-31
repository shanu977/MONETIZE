"""CCTV service abstraction — TestVideoSource / RTSPCameraSource."""
from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Optional
import cv2
import numpy as np

from app.video.video_source import VideoSource
from app.config import PROJECT_ROOT

# Global state for live CCTV
_latest_frame: Optional[np.ndarray] = None
_latest_annotated: Optional[np.ndarray] = None
_latest_customers: list[dict] = []
_latest_analytics: Optional[Any] = None
_latest_events: list[Any] = []
_lock = threading.Lock()
_running = False
_thread: Optional[threading.Thread] = None

# For zone integration (optional)
_zone_integrator = None
_analytics_engine = None

def get_video_path() -> Path:
    # Use test 1.mp4 as live source for development
    # Will be replaced with RTSPCameraSource later
    p = PROJECT_ROOT / "test 1.mp4"
    if p.exists():
        return p
    # fallback
    for cand in PROJECT_ROOT.glob("test 1*"):
        if cand.suffix.lower() in {".mp4", ".avi", ".mov"}:
            return cand
    return p

def _cvt_color():
    pass

def start_cctv_service():
    global _running, _thread, _zone_integrator, _analytics_engine
    if _running:
        return
    _running = True

    # Try to init zone integrator and analytics (cached, not per frame)
    try:
        from app.phase2.integration import ZoneTrackingIntegrator
        from app.analytics.engine import AnalyticsEngine
        from app.phase2.maps.manager import get_map_manager
        mgr = get_map_manager()
        sel = mgr.get_selected_map()
        if sel:
            _zone_integrator = ZoneTrackingIntegrator(map_id=sel["map_id"], camera_id="default_camera")
            # Analytics uses same map/camera, reuses integrator's zones/calibration
            try:
                _analytics_engine = AnalyticsEngine(map_id=sel["map_id"], camera_id="default_camera")
            except Exception:
                _analytics_engine = None
        else:
            _zone_integrator = None
            _analytics_engine = None
    except Exception:
        _zone_integrator = None
        _analytics_engine = None

    def loop():
        global _latest_frame, _latest_annotated, _latest_customers, _latest_analytics, _latest_events
        # Lazy load detector only when needed
        detector = None
        try:
            from app.detection.detector import get_detector
            detector = get_detector()
        except Exception:
            detector = None

        video_path = get_video_path()
        vs = VideoSource(str(video_path))
        if not vs.open():
            # fallback to 0 camera
            vs = VideoSource(0)
            vs.open()

        frame_idx = 0
        while _running and vs.is_opened:
            ok, frame = vs.read()
            if not ok or frame is None:
                # loop video
                vs.release()
                vs.open()
                continue

            frame_idx += 1
            with _lock:
                _latest_frame = frame.copy()

            # Run detection if available (sampled)
            customers = []
            annotated = frame.copy()
            analytics_events = []
            if detector is not None:
                try:
                    # Simple sampling: run every frame for now (6 FPS target would be ~ every 5 frames)
                    # For API we run every 3rd frame to balance CPU
                    # Use frame count to sample
                    if vs.frame_count % 3 == 0:
                        from app.models.tracking_data import TrackingResult
                        result = detector.detect_and_track(frame)
                        customers = [
                            {
                                "customer_id": c.customer_id,
                                "track_id": c.track_id,
                                "bbox": c.bbox.to_list(),
                                "center": list(c.center),
                                "bottom_center": list(c.bottom_center),
                            }
                            for c in result.customers
                        ]
                        # Zone assignment if integrator available
                        if _zone_integrator:
                            try:
                                zone_results = _zone_integrator.process_customers(result)
                                for zr, c in zip(zone_results, result.customers):
                                    # Find matching customer dict and add zone
                                    for cust in customers:
                                        if cust["track_id"] == zr.track_id:
                                            cust["zone_id"] = zr.zone_id
                                            cust["zone_name"] = zr.zone_name
                                            cust["map_position"] = list(zr.map_position) if zr.map_position else None
                                            break
                            except Exception:
                                pass

                        # Analytics update (Phase 3) — handles entry/exit, dwell, occupancy, lost-track
                        if _analytics_engine is not None:
                            try:
                                # Use current time and frame_idx for dwell/lost-track
                                analytics_events = _analytics_engine.update(result, timestamp=time.time(), frame_number=frame_idx)
                            except Exception:
                                pass

                        # Draw on annotated frame (with zone/dwell)
                        for cust in customers:
                            x1, y1, x2, y2 = cust["bbox"]
                            color = (52, 152, 219)
                            # track color
                            try:
                                np.random.seed(cust["track_id"])
                                color = tuple(map(int, np.random.randint(50,255,3)))
                                color = (int(color[0]), int(color[1]), int(color[2]))
                            except: pass
                            cv2.rectangle(annotated, (x1,y1), (x2,y2), color, 2)
                            cv2.rectangle(annotated, (x1, y1-18), (x1+90, y1), color, -1)
                            cv2.putText(annotated, cust["customer_id"], (x1+4, y1-6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1, cv2.LINE_AA)
                            bc = tuple(cust["bottom_center"])
                            cv2.circle(annotated, bc, 5, (0,0,255), -1)
                            cv2.circle(annotated, bc, 8, (255,255,255), 2)
                            zone_txt = cust.get("zone_name") or "Outside"
                            # Add dwell if available from analytics
                            dwell_str = ""
                            if _analytics_engine and cust["track_id"] in _analytics_engine.tracks:
                                ts = _analytics_engine.tracks[cust["track_id"]]
                                if ts.current_zone_id and ts.current_zone_time > 0:
                                    dwell_str = f" {ts.current_zone_time:.0f}s"
                            cv2.putText(annotated, f"Zone:{zone_txt}{dwell_str}", (bc[0]+10, bc[1]+12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0,255,255), 1, cv2.LINE_AA)
                except Exception:
                    pass

            # Update global analytics snapshot
            with _lock:
                _latest_annotated = annotated
                _latest_customers = customers
                # Store analytics snapshot for API
                if _analytics_engine:
                    try:
                        _latest_analytics = _analytics_engine.get_snapshot()
                        _latest_events = list(_analytics_engine.events[-20:])
                    except Exception:
                        pass

            time.sleep(0.03)  # ~30 FPS video, but detection sampled

        vs.release()

    _thread = threading.Thread(target=loop, daemon=True)
    _thread.start()

def get_latest_frame(annotated: bool = True) -> Optional[np.ndarray]:
    with _lock:
        if annotated and _latest_annotated is not None:
            return _latest_annotated.copy()
        if _latest_frame is not None:
            return _latest_frame.copy()
        return None

def get_latest_customers() -> list[dict]:
    with _lock:
        return [c.copy() for c in _latest_customers]

def get_latest_analytics():
    with _lock:
        return _latest_analytics

def get_latest_events():
    with _lock:
        return list(_latest_events)

def stop_cctv_service():
    global _running
    _running = False

def reload_cctv_zones(map_id: Optional[str] = None) -> bool:
    """Safely reload zone integrator and analytics engine in live CCTV loop with new zones/map."""
    global _zone_integrator, _analytics_engine
    try:
        from app.phase2.integration import ZoneTrackingIntegrator
        from app.analytics.engine import AnalyticsEngine
        from app.phase2.maps.manager import get_map_manager
        mgr = get_map_manager()
        sel = mgr.get_map(map_id) if map_id else mgr.get_selected_map()
        if sel:
            new_integrator = ZoneTrackingIntegrator(map_id=sel["map_id"], camera_id="default_camera")
            try:
                new_analytics = AnalyticsEngine(map_id=sel["map_id"], camera_id="default_camera")
            except Exception:
                new_analytics = None
            with _lock:
                _zone_integrator = new_integrator
                _analytics_engine = new_analytics
        else:
            with _lock:
                _zone_integrator = None
                _analytics_engine = None
        return True
    except Exception as e:
        print(f"Error reloading CCTV zones: {e}")
        return False

# ── Active camera selection (for Live CCTV page) ──────────────────────
_active_camera_id: Optional[str] = None
_active_camera_file = PROJECT_ROOT / ".active_camera.json"

def get_active_camera_id() -> Optional[str]:
    global _active_camera_id
    if _active_camera_id:
        return _active_camera_id
    # Try to load from file
    if _active_camera_file.exists():
        try:
            data = __import__("json").loads(_active_camera_file.read_text(encoding="utf-8"))
            return data.get("active_camera_id")
        except:
            pass
    return None

def set_active_camera_id(camera_id: Optional[str]) -> None:
    global _active_camera_id
    _active_camera_id = camera_id
    try:
        __import__("json").dumps
        Path(_active_camera_file).write_text(__import__("json").dumps({"active_camera_id": camera_id}, indent=2), encoding="utf-8")
    except:
        pass

# Aliases for convenience
set_active_camera = set_active_camera_id
get_active_camera = get_active_camera_id

def get_active_camera_info() -> dict:
    # Check demo mode first
    try:
        from app.api.cameras import is_demo_active, get_demo_status
        if is_demo_active():
            demo = get_demo_status()
            return {
                "id": demo.get("camera_id") or "demo",
                "name": "Demo Camera",
                "source_type": "demo",
                "source": "test 1.mp4",
                "status": "DEMO",
                "mode": "DEMO",
                "fps": 6,
                "resolution": [848, 478],
                "connected": True,
            }
    except:
        pass
    # Check active camera
    cid = get_active_camera_id()
    if cid:
        try:
            from app.api.cameras import get_camera as cam_get
            cam = cam_get(cid)
            if cam:
                # Try to test if actually reachable, but don't block
                return {
                    "id": cam["id"],
                    "name": cam["name"],
                    "source_type": cam.get("source_type", "rtsp"),
                    "source": cam.get("rtsp_url", ""),
                    "status": cam.get("status", "DISCONNECTED"),
                    "mode": "Running" if cam.get("status") == "CONNECTED" else "Offline",
                    "fps": cam.get("fps", 15),
                    "resolution": cam.get("resolution"),
                }
        except:
            pass
    # No active camera
    return {
        "id": None,
        "name": None,
        "source_type": None,
        "source": None,
        "status": "NOT_CONFIGURED",
        "mode": "Offline",
        "message": "No CCTV camera connected",
    }

# Abstraction for future RTSP
class VideoSourceBase:
    def read(self): raise NotImplementedError
    def release(self): pass

class TestVideoSource(VideoSourceBase):
    """Uses test 1.mp4 — will be replaced by RTSPCameraSource later."""
    def __init__(self, path: str | Path = None):
        self.path = Path(path) if path else get_video_path()
        self.cap = cv2.VideoCapture(str(self.path))
    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        return ok, frame
    def release(self):
        self.cap.release()

class RTSPCameraSource(VideoSourceBase):
    """Future: RTSP camera source — same interface, no dashboard change."""
    def __init__(self, rtsp_url: str):
        self.url = rtsp_url
        self.cap = cv2.VideoCapture(rtsp_url)
    def read(self):
        return self.cap.read()
    def release(self):
        self.cap.release()

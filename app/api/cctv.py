"""CCTV runtime service.

Single background processing pipeline used by the Admin Dashboard.

Demo pipeline:
    test 1.mp4
        -> VideoSource
        -> YOLO + ByteTrack
        -> TrackedCustomer / TrackingResult
        -> ZoneTrackingIntegrator
        -> AnalyticsEngine
        -> shared runtime state
        -> FastAPI
        -> Admin Dashboard

IMPORTANT:
- No mock customer data.
- No random customer counts.
- No fake zones.
- No changes to zone persistence.
- Existing detection/tracking/zone/analytics implementations are reused.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from app.config import PROJECT_ROOT
from app.video.video_source import VideoSource


# ============================================================================
# Shared runtime state
# ============================================================================

_latest_frame: Optional[np.ndarray] = None
_latest_annotated: Optional[np.ndarray] = None

_latest_customers: list[dict] = []
_latest_analytics: Optional[Any] = None
_latest_events: list[Any] = []

_latest_fps: float = 0.0
_latest_resolution: Optional[list[int]] = None
_latest_frame_number: int = 0
_latest_timestamp: float = 0.0

_running = False
_thread: Optional[threading.Thread] = None

_lock = threading.RLock()

# Existing project components.
_zone_integrator = None
_analytics_engine = None
_detector = None

_active_map_id: Optional[str] = None
_active_camera_id: Optional[str] = None

# Prevent duplicate background services.
_start_lock = threading.Lock()


# ============================================================================
# Configuration
# ============================================================================

DEMO_VIDEO_NAME = "test 1.mp4"

# Your verified CLI test uses this map.
# We do NOT create or modify the map/zone data.
DEMO_MAP_ID = "d6f8bd3b"

DEFAULT_CAMERA_ID = "default_camera"

# CLI target.
TARGET_INFERENCE_FPS = 6.0


# ============================================================================
# Video source
# ============================================================================

def get_video_path() -> Path:
    """Return the existing development test video."""

    path = PROJECT_ROOT / DEMO_VIDEO_NAME

    if path.exists():
        return path

    # Preserve the existing fallback behavior for similarly named videos.
    for candidate in PROJECT_ROOT.glob("test 1*"):
        if candidate.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}:
            return candidate

    return path


class VideoSourceBase:
    """Minimal source abstraction."""

    def read(self):
        raise NotImplementedError

    def release(self):
        pass


class TestVideoSource(VideoSourceBase):
    """Looping test-video source used by Dashboard Demo Mode."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else get_video_path()
        self.cap = cv2.VideoCapture(str(self.path))

        self.frame_count = 0

        self.fps = float(
            self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        )

        self.width = int(
            self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0
        )

        self.height = int(
            self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0
        )

    @property
    def is_opened(self) -> bool:
        return bool(self.cap.isOpened())

    def open(self) -> bool:
        if self.cap is None or not self.cap.isOpened():
            self.cap = cv2.VideoCapture(str(self.path))

        if self.cap.isOpened():
            self.fps = float(
                self.cap.get(cv2.CAP_PROP_FPS) or self.fps or 30.0
            )
            self.width = int(
                self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or self.width
            )
            self.height = int(
                self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.height
            )

        return bool(self.cap.isOpened())

    def read(self):
        if not self.cap or not self.cap.isOpened():
            return False, None

        ok, frame = self.cap.read()

        if ok and frame is not None:
            self.frame_count += 1
            return True, frame

        # Loop the test video exactly as a continuous Demo source.
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.frame_count = 0

        ok, frame = self.cap.read()

        if ok and frame is not None:
            self.frame_count = 1

        return ok, frame

    def release(self):
        if self.cap:
            self.cap.release()


class RTSPCameraSource(VideoSourceBase):
    """Future RTSP source using the same read/release interface."""

    def __init__(self, rtsp_url: str):
        self.url = rtsp_url
        self.cap = cv2.VideoCapture(rtsp_url)

    def read(self):
        return self.cap.read()

    def release(self):
        self.cap.release()


# ============================================================================
# Map / pipeline initialization
# ============================================================================

def _get_demo_map_id() -> str:
    """Use the selected map when available, otherwise the verified demo map."""

    try:
        from app.phase2.maps.manager import get_map_manager

        manager = get_map_manager()
        selected = manager.get_selected_map()

        if selected and selected.get("map_id"):
            return str(selected["map_id"])

    except Exception as exc:
        print(f"[CCTV] Could not read selected map: {exc}")

    return DEMO_MAP_ID


def _initialize_pipeline(map_id: str):
    """Initialize the existing project pipeline once."""

    global _zone_integrator
    global _analytics_engine
    global _detector
    global _active_map_id

    print("=" * 70)
    print("[CCTV] Initializing REAL Demo pipeline")
    print("=" * 70)

    print(f"[CCTV] Video: {get_video_path()}")
    print(f"[CCTV] Map ID: {map_id}")
    print(f"[CCTV] Camera ID: {DEFAULT_CAMERA_ID}")
    print(f"[CCTV] Target inference FPS: {TARGET_INFERENCE_FPS}")

    # ----------------------------------------------------------------------
    # Existing detector.
    # This is the same project detector used by the CLI.
    # ----------------------------------------------------------------------
    from app.detection.detector import get_detector

    _detector = get_detector()

    # ----------------------------------------------------------------------
    # Existing ZoneTrackingIntegrator.
    # DO NOT recreate zone persistence.
    # It loads the project's existing calibration/zones.
    # ----------------------------------------------------------------------
    from app.phase2.integration import ZoneTrackingIntegrator

    _zone_integrator = ZoneTrackingIntegrator(
        map_id=map_id,
        camera_id=DEFAULT_CAMERA_ID,
    )

    # ----------------------------------------------------------------------
    # Existing AnalyticsEngine.
    # ----------------------------------------------------------------------
    from app.analytics.engine import AnalyticsEngine

    _analytics_engine = AnalyticsEngine(
        map_id=map_id,
        camera_id=DEFAULT_CAMERA_ID,
    )

    _active_map_id = map_id

    print(f"[CCTV] Detector: {_detector}")
    print(f"[CCTV] ZoneTrackingIntegrator: {_zone_integrator}")
    print(f"[CCTV] AnalyticsEngine: {_analytics_engine}")
    print("[CCTV] REAL pipeline initialized")


# ============================================================================
# Serialization helpers
# ============================================================================

def _bbox_to_list(bbox) -> list[int]:
    """Convert the project's BoundingBox object to JSON-safe coordinates."""

    if hasattr(bbox, "to_list"):
        values = bbox.to_list()
    else:
        values = list(bbox)

    return [int(round(float(v))) for v in values]


def _point_to_list(point) -> list[int]:
    if point is None:
        return []

    return [
        int(round(float(point[0]))),
        int(round(float(point[1]))),
    ]


def _serialize_customer(customer) -> dict:
    """Serialize the project's real TrackedCustomer."""

    return {
        "customer_id": str(customer.customer_id),
        "track_id": int(customer.track_id),
        "bbox": _bbox_to_list(customer.bbox),
        "center": _point_to_list(customer.center),
        "bottom_center": _point_to_list(customer.bottom_center),

        # Filled by ZoneTrackingIntegrator when available.
        "map_position": None,
        "zone_id": None,
        "zone_name": "Outside",

        # Filled from AnalyticsEngine state when available.
        "dwell": 0.0,
        "dwell_seconds": 0.0,
    }


def _apply_zone_result(customer_data: dict, zone_result) -> None:
    """Add real zone/homography output to a customer snapshot."""

    if zone_result is None:
        return

    if getattr(zone_result, "zone_id", None):
        customer_data["zone_id"] = str(zone_result.zone_id)

    zone_name = getattr(zone_result, "zone_name", None)

    if zone_name:
        customer_data["zone_name"] = str(zone_name)
    else:
        customer_data["zone_name"] = "Outside"

    map_position = getattr(zone_result, "map_position", None)

    if map_position is not None:
        customer_data["map_position"] = _point_to_list(map_position)


def _apply_analytics_state(customer_data: dict) -> None:
    """Attach real dwell information from AnalyticsEngine."""

    if _analytics_engine is None:
        return

    track_id = customer_data["track_id"]

    try:
        tracks = getattr(_analytics_engine, "tracks", {})

        state = tracks.get(track_id)

        if state is None:
            return

        # Existing AnalyticsEngine field.
        dwell = getattr(state, "current_zone_time", 0.0)

        if dwell is None:
            dwell = 0.0

        dwell = max(0.0, float(dwell))

        customer_data["dwell"] = dwell
        customer_data["dwell_seconds"] = dwell

    except Exception:
        # Never manufacture a dwell value.
        customer_data["dwell"] = 0.0
        customer_data["dwell_seconds"] = 0.0


# ============================================================================
# Frame annotation
# ============================================================================

def _draw_customer_annotations(
    frame: np.ndarray,
    customers: list[dict],
) -> np.ndarray:

    annotated = frame.copy()

    for customer in customers:
        try:
            x1, y1, x2, y2 = customer["bbox"]

            cv2.rectangle(
                annotated,
                (x1, y1),
                (x2, y2),
                (52, 152, 219),
                2,
            )

            customer_id = customer["customer_id"]

            label = str(customer_id)

            zone_name = customer.get("zone_name") or "Outside"

            dwell = float(
                customer.get("dwell_seconds", 0.0) or 0.0
            )

            cv2.putText(
                annotated,
                label,
                (x1, max(18, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            bottom_center = customer.get("bottom_center")

            if bottom_center and len(bottom_center) >= 2:
                bx, by = bottom_center

                cv2.circle(
                    annotated,
                    (int(bx), int(by)),
                    5,
                    (0, 0, 255),
                    -1,
                )

                cv2.circle(
                    annotated,
                    (int(bx), int(by)),
                    8,
                    (255, 255, 255),
                    2,
                )

                text = f"{zone_name} | {dwell:.1f}s"

                cv2.putText(
                    annotated,
                    text,
                    (int(bx) + 10, int(by) + 12),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    (0, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

        except Exception as exc:
            print(f"[CCTV] Annotation error: {exc}")

    return annotated


# ============================================================================
# Background processing loop
# ============================================================================

def _processing_loop():
    global _latest_frame
    global _latest_annotated
    global _latest_customers
    global _latest_analytics
    global _latest_events
    global _latest_fps
    global _latest_resolution
    global _latest_frame_number
    global _latest_timestamp

    video_path = get_video_path()

    source = TestVideoSource(video_path)

    if not source.open():
        print(f"[CCTV] ERROR: Cannot open demo video: {video_path}")

        with _lock:
            _latest_annotated = None
            _latest_frame = None

        return

    print(
        f"[CCTV] TestVideoSource opened: "
        f"{source.width}x{source.height} @ {source.fps:.2f} FPS"
    )

    # ----------------------------------------------------------------------
    # Inference scheduling.
    #
    # The video is 30 FPS.
    # The CLI target is 6 FPS.
    #
    # 30 / 6 = 5 camera frames per inference.
    # ----------------------------------------------------------------------
    source_fps = source.fps if source.fps > 0 else 30.0

    inference_interval = max(
        1,
        int(round(source_fps / TARGET_INFERENCE_FPS)),
    )

    frame_number = 0

    last_inference_time = 0.0

    while _running:

        ok, frame = source.read()

        if not ok or frame is None:
            time.sleep(0.01)
            continue

        frame_number += 1

        timestamp = time.time()

        with _lock:
            _latest_frame = frame.copy()
            _latest_resolution = [
                int(frame.shape[1]),
                int(frame.shape[0]),
            ]
            _latest_frame_number = frame_number
            _latest_timestamp = timestamp

        # Keep displaying the most recent processed frame between inference
        # frames. This prevents the UI from freezing at 6 FPS.
        should_infer = (
            frame_number == 1
            or frame_number % inference_interval == 0
        )

        if not should_infer:
            continue

        inference_started = time.perf_counter()

        try:
            # ==============================================================
            # REAL YOLO + BYTE TRACK
            # ==============================================================
            result = _detector.detect_and_track(frame)

            customers = [
                _serialize_customer(customer)
                for customer in result.customers
            ]

            # ==============================================================
            # REAL ZONE TRACKING + HOMOGRAPHY
            # ==============================================================
            if _zone_integrator is not None:

                zone_results = _zone_integrator.process_customers(result)

                # Match by track ID instead of relying on list order.
                zone_by_track = {
                    int(zr.track_id): zr
                    for zr in zone_results
                    if getattr(zr, "track_id", None) is not None
                }

                for customer_data in customers:
                    track_id = customer_data["track_id"]

                    zone_result = zone_by_track.get(track_id)

                    if zone_result is not None:
                        _apply_zone_result(
                            customer_data,
                            zone_result,
                        )

            # ==============================================================
            # REAL ANALYTICS ENGINE
            # ==============================================================
            analytics_events = []

            if _analytics_engine is not None:
                analytics_events = _analytics_engine.update(
                    result,
                    timestamp=timestamp,
                    frame_number=frame_number,
                )

                for customer_data in customers:
                    _apply_analytics_state(customer_data)

            # ==============================================================
            # REAL ANNOTATED CCTV FRAME
            # ==============================================================
            annotated = _draw_customer_annotations(
                frame,
                customers,
            )

            # ==============================================================
            # SHARED RUNTIME CACHE
            # ==============================================================
            analytics_snapshot = None
            events_snapshot = []

            if _analytics_engine is not None:
                try:
                    analytics_snapshot = (
                        _analytics_engine.get_snapshot()
                    )
                except Exception as exc:
                    print(
                        f"[CCTV] Analytics snapshot error: {exc}"
                    )

                try:
                    events_snapshot = list(
                        _analytics_engine.events[-50:]
                    )
                except Exception:
                    events_snapshot = []

            elapsed = time.perf_counter() - inference_started

            actual_inference_fps = (
                1.0 / elapsed
                if elapsed > 0
                else 0.0
            )

            with _lock:
                _latest_annotated = annotated
                _latest_customers = customers
                _latest_analytics = analytics_snapshot
                _latest_events = events_snapshot

                # This is the actual inference FPS.
                _latest_fps = actual_inference_fps

        except Exception as exc:
            # Keep the runtime alive so one bad frame does not kill CCTV.
            print(
                f"[CCTV] Processing error on frame "
                f"{frame_number}: {exc}"
            )

    source.release()

    print("[CCTV] Background processing stopped")


# ============================================================================
# Public runtime API
# ============================================================================

def start_cctv_service(
    map_id: Optional[str] = None,
) -> bool:
    """Start exactly one background Demo CCTV processing service."""

    global _running
    global _thread

    with _start_lock:

        if _running and _thread and _thread.is_alive():
            return True

        selected_map = map_id or _get_demo_map_id()

        try:
            _initialize_pipeline(selected_map)
        except Exception as exc:
            print(
                f"[CCTV] Failed to initialize REAL pipeline: {exc}"
            )

            _running = False

            return False

        _running = True

        _thread = threading.Thread(
            target=_processing_loop,
            name="real-demo-cctv-pipeline",
            daemon=True,
        )

        _thread.start()

        return True


def stop_cctv_service():
    """Stop the single background processing service."""

    global _running

    _running = False

    thread = _thread

    if thread and thread.is_alive():
        thread.join(timeout=2.0)


def is_cctv_running() -> bool:
    with _lock:
        return bool(
            _running
            and _thread is not None
            and _thread.is_alive()
        )


def get_latest_frame(
    annotated: bool = True,
) -> Optional[np.ndarray]:
    with _lock:

        if (
            annotated
            and _latest_annotated is not None
        ):
            return _latest_annotated.copy()

        if _latest_frame is not None:
            return _latest_frame.copy()

        return None


def get_latest_customers() -> list[dict]:
    with _lock:
        return [
            dict(customer)
            for customer in _latest_customers
        ]


def get_latest_analytics():
    with _lock:
        return _latest_analytics


def get_latest_events():
    with _lock:
        return list(_latest_events)


def get_runtime_status() -> dict:
    with _lock:

        return {
            "running": is_cctv_running(),
            "mode": "DEMO",
            "source": DEMO_VIDEO_NAME,
            "map_id": _active_map_id,
            "camera_id": DEFAULT_CAMERA_ID,
            "fps": TARGET_INFERENCE_FPS,
            "inference_fps": _latest_fps,
            "resolution": _latest_resolution,
            "frame_number": _latest_frame_number,
            "timestamp": _latest_timestamp,
            "customer_count": len(_latest_customers),
        }


# ============================================================================
# Zone / map reload
# ============================================================================

def reload_cctv_zones(
    map_id: Optional[str] = None,
) -> bool:
    """Reload existing map/calibration/zones without changing persistence."""

    global _zone_integrator
    global _analytics_engine
    global _active_map_id

    try:
        from app.phase2.integration import ZoneTrackingIntegrator
        from app.analytics.engine import AnalyticsEngine
        from app.phase2.maps.manager import get_map_manager

        manager = get_map_manager()

        selected = (
            manager.get_map(map_id)
            if map_id
            else manager.get_selected_map()
        )

        if not selected:
            print(
                "[CCTV] No map available for zone reload"
            )
            return False

        new_map_id = selected["map_id"]

        new_integrator = ZoneTrackingIntegrator(
            map_id=new_map_id,
            camera_id=DEFAULT_CAMERA_ID,
        )

        new_analytics = AnalyticsEngine(
            map_id=new_map_id,
            camera_id=DEFAULT_CAMERA_ID,
        )

        with _lock:
            _zone_integrator = new_integrator
            _analytics_engine = new_analytics
            _active_map_id = new_map_id

            # Do not retain stale customer/analytics state after map switch.
            _latest_customers.clear()
            _latest_events.clear()

        print(
            f"[CCTV] Reloaded map pipeline: {new_map_id}"
        )

        return True

    except Exception as exc:
        print(
            f"[CCTV] Error reloading CCTV zones: {exc}"
        )

        return False


# ============================================================================
# Active camera selection
# ============================================================================

_active_camera_file = PROJECT_ROOT / ".active_camera.json"


def get_active_camera_id() -> Optional[str]:
    global _active_camera_id

    if _active_camera_id:
        return _active_camera_id

    if _active_camera_file.exists():
        try:
            data = json.loads(
                _active_camera_file.read_text(
                    encoding="utf-8"
                )
            )

            return data.get("active_camera_id")

        except Exception:
            pass

    return None


def set_active_camera_id(
    camera_id: Optional[str],
) -> None:

    global _active_camera_id

    _active_camera_id = camera_id

    try:
        _active_camera_file.write_text(
            json.dumps(
                {
                    "active_camera_id": camera_id
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    except Exception:
        pass


set_active_camera = set_active_camera_id
get_active_camera = get_active_camera_id


def get_active_camera_info() -> dict:
    """Return the active camera/demo runtime information."""

    # Demo mode first.
    try:
        from app.api.cameras import (
            is_demo_active,
            get_demo_status,
        )

        if is_demo_active():

            demo = get_demo_status()

            runtime = get_runtime_status()

            return {
                "id": (
                    demo.get("camera_id")
                    or DEFAULT_CAMERA_ID
                ),
                "name": "Demo Camera",
                "source_type": "demo",
                "source": DEMO_VIDEO_NAME,
                "status": (
                    "DEMO"
                    if runtime["running"]
                    else "STOPPED"
                ),
                "mode": "DEMO",
                "fps": TARGET_INFERENCE_FPS,
                "inference_fps": runtime[
                    "inference_fps"
                ],
                "resolution": (
                    runtime["resolution"]
                    or [848, 478]
                ),
                "connected": runtime["running"],
                "customer_count": runtime[
                    "customer_count"
                ],
                "map_id": runtime["map_id"],
            }

    except Exception:
        pass

    # Fallback: if background Demo pipeline is running, expose DEMO
    # even when .demo_state.json has not been toggled yet. This ensures
    # the dashboard shows the live Demo video immediately after startup.
    try:
        runtime = get_runtime_status()
        if runtime.get("running"):
            return {
                "id": DEFAULT_CAMERA_ID,
                "name": "Demo Camera",
                "source_type": "demo",
                "source": DEMO_VIDEO_NAME,
                "status": "DEMO",
                "mode": "DEMO",
                "fps": TARGET_INFERENCE_FPS,
                "inference_fps": runtime.get("inference_fps", 0.0),
                "resolution": runtime.get("resolution") or [848, 478],
                "connected": True,
                "customer_count": runtime.get("customer_count", 0),
                "map_id": runtime.get("map_id"),
            }
    except Exception:
        pass

    # Normal configured camera.
    cid = get_active_camera_id()

    if cid:
        try:
            from app.api.cameras import get_camera

            camera = get_camera(cid)

            if camera:
                return {
                    "id": camera["id"],
                    "name": camera["name"],
                    "source_type": camera.get(
                        "source_type",
                        "rtsp",
                    ),
                    "source": camera.get(
                        "rtsp_url",
                        "",
                    ),
                    "status": camera.get(
                        "status",
                        "DISCONNECTED",
                    ),
                    "mode": (
                        "Running"
                        if camera.get("status")
                        == "CONNECTED"
                        else "Offline"
                    ),
                    "fps": camera.get(
                        "fps",
                        15,
                    ),
                    "resolution": camera.get(
                        "resolution"
                    ),
                }

        except Exception:
            pass

    return {
        "id": None,
        "name": None,
        "source_type": None,
        "source": None,
        "status": "NOT_CONFIGURED",
        "mode": "Offline",
        "message": "No CCTV camera connected",
    }
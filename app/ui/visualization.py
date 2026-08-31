"""Visualization Module - Drawing tracking results on frames."""

import cv2
import numpy as np
import time
from typing import Optional

from app.config import (
    SHOW_FPS,
    SHOW_CONF,
    WINDOW_NAME,
    InferenceState,
)
from app.models.tracking_data import TrackingResult, TrackedCustomer, BoundingBox


class Colors:
    """Color palette for visualization."""
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    RED = (0, 0, 255)
    GREEN = (0, 255, 0)
    BLUE = (255, 0, 0)
    YELLOW = (0, 255, 255)
    CYAN = (255, 255, 0)
    MAGENTA = (255, 0, 255)
    ORANGE = (0, 165, 255)
    PURPLE = (128, 0, 128)

    @staticmethod
    def get_track_color(track_id: int) -> tuple[int, int, int]:
        """Generate consistent color for track ID."""
        np.random.seed(track_id)
        color = tuple(map(int, np.random.randint(50, 255, 3)))
        return (int(color[0]), int(color[1]), int(color[2]))


class Visualizer:
    """Handles drawing of tracking results on video frames."""

    def __init__(
        self,
        show_fps: bool = SHOW_FPS,
        show_conf: bool = SHOW_CONF,
        window_name: str = WINDOW_NAME,
    ):
        self.show_fps = show_fps
        self.show_conf = show_conf
        self.window_name = window_name

        self.fps_counter = 0
        self.fps_timer = time.time()
        self.fps_display = 0.0

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)

    def draw_tracking_result(
        self,
        frame: np.ndarray,
        result: TrackingResult,
        inference_state: InferenceState = InferenceState.INFERENCE_SKIPPED,
        inference_fps: float = 0.0,
        camera_fps: float = 0.0,
    ) -> np.ndarray:
        """Draw all tracked customers on frame."""
        annotated = frame.copy()

        # Try to get analytics snapshot if attached (Phase 3)
        analytics = getattr(result, "analytics_snapshot", None)
        # Build track_id -> zone/dwell lookup
        zone_lookup: dict[int, tuple[str | None, float]] = {}
        if analytics and hasattr(analytics, "zone_statistics"):
            # Not needed here, per-customer zone is more useful
            pass
        # If result has per-customer zone info via analytics, we can draw it
        # For now, try to get from result's customers' track states if available
        # Fallback: check if result has customer_zone_results attribute
        zone_results = getattr(result, "customer_zone_results", None)
        zone_map: dict[int, Any] = {}
        if zone_results:
            for zr in zone_results:
                try:
                    zone_map[zr.track_id] = zr
                except Exception:
                    pass

        for customer in result.customers:
            # Check if we have analytics state for this track
            dwell_str = None
            zone_name = None
            if analytics:
                # Find track state
                try:
                    from app.analytics.engine import AnalyticsEngine  # to avoid circular
                except Exception:
                    pass
            # Try to get from zone_results
            zr = zone_map.get(customer.track_id)
            if zr:
                zone_name = zr.zone_name
                # Dwell from analytics if available
                if analytics:
                    try:
                        # Find track state in analytics engine (if attached)
                        pass
                    except Exception:
                        pass
            self._draw_customer(annotated, customer, zone_name=zone_name, dwell_str=dwell_str)

        if self.show_fps:
            self._update_fps()
            self._draw_fps(annotated, inference_fps, camera_fps)

        self._draw_info_bar(annotated, result, inference_state)

        # Draw analytics overlay if available
        if analytics:
            try:
                self._draw_analytics_overlay(annotated, analytics)
            except Exception:
                pass

        return annotated

    def _draw_analytics_overlay(self, frame: np.ndarray, snapshot) -> None:
        """Draw zone occupancy and dwell info."""
        try:
            h, w = frame.shape[:2]
            # Top-right overlay for occupancy
            y = 60
            for stat in snapshot.zone_statistics[:3]:  # top 3 zones
                txt = f"{stat.zone_name}: {stat.current_occupancy} (avg {stat.average_dwell_seconds:.0f}s)"
                (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                cv2.rectangle(frame, (w - tw - 15, y - th - 5), (w - 5, y + 5), (0, 0, 0), -1)
                cv2.putText(frame, txt, (w - tw - 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
                y += 22
        except Exception:
            pass

    def _draw_customer(self, frame: np.ndarray, customer: TrackedCustomer, zone_name: str | None = None, dwell_str: str | None = None) -> None:
        """Draw single customer: bbox, ID, center point, zone/dwell."""
        bbox = customer.bbox
        color = Colors.get_track_color(customer.track_id)
        txt_color = self._get_text_color(color)

        x1, y1, x2, y2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        label = customer.customer_id
        if zone_name:
            label += f" | {zone_name}"
        if dwell_str:
            label += f" {dwell_str}"
        if self.show_conf:
            label += f" ({customer.confidence:.2f})"

        (tw, th), bl = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        # Ensure label fits in frame
        lx1 = max(0, x1)
        ly1 = max(th + 10, y1)
        cv2.rectangle(frame, (lx1, ly1 - th - 10), (lx1 + tw + 10, ly1), color, -1)
        cv2.putText(frame, label, (lx1 + 5, ly1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, txt_color, 1, cv2.LINE_AA)

        center = customer.center
        cv2.circle(frame, center, 5, color, -1)
        cv2.circle(frame, center, 8, color, 2)

        center_label = f"({center[0]}, {center[1]})"
        (tw, th), _ = cv2.getTextSize(center_label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.putText(frame, center_label, (center[0] + 10, center[1] - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        # Bottom-center (feet) point for zone calibration
        bc = customer.bottom_center
        cv2.circle(frame, bc, 4, (0, 255, 255), -1)
        cv2.circle(frame, bc, 6, (0, 0, 0), 1)

        if zone_name:
            zone_label = f"Zone: {zone_name}"
            (tw2, th2), _ = cv2.getTextSize(zone_label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
            # Draw just below bottom-center
            zy = min(frame.shape[0] - 5, bc[1] + 18)
            cv2.rectangle(frame, (bc[0] + 8 - 2, zy - th2 - 2), (bc[0] + 8 + tw2 + 2, zy + 2), (0, 0, 0), -1)
            cv2.putText(frame, zone_label, (bc[0] + 8, zy), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1, cv2.LINE_AA)

    def _draw_fps(self, frame: np.ndarray, inference_fps: float, camera_fps: float) -> None:
        """Draw FPS counter with both camera and inference FPS."""
        fps_text = f"Camera: {camera_fps:.1f} FPS | Inference: {inference_fps:.1f} FPS"
        (tw, th), bl = cv2.getTextSize(fps_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(frame, (10 - 5, 25 - th - 5), (10 + tw + 5, 25 + bl), Colors.WHITE, -1)
        cv2.putText(frame, fps_text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, Colors.BLACK, 2)

    def _draw_info_bar(self, frame: np.ndarray, result: TrackingResult, inference_state: InferenceState) -> None:
        """Draw info bar with tracking summary and inference state."""
        h, w = frame.shape[:2]
        info_text = f"Tracked: {len(result.customers)} customers"
        if result.fps > 0:
            info_text += f" | Inference FPS: {result.fps:.1f}"
        
        # Add inference state indicator
        state_colors = {
            InferenceState.INFERENCE_EXECUTED_WITH_DETECTIONS: Colors.GREEN,
            InferenceState.INFERENCE_EXECUTED_NO_DETECTIONS: Colors.YELLOW,
            InferenceState.INFERENCE_SKIPPED: Colors.BLUE,
        }
        state_text = f" | {inference_state.value}"
        info_text += state_text

        (tw, th), bl = cv2.getTextSize(info_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        y_pos = h - 20
        cv2.rectangle(frame, (10 - 5, y_pos - th - 5), (10 + tw + 5, y_pos + bl), Colors.BLACK, -1)
        cv2.putText(frame, info_text, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, Colors.GREEN, 2)

    def _update_fps(self) -> None:
        """Update FPS counter."""
        self.fps_counter += 1
        if time.time() - self.fps_timer >= 1.0:
            self.fps_display = self.fps_counter
            self.fps_counter = 0
            self.fps_timer = time.time()

    def _get_text_color(self, bg_color: tuple[int, int, int]) -> tuple[int, int, int]:
        """Get contrasting text color for background."""
        r, g, b = bg_color
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        return Colors.BLACK if luminance > 128 else Colors.WHITE

    def show(self, frame: np.ndarray) -> int:
        """Display frame and return key press."""
        cv2.imshow(self.window_name, frame)
        return cv2.waitKey(1) & 0xFF

    def close(self) -> None:
        """Close display window."""
        cv2.destroyWindow(self.window_name)


class VideoWriter:
    """Handles video output recording."""

    def __init__(self, output_path: str, fps: float, frame_size: tuple[int, int]):
        self.output_path = output_path
        self.fps = fps
        self.frame_size = frame_size
        self.writer: Optional[cv2.VideoWriter] = None

    def write(self, frame: np.ndarray) -> None:
        """Write frame to video file."""
        if self.writer is None:
            self._init_writer(frame)

        if self.writer is not None:
            self.writer.write(frame)

    def _init_writer(self, frame: np.ndarray) -> None:
        """Initialize video writer on first frame."""
        h, w = frame.shape[:2]
        ext = self.output_path.lower().split('.')[-1]
        fourcc = cv2.VideoWriter_fourcc(*("MJPG" if ext == "avi" else "mp4v"))
        self.writer = cv2.VideoWriter(self.output_path, fourcc, self.fps, (w, h))

    def release(self) -> None:
        """Release video writer."""
        if self.writer is not None:
            self.writer.release()
            self.writer = None


def create_visualizer(**kwargs) -> Visualizer:
    """Factory function to create Visualizer."""
    return Visualizer(**kwargs)
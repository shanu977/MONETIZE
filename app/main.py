"""Main Application Entry Point - MONETIZE Automatic Customer Tracking."""

import sys
from pathlib import Path

# Ensure app module is importable when run directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import time
import signal
from typing import Optional

import cv2
import numpy as np

from app.config import (
    SOURCE,
    INFERENCE_FPS,
    SAVE_VIDEO,
    VIDEO_OUTPUT_PATH,
    WINDOW_NAME,
    TRACKING_STATE_TIMEOUT,
    InferenceState,
)
from app.detection.detector import PersonDetector, get_detector
from app.video.video_source import VideoSource, create_video_source
from app.ui.visualization import Visualizer, VideoWriter, create_visualizer
from app.models.tracking_data import TrackingResult
from ultralytics.utils import LOGGER


class CustomerTrackerApp:
    """Main application for automatic multi-person tracking."""

    def __init__(
        self,
        source: int | str = SOURCE,
        inference_fps: float = INFERENCE_FPS,
        save_video: bool = SAVE_VIDEO,
        output_path: str = VIDEO_OUTPUT_PATH,
        window_name: str = WINDOW_NAME,
        map_id: Optional[str] = None,
        camera_id: str = "default_camera",
        enable_phase2: bool = False,
    ):
        self.source = source
        self.inference_fps = inference_fps
        self.save_video = save_video
        self.output_path = output_path
        self.window_name = window_name
        self.map_id = map_id
        self.camera_id = camera_id
        self.enable_phase2 = enable_phase2

        self.detector: Optional[PersonDetector] = None
        self.video_source: Optional[VideoSource] = None
        self.visualizer: Optional[Visualizer] = None
        self.video_writer: Optional[VideoWriter] = None
        self.zone_integrator: Optional[Any] = None
        self.analytics_engine: Optional[Any] = None

        self.running = False

        # Frame counters
        self.camera_frame_count = 0
        self.inference_frame_count = 0
        self.skipped_frame_count = 0

        # Detection statistics
        self.inference_with_detections = 0
        self.inference_without_detections = 0

        # Timing
        self.last_inference_time = 0.0
        self.inference_interval = 1.0 / inference_fps if inference_fps > 0 else 0
        self.inference_fps_actual = 0.0
        self.inference_start_time = 0.0
        self.inference_times: list[float] = []

        # State for preserving tracking results
        self.last_valid_result: Optional[TrackingResult] = None
        self.last_inference_state: InferenceState = InferenceState.INFERENCE_SKIPPED
        self.inference_in_progress = False

    def initialize(self) -> bool:
        """Initialize all components."""
        LOGGER.info("=" * 50)
        LOGGER.info("MONETIZE - Automatic Customer Tracking")
        LOGGER.info("=" * 50)

        LOGGER.info("Initializing detector...")
        self.detector = get_detector()

        LOGGER.info(f"Opening video source: {self.source}")
        self.video_source = VideoSource(self.source)
        if not self.video_source.open():
            LOGGER.error(f"Failed to open video source: {self.source}")
            return False

        LOGGER.info(f"Video: {self.video_source.width}x{self.video_source.height} @ {self.video_source.fps:.1f} FPS")
        LOGGER.info(f"Target inference FPS: {self.inference_fps} (interval: {self.inference_interval*1000:.1f} ms)")

        self.visualizer = create_visualizer(window_name=self.window_name)

        if self.save_video:
            Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
            self.video_writer = VideoWriter(
                self.output_path,
                self.video_source.fps,
                (self.video_source.width, self.video_source.height),
            )
            LOGGER.info(f"Video recording enabled: {self.output_path}")

        # ── Phase 2.5: Zone Tracking Integration (cached, not per-frame) ──
        # Only enable if explicitly requested or map_id provided
        should_init_zones = self.enable_phase2 or self.map_id is not None
        if should_init_zones:
            try:
                # Resolve map_id: explicit > selected map
                resolved_map_id = self.map_id
                if not resolved_map_id:
                    try:
                        from app.phase2.maps.manager import get_map_manager
                        sel = get_map_manager().get_selected_map()
                        if sel and sel.get("map_id"):
                            resolved_map_id = sel["map_id"]
                    except Exception:
                        resolved_map_id = None
                if not resolved_map_id:
                    LOGGER.warning("Phase 2 zone integration requested but no map selected. Run Map Management tool first. Continuing Phase 1 only.")
                else:
                    self.map_id = resolved_map_id
                    from app.phase2.integration import ZoneTrackingIntegrator
                    self.zone_integrator = ZoneTrackingIntegrator(
                        map_id=self.map_id,
                        camera_id=self.camera_id,
                        camera_resolution=(self.video_source.width, self.video_source.height),
                    )
                    if self.zone_integrator.is_calibrated:
                        LOGGER.info(f"Zone integration enabled: map={self.map_id} camera={self.camera_id} zones={self.zone_integrator.zone_engine.zone_count} calibrated=True")
                    else:
                        LOGGER.warning(f"Zone integration: map={self.map_id} camera={self.camera_id} zones={self.zone_integrator.zone_engine.zone_count} — no calibration found, zone assignments will be None (still tracking)")
                    # ── Phase 3: Analytics Engine (cached) ──
                    try:
                        from app.analytics.engine import AnalyticsEngine
                        self.analytics_engine = AnalyticsEngine(
                            map_id=self.map_id,
                            camera_id=self.camera_id,
                            camera_resolution=(self.video_source.width, self.video_source.height),
                        )
                        LOGGER.info(f"Analytics engine enabled: map={self.map_id} zones={len(self.analytics_engine.zone_stats)}")
                    except Exception as ae:
                        LOGGER.warning(f"Failed to init AnalyticsEngine: {ae}")
                        self.analytics_engine = None
            except Exception as e:
                LOGGER.warning(f"Failed to initialize ZoneTrackingIntegrator: {e}. Continuing Phase 1 only.")
                self.zone_integrator = None
                self.analytics_engine = None

        self._setup_signal_handlers()
        return True

    def _setup_signal_handlers(self) -> None:
        """Setup graceful shutdown handlers."""
        def signal_handler(sig, frame):
            LOGGER.info("Shutdown signal received...")
            self.running = False
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def run(self) -> None:
        """Main processing loop."""
        if not self.initialize():
            return

        self.running = True
        LOGGER.info("Starting tracking loop... Press 'q' to quit.")

        loop_start_time = time.time()
        last_time = loop_start_time
        last_fps_log_time = loop_start_time

        while self.running and self.video_source.is_opened:
            current_time = time.time()
            delta_time = current_time - last_time
            last_time = current_time

            # Read frame from camera (always capture at camera FPS)
            success, frame = self.video_source.read()
            if not success or frame is None:
                LOGGER.info("End of video stream")
                break

            self.camera_frame_count += 1

            # Determine if inference should run (time-based scheduling)
            time_since_last_inference = current_time - self.last_inference_time
            should_infer = (
                self.inference_fps <= 0  # No limit
                or time_since_last_inference >= self.inference_interval
            )

            tracking_result: Optional[TrackingResult] = None
            inference_ran = False
            inference_state = InferenceState.INFERENCE_SKIPPED

            if should_infer and self.detector and not self.inference_in_progress:
                # Run inference on the LATEST frame
                self.inference_in_progress = True
                self.inference_start_time = time.time()
                
                tracking_result = self.detector.detect_and_track(frame)
                
                inference_time = time.time() - self.inference_start_time
                self.inference_in_progress = False
                self.last_inference_time = current_time
                self.inference_frame_count += 1
                self.inference_times.append(inference_time)

                # Update actual inference FPS (rolling average over last 10 inferences)
                if len(self.inference_times) > 10:
                    self.inference_times = self.inference_times[-10:]
                if self.inference_times:
                    avg_inference_time = sum(self.inference_times) / len(self.inference_times)
                    self.inference_fps_actual = 1.0 / avg_inference_time if avg_inference_time > 0 else 0

                tracking_result.fps = self.inference_fps_actual
                inference_ran = True

                if tracking_result.customers:
                    inference_state = InferenceState.INFERENCE_EXECUTED_WITH_DETECTIONS
                    self.inference_with_detections += 1
                    self.last_valid_result = tracking_result
                else:
                    inference_state = InferenceState.INFERENCE_EXECUTED_NO_DETECTIONS
                    self.inference_without_detections += 1
                    # Keep last valid result if we had one, otherwise clear
                    if self.last_valid_result is not None:
                        # Check if cached result is still valid (timeout)
                        time_since_last_valid = current_time - self._get_result_timestamp(self.last_valid_result)
                        if time_since_last_valid > TRACKING_STATE_TIMEOUT:
                            self.last_valid_result = None
                    # tracking_result already has empty customers list
            else:
                self.skipped_frame_count += 1
                inference_state = InferenceState.INFERENCE_SKIPPED
                
                # Use cached result if within timeout
                if self.last_valid_result is not None:
                    time_since_last_valid = current_time - self._get_result_timestamp(self.last_valid_result)
                    if time_since_last_valid <= TRACKING_STATE_TIMEOUT:
                        tracking_result = self.last_valid_result
                    else:
                        tracking_result = TrackingResult(customers=[], fps=self.inference_fps_actual)
                        self.last_valid_result = None
                else:
                    tracking_result = TrackingResult(customers=[], fps=self.inference_fps_actual)

            self.last_inference_state = inference_state

            # Visualization — single CCTV window only
            if self.visualizer:
                annotated_frame = self.visualizer.draw_tracking_result(
                    frame, tracking_result, inference_state, self.inference_fps_actual, self.video_source.fps
                )

                if self.save_video and self.video_writer:
                    self.video_writer.write(annotated_frame)

                key = self.visualizer.show(annotated_frame)
                if key == ord('q'):
                    LOGGER.info("Quit key pressed")
                    break

            # Zone Integration (Phase 2.5) + Analytics (Phase 3) — after TrackingResult
            # Cached: integrator/analytics created once in initialize(), not per frame
            # Keep TrackingResult intact; produce CustomerZoneResults and Analytics
            zone_results = None
            analytics_events = []
            if self.zone_integrator is not None and tracking_result is not None:
                try:
                    zone_results = self.zone_integrator.process_customers(tracking_result)
                    if zone_results and inference_ran:
                        parts = []
                        for zr in zone_results:
                            zone_label = zr.zone_name if zr.zone_name else "Outside"
                            parts.append(f"{zr.customer_id}→{zone_label}")
                        LOGGER.info(f"Zone assignments | {' | '.join(parts)}")
                except Exception as e:
                    LOGGER.warning(f"Zone integration error: {e}")
                    zone_results = None

            # Analytics Engine update (Phase 3) — handles entry/exit, dwell, occupancy, counting
            if self.analytics_engine is not None and tracking_result is not None:
                try:
                    # Analytics uses TrackingResult directly (it will call integrator internally for zone)
                    # Pass current time and frame number for dwell/lost-track handling
                    analytics_events = self.analytics_engine.update(
                        tracking_result,
                        timestamp=current_time,
                        frame_number=self.camera_frame_count,
                    )
                    for ev in analytics_events:
                        if ev.event_type in ("zone_entry", "zone_exit", "zone_transition"):
                            dwell_str = f" dwell={ev.dwell_seconds:.1f}s" if ev.dwell_seconds else ""
                            LOGGER.info(f"[ZONE] {ev.event_type} track={ev.track_id} zone={ev.zone_id or ev.from_zone_id} {dwell_str}")
                        elif ev.event_type in ("track_started", "track_lost", "track_ended"):
                            LOGGER.debug(f"[TRACK] {ev.event_type} track={ev.track_id}")
                except Exception as e:
                    LOGGER.warning(f"Analytics error: {e}")

            # Enhanced visualization with analytics (if available)
            if self.visualizer and self.analytics_engine is not None and tracking_result is not None:
                # Pass analytics info to visualizer for dwell/occupancy display
                try:
                    snapshot = self.analytics_engine.get_snapshot()
                    # Attach snapshot to tracking_result for visualization (optional)
                    tracking_result.analytics_snapshot = snapshot  # type: ignore
                except Exception:
                    pass

            # Logging
            self._log_tracking_result(tracking_result, inference_state, inference_ran)

            # Periodic FPS logging
            if current_time - last_fps_log_time >= 5.0:
                self._log_periodic_fps()
                last_fps_log_time = current_time

        # Final statistics
        total_time = time.time() - loop_start_time
        self._log_final_statistics(total_time)

        self.cleanup()

    def _get_result_timestamp(self, result: TrackingResult) -> float:
        """Extract timestamp from the first customer, or return 0."""
        if result.customers:
            try:
                from datetime import datetime
                return datetime.fromisoformat(result.customers[0].timestamp).timestamp()
            except Exception:
                pass
        return 0.0

    def _log_tracking_result(
        self,
        result: TrackingResult,
        inference_state: InferenceState,
        inference_ran: bool
    ) -> None:
        """Log tracking results to terminal with clear state distinction."""
        frame_label = f"Camera Frame {self.camera_frame_count}"
        
        if inference_ran:
            if inference_state == InferenceState.INFERENCE_EXECUTED_WITH_DETECTIONS:
                parts = [f"{c.customer_id}@({c.center[0]},{c.center[1]})" for c in result.customers]
                LOGGER.info(f"{frame_label} | {inference_state.value} | Customers: {' | '.join(parts)}")
            else:
                LOGGER.info(f"{frame_label} | {inference_state.value} | Customers: NONE")
        else:
            if result.customers:
                parts = [f"{c.customer_id}@({c.center[0]},{c.center[1]})" for c in result.customers]
                LOGGER.info(f"{frame_label} | {inference_state.value} | Latest: {' | '.join(parts)}")
            else:
                LOGGER.info(f"{frame_label} | {inference_state.value} | No cached result")

    def _log_periodic_fps(self) -> None:
        """Log periodic FPS information."""
        LOGGER.info(
            f"FPS Stats - Camera: {self.camera_frame_count / (time.time() - (time.time() - 5)):.1f} "
            f"(approx) | Inference: {self.inference_fps_actual:.1f} | "
            f"Total frames: {self.camera_frame_count} | Inferences: {self.inference_frame_count} | Skipped: {self.skipped_frame_count}"
        )

    def _log_final_statistics(self, total_time: float) -> None:
        """Log final performance statistics."""
        camera_fps = self.camera_frame_count / total_time if total_time > 0 else 0
        actual_inference_fps = self.inference_frame_count / total_time if total_time > 0 else 0
        avg_inference_time = sum(self.inference_times) / len(self.inference_times) * 1000 if self.inference_times else 0

        LOGGER.info("=" * 50)
        LOGGER.info("MONETIZE PERFORMANCE STATISTICS")
        LOGGER.info("=" * 50)
        LOGGER.info(f"Total runtime: {total_time:.1f} seconds")
        LOGGER.info(f"Camera frames captured: {self.camera_frame_count}")
        LOGGER.info(f"Camera FPS (measured): {camera_fps:.1f}")
        LOGGER.info(f"Target inference FPS: {self.inference_fps}")
        LOGGER.info(f"Inference frames executed: {self.inference_frame_count}")
        LOGGER.info(f"Frames skipped: {self.skipped_frame_count}")
        LOGGER.info(f"Actual inference FPS: {actual_inference_fps:.1f}")
        LOGGER.info(f"Average YOLO inference time: {avg_inference_time:.1f} ms")
        LOGGER.info(f"Inference frames WITH detections: {self.inference_with_detections}")
        LOGGER.info(f"Inference frames WITHOUT detections: {self.inference_without_detections}")
        LOGGER.info("=" * 50)

    def cleanup(self) -> None:
        """Clean up resources."""
        LOGGER.info("Cleaning up...")
        self.running = False

        if self.video_source:
            self.video_source.release()

        if self.video_writer:
            self.video_writer.release()

        if self.visualizer:
            self.visualizer.close()

        LOGGER.info("Application closed.")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="MONETIZE - Automatic Customer Tracking (+ Zone Integration)")
    parser.add_argument("--source", type=str, default=str(SOURCE),
                       help="Video source (0 for webcam, or path to video file)")
    parser.add_argument("--inference-fps", type=float, default=INFERENCE_FPS,
                       help="Target inference FPS (0 for no limit)")
    parser.add_argument("--save-video", action="store_true", default=SAVE_VIDEO,
                       help="Save output video")
    parser.add_argument("--output", type=str, default=VIDEO_OUTPUT_PATH,
                       help="Output video path")
    parser.add_argument("--model", type=str, default="yolo11n.pt",
                       help="YOLO model path")
    parser.add_argument("--gpu", action="store_true", help="Enable GPU")
    # Phase 2 integration (optional, backward compatible)
    parser.add_argument("--phase2", action="store_true", help="Enable Phase 2 zone integration (uses selected map if --map not provided)")
    parser.add_argument("--map", type=str, default=None, help="Bird's-Eye map ID for Phase 2 (e.g., d6f8bd3b). Implies --phase2")
    parser.add_argument("--map-id", type=str, default=None, help=argparse.SUPPRESS)  # alias for --map
    parser.add_argument("--camera-id", type=str, default="default_camera", help="Camera ID for calibration (default: default_camera)")

    args = parser.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source

    # Resolve map alias: --map-id takes precedence if provided
    map_id = args.map_id if args.map_id else args.map
    enable_phase2 = args.phase2 or (map_id is not None)

    app = CustomerTrackerApp(
        source=source,
        inference_fps=args.inference_fps,
        save_video=args.save_video,
        output_path=args.output,
        map_id=map_id,
        camera_id=args.camera_id,
        enable_phase2=enable_phase2,
    )

    if args.gpu:
        from app.config import ENABLE_GPU
        import app.config as config_module
        config_module.ENABLE_GPU = True

    if args.model != "yolo11n.pt":
        import app.config as config_module
        config_module.MODEL_PATH = args.model

    try:
        app.run()
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")
    except Exception as e:
        LOGGER.error(f"Application error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

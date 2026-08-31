"""Video Source Module - Webcam and video file handling."""

import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Union

from app.config import SOURCE


class VideoSource:
    """Handles video input from webcam or file."""

    def __init__(
        self,
        source: Union[int, str] = SOURCE,
        target_fps: Optional[float] = None,
        frame_skip: int = 0,
    ):
        self.source = source
        self.target_fps = target_fps
        self.frame_skip = frame_skip
        self.cap: Optional[cv2.VideoCapture] = None
        self.frame_count = 0
        self._fps: float = 0.0
        self._width: int = 0
        self._height: int = 0

    def open(self) -> bool:
        """Open video source."""
        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            return False

        self._width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps = self.cap.get(cv2.CAP_PROP_FPS)
        if self._fps <= 0:
            self._fps = 30.0

        return True

    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        """Read next frame."""
        if self.cap is None:
            return False, None

        success, frame = self.cap.read()
        if success:
            self.frame_count += 1
        return success, frame

    def skip_frames(self, n: int) -> bool:
        """Skip n frames."""
        if self.cap is None:
            return False
        for _ in range(n):
            if not self.cap.grab():
                return False
        return True

    def get_frame(self) -> tuple[bool, Optional[np.ndarray]]:
        """Get frame with optional frame skipping for FPS control."""
        if self.frame_skip > 0:
            self.skip_frames(self.frame_skip)
        return self.read()

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def is_opened(self) -> bool:
        return self.cap is not None and self.cap.isOpened()

    def release(self) -> None:
        """Release video capture."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def __enter__(self) -> "VideoSource":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class FrameSampler:
    """Samples frames to achieve target inference FPS."""

    def __init__(self, source_fps: float, target_fps: float):
        self.source_fps = source_fps
        self.target_fps = target_fps
        self.accumulator = 0.0
        self.frame_interval = 1.0 / target_fps if target_fps > 0 else 0

    def should_process(self, delta_time: float) -> bool:
        """Determine if current frame should be processed."""
        if self.target_fps <= 0 or self.target_fps >= self.source_fps:
            return True

        self.accumulator += delta_time
        if self.accumulator >= self.frame_interval:
            self.accumulator -= self.frame_interval
            return True
        return False

    def reset(self) -> None:
        """Reset accumulator."""
        self.accumulator = 0.0


def create_video_source(
    source: Union[int, str] = SOURCE,
    inference_fps: float = 6.0,
) -> tuple[VideoSource, Optional[FrameSampler]]:
    """Factory to create video source with optional frame sampler."""
    video = VideoSource(source)
    if not video.open():
        raise RuntimeError(f"Failed to open video source: {source}")

    sampler = None
    if inference_fps > 0 and inference_fps < video.fps:
        sampler = FrameSampler(video.fps, inference_fps)

    return video, sampler
"""Configuration settings for SIH Part 1 - Automatic Customer Detection & Tracking."""

from pathlib import Path
from enum import Enum


class InferenceState(Enum):
    """Three distinct states for inference tracking."""
    INFERENCE_EXECUTED_WITH_DETECTIONS = "INFERENCE_WITH_DETECTIONS"
    INFERENCE_EXECUTED_NO_DETECTIONS = "INFERENCE_NO_DETECTIONS"
    INFERENCE_SKIPPED = "INFERENCE_SKIPPED"


PROJECT_ROOT = Path(__file__).resolve().parent.parent

MODEL_PATH = "yolo11n.pt"

SOURCE = 0

TRACKER_CONFIG = "bytetrack.yaml"

CONF_THRESHOLD = 0.3

IOU_THRESHOLD = 0.3

MAX_DET = 20

PERSON_CLASS_ID = 0

PERSON_CLASS_NAME = "person"

INFERENCE_FPS = 6

SHOW_FPS = True

SHOW_CONF = False

SAVE_VIDEO = False

VIDEO_OUTPUT_PATH = str(PROJECT_ROOT / "output" / "tracking_output.avi")

WINDOW_NAME = "SIH Part 1 - Automatic Customer Tracking"

ENABLE_GPU = False

TRACK_ARGS = {
    "persist": True,
    "verbose": False,
}

TRACKER_DEFAULTS = {
    "track_high_thresh": 0.5,
    "new_track_thresh": 0.5,
    "match_thresh": 0.8,
    "track_buffer": 30,
    "frame_rate": 30,
}

BYTE_TRACK_CONFIG_CONTENT = """# ByteTrack configuration for SIH Part 1
tracker_type: bytetrack
track_high_thresh: 0.5
new_track_thresh: 0.5
match_thresh: 0.8
track_buffer: 30
frame_rate: 30
"""

# Tracking state timeout (seconds) - how long to keep showing cached result
TRACKING_STATE_TIMEOUT = 2.0
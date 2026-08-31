"""ByteTrack Tracking Module - Wrapper for Ultralytics ByteTrack."""

from pathlib import Path
from typing import Any

from app.config import (
    TRACKER_DEFAULTS,
    BYTE_TRACK_CONFIG_CONTENT,
    TRACKER_CONFIG,
)
from app.models.tracking_data import TrackingResult, TrackedCustomer


class ByteTrackWrapper:
    """Wrapper for ByteTrack configuration and utilities."""

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or TRACKER_CONFIG
        self.defaults = TRACKER_DEFAULTS.copy()

    def get_config_dict(self) -> dict[str, Any]:
        """Get tracker configuration as dictionary."""
        return self.defaults.copy()

    def create_config_file(self, output_path: str | None = None) -> Path:
        """Create ByteTrack YAML config file."""
        path = Path(output_path) if output_path else Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(BYTE_TRACK_CONFIG_CONTENT)
        return path

    def update_config(self, **kwargs) -> None:
        """Update tracker configuration."""
        self.defaults.update(kwargs)
        self._regenerate_config()

    def _regenerate_config(self) -> None:
        """Regenerate config file with current settings."""
        lines = [
            "# ByteTrack configuration for SIH Part 1",
            "tracker_type: bytetrack",
        ]
        for key, value in self.defaults.items():
            lines.append(f"{key}: {value}")
        content = "\n".join(lines) + "\n"
        Path(self.config_path).write_text(content)


def get_tracker_wrapper(config_path: str | None = None) -> ByteTrackWrapper:
    """Factory function to create ByteTrackWrapper."""
    return ByteTrackWrapper(config_path)


def format_tracking_output(result: TrackingResult) -> list[dict[str, Any]]:
    """Format tracking result for Part 2 consumption."""
    return result.to_list()


def filter_person_tracks(
    tracks: list[TrackedCustomer],
    person_class: str = "person"
) -> list[TrackedCustomer]:
    """Filter tracks to only person class."""
    return [t for t in tracks if t.class_name == person_class]
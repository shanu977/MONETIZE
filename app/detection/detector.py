"""YOLO11 Detection Module - Person detection for SIH Part 1."""

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO
from ultralytics.utils import LOGGER

from app.config import (
    MODEL_PATH,
    ENABLE_GPU,
    CONF_THRESHOLD,
    IOU_THRESHOLD,
    MAX_DET,
    PERSON_CLASS_ID,
    PERSON_CLASS_NAME,
    TRACKER_CONFIG,
    TRACK_ARGS,
)
from app.models.tracking_data import BoundingBox, TrackedCustomer, TrackingResult


class PersonDetector:
    """YOLO11-based person detector with ByteTrack integration."""

    def __init__(
        self,
        model_path: str = MODEL_PATH,
        enable_gpu: bool = ENABLE_GPU,
        conf_threshold: float = CONF_THRESHOLD,
        iou_threshold: float = IOU_THRESHOLD,
        max_det: int = MAX_DET,
        tracker_config: str = TRACKER_CONFIG,
        track_args: dict[str, Any] | None = None,
        person_class_id: int = PERSON_CLASS_ID,
    ):
        self.model_path = model_path
        self.enable_gpu = enable_gpu
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.max_det = max_det
        self.tracker_config = tracker_config
        self.track_args = track_args or TRACK_ARGS
        self.person_class_id = person_class_id

        self.model: YOLO | None = None
        self.class_names: dict[int, str] = {}
        self._initialize_model()

    def _initialize_model(self) -> None:
        """Initialize YOLO model."""
        LOGGER.info(f"🚀 Initializing model: {self.model_path}")
        if self.enable_gpu:
            LOGGER.info("Using GPU...")
            self.model = YOLO(self.model_path)
            self.model.to("cuda")
        else:
            LOGGER.info("Using CPU...")
            self.model = YOLO(self.model_path, task="detect")

        self.class_names = self.model.names
        LOGGER.info(f"Model classes: {self.class_names}")

    def detect_and_track(self, frame: np.ndarray) -> TrackingResult:
        """
        Run YOLO detection + ByteTrack tracking on a frame.
        Returns only person detections as TrackedCustomer objects.
        """
        if self.model is None:
            raise RuntimeError("Model not initialized")

        results = self.model.track(
            frame,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            max_det=self.max_det,
            tracker=self.tracker_config,
            classes=[self.person_class_id],
            **self.track_args,
        )

        return self._process_results(results[0], frame.shape)

    def _process_results(self, result, frame_shape: tuple) -> TrackingResult:
        """Process YOLO tracking results into TrackedCustomer objects."""
        customers: list[TrackedCustomer] = []

        if result.boxes is None or len(result.boxes) == 0:
            return TrackingResult(customers=customers)

        boxes = result.boxes

        for i in range(len(boxes)):
            box = boxes[i]
            xyxy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], 'cpu') else box.xyxy[0].numpy()
            x1, y1, x2, y2 = map(int, xyxy)

            track_id = int(box.id[0].cpu().numpy()) if box.id is not None and hasattr(box.id[0], 'cpu') else \
                       int(box.id[0].numpy()) if box.id is not None else -1

            if track_id == -1:
                continue

            conf = float(box.conf[0].cpu().numpy()) if hasattr(box.conf[0], 'cpu') else \
                   float(box.conf[0].numpy()) if box.conf is not None else 0.0

            class_id = int(box.cls[0].cpu().numpy()) if hasattr(box.cls[0], 'cpu') else \
                       int(box.cls[0].numpy()) if box.cls is not None else self.person_class_id

            class_name = self.class_names.get(class_id, PERSON_CLASS_NAME)

            if class_name != PERSON_CLASS_NAME:
                continue

            bbox = BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)
            customer = TrackedCustomer.create(
                track_id=track_id,
                class_name=class_name,
                bbox=bbox,
                confidence=conf,
            )
            customers.append(customer)

        return TrackingResult(customers=customers)

    def detect_only(self, frame: np.ndarray) -> list[BoundingBox]:
        """Run detection only (no tracking) - returns person bounding boxes."""
        if self.model is None:
            raise RuntimeError("Model not initialized")

        results = self.model(
            frame,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            max_det=self.max_det,
            classes=[self.person_class_id],
            verbose=False,
        )

        bboxes: list[BoundingBox] = []
        if results[0].boxes is not None:
            for box in results[0].boxes:
                xyxy = box.xyxy[0].cpu().numpy() if hasattr(box.xyxy[0], 'cpu') else box.xyxy[0].numpy()
                x1, y1, x2, y2 = map(int, xyxy)
                bboxes.append(BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2))

        return bboxes


def get_detector(**kwargs) -> PersonDetector:
    """Factory function to create a PersonDetector with default config."""
    return PersonDetector(**kwargs)
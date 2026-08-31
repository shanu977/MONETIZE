"""Tests for tracking data models."""

import pytest
from datetime import datetime

from app.models.tracking_data import BoundingBox, TrackedCustomer, TrackingResult


class TestBoundingBox:
    def test_bbox_creation(self):
        bbox = BoundingBox(x1=100, y1=50, x2=200, y2=150)
        assert bbox.x1 == 100
        assert bbox.y1 == 50
        assert bbox.x2 == 200
        assert bbox.y2 == 150

    def test_bbox_center(self):
        bbox = BoundingBox(x1=100, y1=50, x2=200, y2=150)
        center = bbox.center
        assert center == (150, 100)

    def test_bbox_width_height(self):
        bbox = BoundingBox(x1=100, y1=50, x2=200, y2=150)
        assert bbox.width == 100
        assert bbox.height == 100

    def test_bbox_to_list(self):
        bbox = BoundingBox(x1=100, y1=50, x2=200, y2=150)
        assert bbox.to_list() == [100, 50, 200, 150]


class TestTrackedCustomer:
    def test_customer_creation(self):
        bbox = BoundingBox(x1=100, y1=50, x2=200, y2=150)
        customer = TrackedCustomer.create(
            track_id=1,
            class_name="person",
            bbox=bbox,
            confidence=0.9
        )

        assert customer.track_id == 1
        assert customer.customer_id == "Customer_001"
        assert customer.class_name == "person"
        assert customer.bbox == bbox
        assert customer.center == (150, 100)
        assert customer.confidence == 0.9
        assert "T" in customer.timestamp  # ISO format

    def test_customer_to_dict(self):
        bbox = BoundingBox(x1=100, y1=50, x2=200, y2=150)
        customer = TrackedCustomer.create(
            track_id=2,
            class_name="person",
            bbox=bbox,
            confidence=0.85
        )

        d = customer.to_dict()
        assert d["track_id"] == 2
        assert d["customer_id"] == "Customer_002"
        assert d["bbox"] == [100, 50, 200, 150]
        assert d["center"] == [150, 100]
        assert d["confidence"] == 0.85

    def test_customer_to_part2_format(self):
        bbox = BoundingBox(x1=100, y1=50, x2=200, y2=150)
        customer = TrackedCustomer.create(
            track_id=3,
            class_name="person",
            bbox=bbox
        )

        d = customer.to_part2_format()
        assert "track_id" in d
        assert "customer_id" in d
        assert "bbox" in d
        assert "center" in d
        assert "timestamp" in d
        assert "confidence" not in d  # Part 2 format excludes confidence


class TestTrackingResult:
    def test_empty_result(self):
        result = TrackingResult()
        assert result.customers == []
        assert result.to_list() == []

    def test_result_with_customers(self):
        bbox1 = BoundingBox(x1=100, y1=50, x2=200, y2=150)
        bbox2 = BoundingBox(x1=300, y1=100, x2=400, y2=250)

        c1 = TrackedCustomer.create(1, "person", bbox1)
        c2 = TrackedCustomer.create(2, "person", bbox2)

        result = TrackingResult(customers=[c1, c2])
        assert len(result.customers) == 2

        part2_list = result.to_list()
        assert len(part2_list) == 2
        assert part2_list[0]["customer_id"] == "Customer_001"
        assert part2_list[1]["customer_id"] == "Customer_002"

    def test_get_customer(self):
        bbox = BoundingBox(x1=100, y1=50, x2=200, y2=150)
        customer = TrackedCustomer.create(5, "person", bbox)
        result = TrackingResult(customers=[customer])

        found = result.get_customer(5)
        assert found is not None
        assert found.track_id == 5

        not_found = result.get_customer(999)
        assert not_found is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
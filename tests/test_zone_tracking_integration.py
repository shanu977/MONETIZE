"""Tests for Phase 2.5 — Tracking + Zone Integration."""
import json
from pathlib import Path

import pytest
import numpy as np
from PIL import Image

from app.phase2.maps.manager import MapManager
from app.phase2.zones.manager import ZoneManager
from app.phase2.calibration.homography import HomographyCalibrator
from app.phase2.calibration.store import save_calibration
from app.phase2.zones.engine import ZoneEngine
from app.phase2.integration import ZoneTrackingIntegrator
from app.phase2.integration.models import CustomerZoneResult
from app.models.tracking_data import BoundingBox, TrackedCustomer, TrackingResult


def make_image(path: Path, size, color=(200, 210, 220)):
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def create_map(tmp_path: Path, size=(800, 600), name="TestMap"):
    maps_dir = tmp_path / "maps"
    m = MapManager(maps_dir)
    src = tmp_path / f"src_{name.replace(' ','_')}.png"
    make_image(src, size)
    meta = m.upload_map(src, name=name)
    return m, meta, maps_dir


def create_calibration(tmp_path: Path, map_id: str, camera_id: str = "default_camera",
                       cam_size=(640, 480), map_size=(800, 600), calib_dir=None):
    """Create a simple 1:1-ish calibration (cctv quad -> map quad) and save."""
    if calib_dir is None:
        calib_dir = tmp_path / "calibration"
    calib = HomographyCalibrator()
    cam_w, cam_h = cam_size
    map_w, map_h = map_size
    # Simple full-frame mapping: cctv (0,0)-(cam_w,cam_h) -> map (0,0)-(map_w,map_h)
    calib.cctv_points = [[0, 0], [cam_w, 0], [cam_w, cam_h], [0, cam_h]]
    calib.map_points = [[0, 0], [map_w, 0], [map_w, map_h], [0, map_h]]
    # Use calibrator to compute homography
    c = HomographyCalibrator()
    c.cctv_points = [[0, 0], [cam_w, 0], [cam_w, cam_h], [0, cam_h]]
    c.map_points = [[0, 0], [map_w, 0], [map_w, map_h], [0, map_h]]
    result = c.calibrate(camera_id=camera_id, map_id=map_id, camera_resolution=cam_size)
    data = c.to_dict()
    save_calibration(data, calib_dir)
    return data, calib_dir


def create_tracked_customer(track_id: int, bbox: tuple[int, int, int, int]) -> TrackedCustomer:
    bb = BoundingBox(*bbox)
    return TrackedCustomer.create(track_id=track_id, class_name="person", bbox=bb, confidence=0.9)


# ── Test 1 — Single customer ──────────────────────────────────────────

class TestSingleCustomer:
    def test_single_customer_inside_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Zone A", (100, 100), (500, 400))
        create_calibration(tmp_path, meta["map_id"], cam_size=(640, 480), map_size=(800, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], camera_id="default_camera",
                                            zones_dir=tmp_path / "zones", maps_dir=maps_dir,
                                            calibration_dir=tmp_path / "calibration")
        # Customer camera bottom-center (320,400) -> map (400,500) inside Zone A? Let's use identity scaled: 320*800/640=400, 400*600/480=500 -> outside A (y 500 >400)
        # So pick camera (160,160) -> map (200,200) inside
        result = integrator.process_customer(customer_id=1, camera_position=(160, 160))
        assert result.zone_name == "Zone A"
        assert result.zone_id is not None
        assert result.map_position is not None
        assert result.camera_position == (160.0, 160.0)
        assert result.map_id == meta["map_id"]


# ── Test 2 — Customer outside zone ────────────────────────────────────

class TestOutsideZone:
    def test_customer_outside_all_zones(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Zone A", (100, 100), (200, 200))
        create_calibration(tmp_path, meta["map_id"], cam_size=(640, 480), map_size=(800, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        # Camera (10,10) -> map (12.5,12.5) outside
        result = integrator.process_customer(customer_id=1, camera_position=(10, 10))
        assert result.zone_id is None and result.zone_name is None
        assert result.map_position is not None


# ── Test 3 — Multiple customers ───────────────────────────────────────

class TestMultipleCustomers:
    def test_multiple_customers_independent(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (1000, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Entrance", (0, 0), (250, 600))
        zm.create_rectangle(meta["map_id"], "Billing", (250, 0), (500, 600))
        zm.create_rectangle(meta["map_id"], "Electronics", (500, 0), (750, 600))
        create_calibration(tmp_path, meta["map_id"], cam_size=(1000, 600), map_size=(1000, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        # Map and cam same size, so positions equal
        customers = [
            create_tracked_customer(1, (50, 100, 150, 300)),   # bottom-center (100,300) -> Entrance
            create_tracked_customer(2, (250, 100, 350, 300)),  # (300,300) -> Billing
            create_tracked_customer(3, (550, 100, 650, 300)),  # (600,300) -> Electronics
            create_tracked_customer(4, (800, 100, 900, 300)),  # (850,300) -> None
        ]
        results = integrator.process_tracked_customers(customers)
        assert results[0].zone_name == "Entrance"
        assert results[1].zone_name == "Billing"
        assert results[2].zone_name == "Electronics"
        assert results[3].zone_name is None

    def test_batch_via_tracking_result(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Entrance", (0, 0), (400, 600))
        zm.create_rectangle(meta["map_id"], "Billing", (400, 0), (800, 600))
        create_calibration(tmp_path, meta["map_id"], cam_size=(800, 600), map_size=(800, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        c1 = create_tracked_customer(1, (100, 100, 200, 300))  # (150,300) Entrance
        c2 = create_tracked_customer(2, (500, 100, 600, 300))  # (550,300) Billing
        tr = TrackingResult(customers=[c1, c2])
        results = integrator.process_customers(tr)
        assert len(results) == 2
        assert results[0].zone_name == "Entrance"
        assert results[1].zone_name == "Billing"


# ── Test 4 — Map isolation ────────────────────────────────────────────

class TestMapIsolation:
    def test_map_isolation(self, tmp_path):
        maps_dir = tmp_path / "maps"
        m = MapManager(maps_dir)
        srcA = tmp_path / "srcA.png"
        make_image(srcA, (800, 600))
        metaA = m.upload_map(srcA, name="MapA")
        srcB = tmp_path / "srcB.png"
        make_image(srcB, (800, 600))
        metaB = m.upload_map(srcB, name="MapB")
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(metaA["map_id"], "Zone A1", (0, 0), (100, 100))
        zm.create_rectangle(metaB["map_id"], "Zone B1", (500, 500), (600, 600))
        create_calibration(tmp_path, metaA["map_id"], cam_size=(800, 600), map_size=(800, 600))
        create_calibration(tmp_path, metaB["map_id"], cam_size=(800, 600), map_size=(800, 600))
        intA = ZoneTrackingIntegrator(map_id=metaA["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        intB = ZoneTrackingIntegrator(map_id=metaB["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        # Same camera point (50,50) -> map (50,50) -> A1 for A, but B should be outside (since B1 at 500,500)
        assert intA.process_customer(1, (50, 50)).zone_name == "Zone A1"
        assert intB.process_customer(1, (50, 50)).zone_name is None
        assert intB.process_customer(2, (550, 550)).zone_name == "Zone B1"
        assert intA.process_customer(2, (550, 550)).zone_name is None


# ── Test 5 — Missing calibration ──────────────────────────────────────

class TestMissingCalibration:
    def test_missing_calibration(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (0, 0), (100, 100))
        # No calibration created
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        assert integrator.is_calibrated is False
        result = integrator.process_customer(1, (50, 50))
        assert result.map_position is None
        assert result.zone_id is None
        # Should not crash for batch
        c = create_tracked_customer(1, (0, 0, 100, 100))
        results = integrator.process_tracked_customers([c])
        assert results[0].map_position is None


# ── Test 6 — Invalid calibration ──────────────────────────────────────

class TestInvalidCalibration:
    def test_invalid_calibration(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (0, 0), (100, 100))
        calib_dir = tmp_path / "calibration"
        calib_dir.mkdir(parents=True, exist_ok=True)
        # Write malformed calibration (missing homography)
        bad = {"camera_id": "default_camera", "map_id": meta["map_id"], "camera_resolution": [640, 480]}
        (calib_dir / f"calibration_default_camera__{meta['map_id']}.json").write_text(json.dumps(bad))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=calib_dir)
        assert integrator.is_calibrated is False
        result = integrator.process_customer(1, (50, 50))
        assert result.map_position is None
        assert result.zone_id is None

    def test_malformed_homography(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (0, 0), (100, 100))
        calib_dir = tmp_path / "calibration"
        calib_dir.mkdir(parents=True, exist_ok=True)
        bad = {"camera_id": "default_camera", "map_id": meta["map_id"], "homography_matrix": [[1, 0], [0, 1]], "camera_resolution": [640, 480]}
        (calib_dir / f"calibration_default_camera__{meta['map_id']}.json").write_text(json.dumps(bad))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=calib_dir)
        assert integrator.is_calibrated is False
        assert integrator.process_customer(1, (10, 10)).zone_id is None


# ── Test 7 — Boundary ─────────────────────────────────────────────────

class TestBoundary:
    def test_boundary_as_inside(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (100, 100), (300, 300))
        create_calibration(tmp_path, meta["map_id"], cam_size=(800, 600), map_size=(800, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        # Edge and corner should be inside per ZoneEngine boundary rule
        for pt in [(100, 100), (300, 100), (300, 300), (100, 300), (200, 100), (100, 200)]:
            assert integrator.process_customer(1, pt).zone_id is not None, f"Boundary {pt} should be inside"


# ── Test 8 — Multiple frames same customer ────────────────────────────

class TestMultipleFrames:
    def test_same_customer_across_frames(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Zone A", (0, 0), (400, 600))
        create_calibration(tmp_path, meta["map_id"], cam_size=(800, 600), map_size=(800, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        # Same track_id 5 across 3 frames at same position
        for frame in range(3):
            c = create_tracked_customer(5, (100, 100, 200, 300))  # bottom-center (150,300) inside Zone A
            result = integrator.process_tracked_customer(c)
            assert result.customer_id == "Customer_005"
            assert result.track_id == 5
            assert result.zone_name == "Zone A"
        # Should not generate ENTER/EXIT — just current zone each frame


# ── Test 9 — Customer IDs preserved ───────────────────────────────────

class TestCustomerIDs:
    def test_bytetrack_id_preserved(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (0, 0), (100, 100))
        create_calibration(tmp_path, meta["map_id"], cam_size=(800, 600), map_size=(800, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        c = create_tracked_customer(42, (10, 10, 50, 50))
        result = integrator.process_tracked_customer(c)
        assert result.customer_id == "Customer_042"
        assert result.track_id == 42
        assert result.zone_name == "R"
        # Direct process_customer preserves id
        r2 = integrator.process_customer(customer_id=42, camera_position=(20, 20))
        assert r2.customer_id == 42


# ── Test 10 — No YOLO dependency ──────────────────────────────────────

class TestNoYOLODependency:
    def test_no_yolo_needed(self):
        import subprocess, sys
        code = "import sys; from app.phase2.integration import ZoneTrackingIntegrator; assert 'ultralytics' not in sys.modules"
        import subprocess as sp
        r = sp.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


# ── Additional: bottom-center, map isolation via integrator, performance ─

class TestIntegrationDetails:
    def test_bottom_center_used(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Zone at bottom area y 400-600
        zm.create_rectangle(meta["map_id"], "BottomZone", (0, 400), (800, 600))
        create_calibration(tmp_path, meta["map_id"], cam_size=(640, 480), map_size=(800, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        # Bbox (0,0,100,100) bottom-center (50,100) -> map (62.5,125) outside bottom zone
        c1 = create_tracked_customer(1, (0, 0, 100, 100))
        assert integrator.process_tracked_customer(c1).zone_id is None
        # Bbox (0,300,100,400) bottom-center (50,400) -> map (62.5,500) inside bottom zone
        c2 = create_tracked_customer(2, (0, 300, 100, 400))
        # Note: 400 in cam 480 -> map 500
        assert integrator.process_tracked_customer(c2).zone_name == "BottomZone"

    def test_outside_all_zones_valid_state(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (100, 100), (200, 200))
        create_calibration(tmp_path, meta["map_id"], cam_size=(800, 600), map_size=(800, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        result = integrator.process_customer(1, (500, 500))
        assert result.zone_id is None and result.zone_name is None
        assert result.map_position is not None  # valid transform but outside

    def test_batch_and_single_consistency(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (0, 0), (400, 600))
        create_calibration(tmp_path, meta["map_id"], cam_size=(800, 600), map_size=(800, 600))
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        c1 = create_tracked_customer(1, (100, 100, 200, 300))
        c2 = create_tracked_customer(2, (500, 100, 600, 300))
        batch = integrator.process_customers(TrackingResult(customers=[c1, c2]))
        single1 = integrator.process_tracked_customer(c1)
        single2 = integrator.process_tracked_customer(c2)
        assert batch[0].zone_id == single1.zone_id
        assert batch[1].zone_id == single2.zone_id

    def test_performance_caching(self, tmp_path):
        # Ensure no per-frame reload: homography and zones cached
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (0, 0), (100, 100))
        create_calibration(tmp_path, meta["map_id"])
        integrator = ZoneTrackingIntegrator(map_id=meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir, calibration_dir=tmp_path / "calibration")
        h1 = integrator.homography.copy() if integrator.homography is not None else None
        zc1 = integrator.zone_engine.zone_count
        # Process many customers - should not reload
        for i in range(10):
            integrator.process_customer(i, (10, 10))
        assert np.array_equal(integrator.homography, h1) if h1 is not None else True
        assert integrator.zone_engine.zone_count == zc1

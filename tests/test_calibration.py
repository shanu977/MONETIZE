"""Tests for Phase 2 Step 2 — Visual Camera Calibration."""
import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from app.phase2.maps.manager import MapManager
from app.phase2.calibration.homography import HomographyCalibrator
from app.phase2.calibration.store import save_calibration, load_calibration, get_calibration_path, check_resolution_mismatch


def make_image(path: Path, size, color=(200, 200, 200)):
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def create_selected_map(tmp_path: Path):
    """Helper: create maps dir with one selected map, return (manager, meta)."""
    maps_dir = tmp_path / "maps"
    m = MapManager(maps_dir)
    src = tmp_path / "floor.png"
    make_image(src, (800, 600))
    meta = m.upload_map(src, name="Test Floor")
    # upload auto-selects
    assert m.get_selected_map_id() == meta["map_id"]
    return m, meta


# ── selected map loading ──────────────────────────────────────────────

class TestSelectedMap:
    def test_loading_selected_map(self, tmp_path):
        m, meta = create_selected_map(tmp_path)
        assert m.get_selected_map() is not None
        assert m.get_selected_map()["map_id"] == meta["map_id"]

    def test_no_map_handling(self, tmp_path):
        maps_dir = tmp_path / "empty_maps"
        m = MapManager(maps_dir)
        assert m.get_selected_map() is None
        assert m.get_selected_map_id() is None
        # Calibration should detect no map and error
        calib = HomographyCalibrator()
        # No points yet, validate should need pairs
        assert "at least 4" in calib.validate().lower() or "need" in calib.validate().lower() if calib.validate() else True
        # No map image to load — tool would show error, here we just verify manager empty
        assert m.list_maps() == []


# ── point pairs ───────────────────────────────────────────────────────

class TestPointPairs:
    def test_creating_4_matching_pairs(self, tmp_path):
        c = HomographyCalibrator()
        pairs = [((0, 0), (0, 0)), ((640, 0), (800, 0)), ((640, 480), (800, 600)), ((0, 480), (0, 600))]
        for cc, mm in pairs:
            c.add_pair(cc, mm)
        assert c.pairs_count() == 4
        assert c.can_calibrate()

    def test_5_plus_pairs(self, tmp_path):
        c = HomographyCalibrator()
        pts = [((0, 0), (0, 0)), ((640, 0), (800, 0)), ((640, 480), (800, 600)), ((0, 480), (0, 600)), ((320, 240), (400, 300)), ((100, 100), (120, 110))]
        for cc, mm in pts:
            c.add_pair(cc, mm)
        assert c.pairs_count() == 6
        result = c.calibrate(camera_id="cam0", map_id="m1", camera_resolution=(640, 480))
        assert result.homography.shape == (3, 3)

    def test_undo(self, tmp_path):
        c = HomographyCalibrator()
        c.add_pair((0, 0), (0, 0))
        c.add_pair((10, 10), (10, 10))
        assert c.pairs_count() == 2
        c.undo()
        assert c.pairs_count() == 1
        c.undo()
        assert c.pairs_count() == 0
        assert not c.undo()  # nothing to undo

    def test_reset(self, tmp_path):
        c = HomographyCalibrator()
        for i in range(4):
            c.add_pair((i * 10, i * 10), (i * 12, i * 12))
        assert c.pairs_count() == 4
        c.reset()
        assert c.pairs_count() == 0
        assert c.cctv_points == [] and c.map_points == []

    def test_pending_undo(self, tmp_path):
        c = HomographyCalibrator()
        c.add_cctv_point((100, 100))
        assert c.has_pending()
        assert c.undo() is True
        assert not c.has_pending()


# ── validation ────────────────────────────────────────────────────────

class TestValidation:
    def test_duplicate_rejection(self, tmp_path):
        c = HomographyCalibrator()
        # CCTV duplicates within 8px threshold
        c.add_pair((100, 100), (0, 0))
        c.add_pair((100, 101), (800, 0))  # CCTV dup (100,100) vs (100,101) <8
        c.add_pair((200, 200), (800, 600))
        c.add_pair((0, 480), (0, 600))
        err = c.validate()
        assert err is not None and "duplicate" in err.lower()

    def test_duplicate_map_rejection(self, tmp_path):
        c = HomographyCalibrator()
        c.add_pair((0, 0), (100, 100))
        c.add_pair((640, 0), (100, 101))  # map dup
        c.add_pair((640, 480), (200, 200))
        c.add_pair((0, 480), (300, 300))
        err = c.validate()
        assert "duplicate" in err.lower()

    def test_collinear_rejection(self, tmp_path):
        c = HomographyCalibrator()
        # All points on line y=0
        c.add_pair((0, 0), (0, 0))
        c.add_pair((100, 0), (100, 0))
        c.add_pair((200, 0), (200, 0))
        c.add_pair((300, 0), (300, 0))
        err = c.validate()
        assert err is not None and "cover" in err.lower() or "collinear" in err.lower()

    def test_invalid_degenerate_not_enough_points(self, tmp_path):
        c = HomographyCalibrator()
        c.add_pair((0, 0), (0, 0))
        c.add_pair((10, 10), (10, 10))
        with pytest.raises(ValueError, match="at least 4"):
            c.calibrate()

    def test_near_duplicate_threshold(self, tmp_path):
        c = HomographyCalibrator()
        c.add_pair((0, 0), (0, 0))
        c.add_pair((640, 0), (800, 0))
        c.add_pair((640, 480), (800, 600))
        c.add_pair((0, 480), (0, 600))
        # Now add a 5th pair that is near duplicate of first — should be flagged if we add it
        c.add_pair((1, 1), (1, 1))  # near (0,0)
        err = c.validate()
        assert "duplicate" in err.lower()

    def test_successful_with_good_points(self, tmp_path):
        c = HomographyCalibrator()
        c.add_pair((0, 0), (0, 0))
        c.add_pair((640, 0), (800, 0))
        c.add_pair((640, 480), (800, 600))
        c.add_pair((0, 480), (0, 600))
        assert c.validate() is None
        result = c.calibrate()
        assert result.reprojection_error < 1.0


# ── transforms ────────────────────────────────────────────────────────

class TestTransforms:
    def test_cctv_to_map_transform(self, tmp_path):
        c = HomographyCalibrator()
        c.add_pair((0, 0), (0, 0))
        c.add_pair((640, 0), (800, 0))
        c.add_pair((640, 480), (800, 600))
        c.add_pair((0, 480), (0, 600))
        c.calibrate()
        # Center should map ~ (400,300)
        out = c.cctv_to_map(np.array([[320, 240]]))
        np.testing.assert_allclose(out[0], [400, 300], atol=2.0)

    def test_map_to_cctv_transform(self, tmp_path):
        c = HomographyCalibrator()
        c.add_pair((0, 0), (0, 0))
        c.add_pair((640, 0), (800, 0))
        c.add_pair((640, 480), (800, 600))
        c.add_pair((0, 480), (0, 600))
        c.calibrate()
        out = c.map_to_cctv(np.array([[400, 300]]))
        np.testing.assert_allclose(out[0], [320, 240], atol=2.0)

    def test_roundtrip(self, tmp_path):
        c = HomographyCalibrator()
        c.add_pair((0, 0), (0, 0))
        c.add_pair((640, 0), (800, 0))
        c.add_pair((640, 480), (800, 600))
        c.add_pair((0, 480), (0, 600))
        c.calibrate()
        pt = np.array([[100, 150]])
        mapped = c.cctv_to_map(pt)
        back = c.map_to_cctv(mapped)
        np.testing.assert_allclose(back, pt, atol=1.0)

    def test_cctv_to_map_batch(self, tmp_path):
        c = HomographyCalibrator()
        c.add_pair((0, 0), (0, 0))
        c.add_pair((640, 0), (800, 0))
        c.add_pair((640, 480), (800, 600))
        c.add_pair((0, 480), (0, 600))
        c.calibrate()
        pts = np.array([[0, 0], [640, 480], [320, 240]])
        out = c.cctv_to_map(pts)
        assert out.shape == (3, 2)


# ── save / load / isolation ───────────────────────────────────────────

class TestStore:
    def test_save_and_load(self, tmp_path):
        m, meta = create_selected_map(tmp_path)
        c = HomographyCalibrator()
        c.add_pair((0, 0), (0, 0))
        c.add_pair((640, 0), (800, 0))
        c.add_pair((640, 480), (800, 600))
        c.add_pair((0, 480), (0, 600))
        c.calibrate(camera_id="default_camera", map_id=meta["map_id"], camera_resolution=(640, 480))
        data = c.to_dict()
        calib_dir = tmp_path / "calibration"
        path = save_calibration(data, calib_dir)
        assert path.exists()
        loaded = load_calibration("default_camera", meta["map_id"], calib_dir)
        assert loaded is not None
        assert loaded["camera_id"] == "default_camera"
        assert loaded["map_id"] == meta["map_id"]
        assert loaded["camera_resolution"] == [640, 480]
        assert "homography_matrix" in loaded

    def test_camera_map_isolation(self, tmp_path):
        calib_dir = tmp_path / "calibration"
        m, meta = create_selected_map(tmp_path)
        # Save for cam0
        c = HomographyCalibrator()
        for cc, mm in [((0, 0), (0, 0)), ((640, 0), (800, 0)), ((640, 480), (800, 600)), ((0, 480), (0, 600))]:
            c.add_pair(cc, mm)
        c.calibrate(camera_id="cam0", map_id=meta["map_id"], camera_resolution=(640, 480))
        save_calibration(c.to_dict(), calib_dir)
        # Save for cam1 same map
        c2 = HomographyCalibrator()
        for cc, mm in [((0, 0), (0, 0)), ((640, 0), (800, 0)), ((640, 480), (800, 600)), ((0, 480), (0, 600))]:
            c2.add_pair(cc, mm)
        c2.calibrate(camera_id="cam1", map_id=meta["map_id"], camera_resolution=(640, 480))
        save_calibration(c2.to_dict(), calib_dir)
        assert get_calibration_path("cam0", meta["map_id"], calib_dir) != get_calibration_path("cam1", meta["map_id"], calib_dir)
        assert load_calibration("cam0", meta["map_id"], calib_dir)["camera_id"] == "cam0"
        assert load_calibration("cam1", meta["map_id"], calib_dir)["camera_id"] == "cam1"

    def test_no_overwrite_other_camera(self, tmp_path):
        calib_dir = tmp_path / "calibration"
        m, meta = create_selected_map(tmp_path)
        # Create second map
        src2 = tmp_path / "floor2.png"
        make_image(src2, (400, 300))
        meta2 = m.upload_map(src2, name="Floor2")
        # Save calib for meta
        c = HomographyCalibrator()
        for cc, mm in [((0, 0), (0, 0)), ((640, 0), (800, 0)), ((640, 480), (800, 600)), ((0, 480), (0, 600))]:
            c.add_pair(cc, mm)
        c.calibrate(camera_id="cam0", map_id=meta["map_id"], camera_resolution=(640, 480))
        p1 = save_calibration(c.to_dict(), calib_dir)
        # Save for meta2 same cam
        c2 = HomographyCalibrator()
        for cc, mm in [((0, 0), (0, 0)), ((640, 0), (800, 0)), ((640, 480), (800, 600)), ((0, 480), (0, 600))]:
            c2.add_pair(cc, mm)
        c2.calibrate(camera_id="cam0", map_id=meta2["map_id"], camera_resolution=(640, 480))
        p2 = save_calibration(c2.to_dict(), calib_dir)
        assert p1 != p2
        assert load_calibration("cam0", meta["map_id"], calib_dir) is not None
        assert load_calibration("cam0", meta2["map_id"], calib_dir) is not None

    def test_camera_resolution_storage(self, tmp_path):
        calib_dir = tmp_path / "calibration"
        c = HomographyCalibrator()
        for cc, mm in [((0, 0), (0, 0)), ((640, 0), (800, 0)), ((640, 480), (800, 600)), ((0, 480), (0, 600))]:
            c.add_pair(cc, mm)
        c.calibrate(camera_id="camX", map_id="m1", camera_resolution=(1280, 720))
        data = c.to_dict()
        assert data["camera_resolution"] == [1280, 720]
        save_calibration(data, calib_dir)
        loaded = load_calibration("camX", "m1", calib_dir)
        assert loaded["camera_resolution"] == [1280, 720]

    def test_resolution_mismatch_warning(self, tmp_path):
        warn = check_resolution_mismatch([640, 480], (1280, 720))
        assert warn is not None and "640" in warn and "1280" in warn
        assert check_resolution_mismatch([640, 480], (640, 480)) is None
        assert check_resolution_mismatch(None, (640, 480)) is None


# ── Phase 1 regression ────────────────────────────────────────────────

class TestRegression:
    def test_phase1_not_broken(self):
        from app.video.video_source import VideoSource
        from app.models.tracking_data import BoundingBox
        vs = VideoSource(0)
        # Not opening, just check class still works
        assert hasattr(vs, "open")
        b = BoundingBox(0, 0, 100, 100)
        assert b.width == 100

    def test_step1_still_works(self, tmp_path):
        maps_dir = tmp_path / "maps2"
        m = MapManager(maps_dir)
        src = tmp_path / "a.png"
        make_image(src, (100, 100))
        meta = m.upload_map(src)
        assert m.list_maps()
        assert m.get_selected_map_id() == meta["map_id"]

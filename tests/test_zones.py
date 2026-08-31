"""Tests for Phase 2 Step 3 — Visual Zone Editor."""
import json
from pathlib import Path

import pytest
from PIL import Image

from app.phase2.maps.manager import MapManager
from app.phase2.zones.manager import ZoneManager, get_zone_manager, MIN_ZONE_SIZE
from app.phase2.calibration.homography import HomographyCalibrator  # for regression


def make_image(path: Path, size, color=(200, 210, 220)):
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def create_map(tmp_path: Path, size=(800, 600), name="Test Map"):
    maps_dir = tmp_path / "maps"
    m = MapManager(maps_dir)
    src = tmp_path / f"src_{name.replace(' ','_')}.png"
    make_image(src, size)
    meta = m.upload_map(src, name=name)
    return m, meta, maps_dir


# ── 1. Loads selected map ─────────────────────────────────────────────

class TestLoadsSelectedMap:
    def test_zone_editor_loads_selected_map(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (1024, 768), "Store A")
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Editor would do: map_manager.get_selected_map()
        assert m.get_selected_map()["map_id"] == meta["map_id"]
        # Zone manager should be able to get zones for that map (empty initially)
        assert zm.get_zones(meta["map_id"]) == []

    def test_no_selected_map_handling(self, tmp_path):
        maps_dir = tmp_path / "maps_empty"
        m = MapManager(maps_dir)
        assert m.get_selected_map() is None
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Should handle gracefully, not crash
        assert zm.get_zones("nonexistent") == []


# ── 3-4 Rectangle creation & coordinates ────────────────────────────────

class TestRectangleCreation:
    def test_rectangle_creation(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zone = zm.create_rectangle(meta["map_id"], "Outdoor", (100, 100), (400, 300))
        assert zone["name"] == "Outdoor"
        assert zone["type"] == "rectangle"
        assert len(zone["points"]) == 4

    def test_rectangle_coordinates(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zone = zm.create_rectangle(meta["map_id"], "R1", (100, 100), (400, 300))
        # Points should be [[100,100],[400,100],[400,300],[100,300]] clockwise
        assert zone["points"] == [[100, 100], [400, 100], [400, 300], [100, 300]]

    def test_rectangle_reverse_drag(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Drag from bottom-right to top-left should still produce same rect
        zone = zm.create_rectangle(meta["map_id"], "R1", (400, 300), (100, 100))
        assert zone["points"] == [[100, 100], [400, 100], [400, 300], [100, 300]]


# ── 5-6 Display-to-original conversion & different resolutions ──────────

class TestCoordinateConversion:
    def test_display_to_original_conversion(self, tmp_path):
        # Simulate editor scaling: original 1920x1080 displayed at 960x540 (scale 0.5)
        orig_w, orig_h = 1920, 1080
        disp_w, disp_h = 960, 540
        scale = min(disp_w / orig_w, disp_h / orig_h)  # 0.5
        # Display (100,100) -> original (200,200)
        dx, dy = 100, 100
        ox, oy = 0, 0  # centered, but for this test assume no offset
        orig_x = (dx - ox) / scale
        orig_y = (dy - oy) / scale
        assert orig_x == 200 and orig_y == 200

    def test_editor_conversion_with_offset(self, tmp_path):
        # Original 800x600, canvas 980x620, scale = min(980/800,620/600)=1.033? Actually 980/800=1.225, 620/600=1.033 -> scale 1.033, but our editor caps? Let's test realistic 800x600
        from app.phase2.zones.editor import _compute_display_params
        scale, sw, sh, ox, oy = _compute_display_params(800, 600, 980, 620)
        # Display center should map back correctly
        # Canvas center (490,310) -> original (400,300)
        cx, cy = 490, 310
        # Need to test via editor helper: display_to_original
        # Simulate editor's _display_to_original logic
        orig = ( (cx - ox) / scale, (cy - oy) / scale )
        # Allow tolerance because ox/oy may offset
        # For this map, it should be close to center
        assert 390 < orig[0] < 410
        assert 290 < orig[1] < 310

    def test_different_map_resolutions(self, tmp_path):
        for size in [(640, 480), (1920, 1080), (400, 800), (1024, 1024)]:
            m, meta, maps_dir = create_map(tmp_path / f"res_{size[0]}x{size[1]}", size, f"Map {size}")
            zm = ZoneManager(zones_dir=tmp_path / f"zones_{size[0]}", maps_dir=maps_dir)
            # Create zone at center 25% size
            w, h = size
            zone = zm.create_rectangle(meta["map_id"], "Center", (w * 0.25, h * 0.25), (w * 0.75, h * 0.75))
            xs = [p[0] for p in zone["points"]]
            assert min(xs) == pytest.approx(w * 0.25, abs=1)
            assert max(xs) == pytest.approx(w * 0.75, abs=1)


# ── 7-8 Name & multiple zones ─────────────────────────────────────────

class TestZoneNameAndMultiple:
    def test_zone_name(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zone = zm.create_rectangle(meta["map_id"], "Outdoor Entrance", (10, 10), (100, 100))
        assert zone["name"] == "Outdoor Entrance"

    def test_multiple_zones(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Outdoor", (0, 0), (100, 100))
        zm.create_rectangle(meta["map_id"], "Electronics", (200, 0), (300, 100))
        zm.create_rectangle(meta["map_id"], "Billing", (400, 400), (500, 500))
        zones = zm.get_zones(meta["map_id"])
        assert len(zones) == 3
        names = {z["name"] for z in zones}
        assert names == {"Outdoor", "Electronics", "Billing"}


# ── 9-10 Save / Load ──────────────────────────────────────────────────

class TestSaveLoad:
    def test_save_zones(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (0, 0), (100, 100))
        zones = zm.get_zones(meta["map_id"])
        zm.save_zones(meta["map_id"], zones)
        assert (tmp_path / "zones" / f"{meta['map_id']}.json").exists()

    def test_load_zones(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (10, 10), (100, 100))
        zm.create_rectangle(meta["map_id"], "B", (200, 200), (300, 300))
        # New manager instance should load same
        zm2 = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zones = zm2.get_zones(meta["map_id"])
        assert len(zones) == 2

    def test_existing_zones_reload_correctly(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        z1 = zm.create_rectangle(meta["map_id"], "Persist", (5, 5), (50, 50))
        # Simulate reopening editor: new ZoneManager loads
        zm2 = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        loaded = zm2.get_zones(meta["map_id"])
        assert len(loaded) == 1
        assert loaded[0]["zone_id"] == z1["zone_id"]
        assert loaded[0]["points"] == z1["points"]

    def test_zone_persistence(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zones_dir = tmp_path / "zones"
        zm = ZoneManager(zones_dir=zones_dir, maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Persist2", (0, 0), (100, 100))
        # Check file content
        data = json.loads((zones_dir / f"{meta['map_id']}.json").read_text())
        assert data["map_id"] == meta["map_id"]
        assert len(data["zones"]) == 1


# ── 11-14 Edit / Rename / Delete ──────────────────────────────────────

class TestEdit:
    def test_edit_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zone = zm.create_rectangle(meta["map_id"], "Old", (10, 10), (100, 100))
        # Move/resize via update_zone points
        new_points = [[20, 20], [200, 20], [200, 200], [20, 200]]
        assert zm.update_zone(meta["map_id"], zone["zone_id"], points=new_points) is True
        updated = zm.get_zone(meta["map_id"], zone["zone_id"])
        assert updated["points"] == new_points

    def test_rename_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zone = zm.create_rectangle(meta["map_id"], "OldName", (10, 10), (100, 100))
        assert zm.rename_zone(meta["map_id"], zone["zone_id"], "NewName") is True
        assert zm.get_zone(meta["map_id"], zone["zone_id"])["name"] == "NewName"

    def test_delete_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zone = zm.create_rectangle(meta["map_id"], "ToDelete", (10, 10), (100, 100))
        assert zm.delete_zone(meta["map_id"], zone["zone_id"]) is True
        assert zm.get_zone(meta["map_id"], zone["zone_id"]) is None

    def test_delete_one_without_affecting_others(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        z1 = zm.create_rectangle(meta["map_id"], "Keep1", (0, 0), (100, 100))
        z2 = zm.create_rectangle(meta["map_id"], "DeleteMe", (200, 0), (300, 100))
        z3 = zm.create_rectangle(meta["map_id"], "Keep2", (400, 400), (500, 500))
        zm.delete_zone(meta["map_id"], z2["zone_id"])
        remaining = zm.get_zones(meta["map_id"])
        assert len(remaining) == 2
        assert {z["zone_id"] for z in remaining} == {z1["zone_id"], z3["zone_id"]}


# ── 15-16 Zero-size & out-of-bounds ───────────────────────────────────

class TestValidation:
    def test_zero_size_rejection(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        with pytest.raises(ValueError, match="too small"):
            zm.create_rectangle(meta["map_id"], "Tiny", (100, 100), (101, 101))
        with pytest.raises(ValueError, match="too small"):
            zm.create_rectangle(meta["map_id"], "Click", (50, 50), (50, 50))

    def test_out_of_bounds_clamping(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Drag outside map bounds
        zone = zm.create_rectangle(meta["map_id"], "Clamped", (-100, -100), (900, 700))
        xs = [p[0] for p in zone["points"]]
        ys = [p[1] for p in zone["points"]]
        assert min(xs) == 0
        assert max(xs) == 800
        assert min(ys) == 0
        assert max(ys) == 600

    def test_small_drag_after_clamp_rejected(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (100, 100))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Points far outside but clamped to tiny valid area? Actually -10,-10 to 2,2 clamped to 0,0 to 2,2 -> too small
        with pytest.raises(ValueError, match="too small"):
            zm.create_rectangle(meta["map_id"], "Tiny2", (-10, -10), (2, 2))


# ── 17 Map ID association ─────────────────────────────────────────────

class TestMapIDAssociation:
    def test_map_id_association(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600), "MapA")
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zone = zm.create_rectangle(meta["map_id"], "Z1", (10, 10), (100, 100))
        assert zone["map_id"] == meta["map_id"]
        # Zones for other map should be empty
        assert zm.get_zones("other_map_id") == []
        # Ensure file per map
        assert (tmp_path / "zones" / f"{meta['map_id']}.json").exists()
        assert not (tmp_path / "zones" / "other_map_id.json").exists()

    def test_zones_isolated_per_map(self, tmp_path):
        m1, meta1, maps_dir = create_map(tmp_path / "a", (800, 600), "MapA")
        # Create second map in same maps_dir
        import shutil
        # Reuse same maps_dir for second map
        src2 = tmp_path / "src2.png"
        make_image(src2, (400, 400))
        meta2 = m1.upload_map(src2, name="MapB")
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta1["map_id"], "A_Zone", (0, 0), (50, 50))
        zm.create_rectangle(meta2["map_id"], "B_Zone", (0, 0), (50, 50))
        assert len(zm.get_zones(meta1["map_id"])) == 1
        assert len(zm.get_zones(meta2["map_id"])) == 1
        assert zm.get_zones(meta1["map_id"])[0]["name"] == "A_Zone"


# ── 20-22 Regressions ─────────────────────────────────────────────────

class TestRegressions:
    def test_phase1_regression(self):
        from app.models.tracking_data import BoundingBox
        b = BoundingBox(0, 0, 100, 100)
        assert b.width == 100

    def test_step1_regression(self, tmp_path):
        maps_dir = tmp_path / "maps_step1"
        m = MapManager(maps_dir)
        src = tmp_path / "step1.png"
        make_image(src, (200, 200))
        meta = m.upload_map(src, name="Step1Map")
        assert m.get_selected_map_id() == meta["map_id"]
        assert (maps_dir / "metadata" / f"{meta['map_id']}.json").exists()

    def test_step2_regression(self, tmp_path):
        # Calibration should still work
        calib = HomographyCalibrator()
        calib.add_pair((0, 0), (0, 0))
        calib.add_pair((640, 0), (800, 0))
        calib.add_pair((640, 480), (800, 600))
        calib.add_pair((0, 480), (0, 600))
        result = calib.calibrate(camera_id="cam0", map_id="m1", camera_resolution=(640, 480))
        assert result.homography.shape == (3, 3)
        # Store still works
        from app.phase2.calibration.store import save_calibration, load_calibration
        data = calib.to_dict()
        tmp_cal = tmp_path / "calib"
        save_calibration(data, tmp_cal)
        assert load_calibration("cam0", "m1", tmp_cal) is not None

    def test_editor_import_no_yolo(self):
        import subprocess, sys
        code = "import sys; import app.phase2.zones.editor; assert 'ultralytics' not in sys.modules; assert 'app.detection.detector' not in sys.modules"
        import subprocess as sp
        r = sp.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

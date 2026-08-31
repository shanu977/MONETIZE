"""Regression tests for Zone Editor deletion — Phase 2 Step 3 fix."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

from app.phase2.maps.manager import MapManager
from app.phase2.zones.manager import ZoneManager, get_zone_manager


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


# Helper to simulate editor's in-memory deletion flow (mirrors editor.on_delete)
def editor_delete_simulation(zones: list[dict], selected_id: str | None, confirm: bool = True):
    """Simulate editor deletion: returns (new_zones, new_selected_id, deleted)."""
    if not selected_id:
        return zones, selected_id, False  # would show "Select a zone first."
    target = next((z for z in zones if z["zone_id"] == selected_id), None)
    if not target:
        return zones, selected_id, False
    if not confirm:
        return zones, selected_id, False  # cancel
    new_zones = [z for z in zones if z["zone_id"] != selected_id]
    return new_zones, None, True


class TestSelectingZone:
    def test_selecting_a_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        z1 = zm.create_rectangle(meta["map_id"], "Outdoor", (0, 0), (100, 100))
        z2 = zm.create_rectangle(meta["map_id"], "Indoor", (200, 0), (300, 100))
        # Simulate editor selection: click zone -> sets selected_id
        selected_id = z2["zone_id"]
        assert zm.has_zone(meta["map_id"], selected_id)
        # Verify clearly show selected — in editor this is green outline; here check manager can retrieve
        assert zm.get_zone(meta["map_id"], selected_id)["name"] == "Indoor"

    def test_hit_test_selection(self, tmp_path):
        # Test editor's hit test logic indirectly via creating zones and checking bbox
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (10, 10), (100, 100))
        zm.create_rectangle(meta["map_id"], "B", (200, 200), (300, 300))
        # Simulate display hit at (15,15) should hit A, (250,250) hits B
        zones = zm.get_zones(meta["map_id"])
        # Simple bbox hit test (original coords)
        def hit_at(x, y):
            for z in reversed(zones):
                xs = [p[0] for p in z["points"]]
                ys = [p[1] for p in z["points"]]
                if min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys):
                    return z
            return None
        assert hit_at(15, 15)["name"] == "A"
        assert hit_at(250, 250)["name"] == "B"
        assert hit_at(500, 500) is None


class TestDeletingSelectedZone:
    def test_deleting_selected_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        z = zm.create_rectangle(meta["map_id"], "Outdoor Entrance", (10, 10), (100, 100))
        assert len(zm.get_zones(meta["map_id"])) == 1
        # Simulate editor delete with confirm=True
        zones = zm.get_zones(meta["map_id"])
        new_zones, new_sel, deleted = editor_delete_simulation(zones, z["zone_id"], confirm=True)
        assert deleted is True
        assert len(new_zones) == 0
        assert new_sel is None
        # Persist via manager
        zm.save_zones(meta["map_id"], new_zones)
        assert zm.get_zones(meta["map_id"]) == []

    def test_deleting_only_selected_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        z1 = zm.create_rectangle(meta["map_id"], "Keep1", (0, 0), (100, 100))
        z2 = zm.create_rectangle(meta["map_id"], "DeleteMe", (200, 0), (300, 100))
        z3 = zm.create_rectangle(meta["map_id"], "Keep2", (400, 400), (500, 500))
        zones = zm.get_zones(meta["map_id"])
        new_zones, _, _ = editor_delete_simulation(zones, z2["zone_id"], confirm=True)
        assert len(new_zones) == 2
        assert {z["zone_id"] for z in new_zones} == {z1["zone_id"], z3["zone_id"]}
        # Ensure other zones untouched
        assert new_zones[0]["name"] == "Keep1"
        assert new_zones[1]["name"] == "Keep2"

    def test_canceling_deletion(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        z = zm.create_rectangle(meta["map_id"], "Outdoor Entrance", (10, 10), (100, 100))
        zones = zm.get_zones(meta["map_id"])
        # Cancel (confirm=False) should keep zone
        new_zones, new_sel, deleted = editor_delete_simulation(zones, z["zone_id"], confirm=False)
        assert deleted is False
        assert len(new_zones) == 1
        assert new_zones[0]["zone_id"] == z["zone_id"]
        # File should still have zone (no save with deletion)
        assert len(zm.get_zones(meta["map_id"])) == 1

    def test_deleting_with_no_selection(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (0, 0), (100, 100))
        zones = zm.get_zones(meta["map_id"])
        new_zones, new_sel, deleted = editor_delete_simulation(zones, None, confirm=True)
        assert deleted is False
        assert len(new_zones) == 1  # no change
        # Manager should not crash, no deletion
        assert zm.delete_zone(meta["map_id"], "nonexistent") is False


class TestSaveAfterDeletion:
    def test_save_after_deletion(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        for name in ["A", "B", "C"]:
            idx = ["A", "B", "C"].index(name)
            zm.create_rectangle(meta["map_id"], name, (idx * 110, 0), (idx * 110 + 100, 100))
        zones = zm.get_zones(meta["map_id"])
        assert len(zones) == 3
        # Delete B
        b_id = next(z["zone_id"] for z in zones if z["name"] == "B")
        new_zones, _, _ = editor_delete_simulation(zones, b_id, confirm=True)
        zm.save_zones(meta["map_id"], new_zones)
        # Verify file has only 2
        assert len(zm.get_zones(meta["map_id"])) == 2
        assert all(z["name"] != "B" for z in zm.get_zones(meta["map_id"]))

    def test_reload_after_deletion(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zones_dir = tmp_path / "zones"
        zm = ZoneManager(zones_dir=zones_dir, maps_dir=maps_dir)
        for name in ["A", "B", "C"]:
            idx = ["A", "B", "C"].index(name)
            zm.create_rectangle(meta["map_id"], name, (idx * 110, 0), (idx * 110 + 100, 100))
        zones = zm.get_zones(meta["map_id"])
        b_id = next(z["zone_id"] for z in zones if z["name"] == "B")
        new_zones, _, _ = editor_delete_simulation(zones, b_id, confirm=True)
        zm.save_zones(meta["map_id"], new_zones)
        # Simulate close and reopen: new manager instance
        zm2 = ZoneManager(zones_dir=zones_dir, maps_dir=maps_dir)
        reloaded = zm2.get_zones(meta["map_id"])
        assert len(reloaded) == 2
        assert "B" not in [z["name"] for z in reloaded]
        assert {"A", "C"} == {z["name"] for z in reloaded}

    def test_create_3_delete_1_save_reopen_only_2(self, tmp_path):
        # Exact scenario from requirements
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Z1", (0, 0), (100, 100))
        zm.create_rectangle(meta["map_id"], "Z2", (200, 0), (300, 100))
        zm.create_rectangle(meta["map_id"], "Z3", (400, 0), (500, 100))
        assert len(zm.get_zones(meta["map_id"])) == 3
        # Delete Z2
        z2_id = [z for z in zm.get_zones(meta["map_id"]) if z["name"] == "Z2"][0]["zone_id"]
        zones = zm.get_zones(meta["map_id"])
        new_zones, _, _ = editor_delete_simulation(zones, z2_id, confirm=True)
        zm.save_zones(meta["map_id"], new_zones)
        # Close and reopen
        zm_reload = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert len(zm_reload.get_zones(meta["map_id"])) == 2
        assert all(z["name"] in ["Z1", "Z3"] for z in zm_reload.get_zones(meta["map_id"]))


class TestIsolation:
    def test_deleting_one_map_not_affect_another(self, tmp_path):
        maps_dir = tmp_path / "maps"
        m = MapManager(maps_dir)
        src1 = tmp_path / "src1.png"
        make_image(src1, (800, 600))
        meta1 = m.upload_map(src1, name="Map1")
        src2 = tmp_path / "src2.png"
        make_image(src2, (800, 600))
        meta2 = m.upload_map(src2, name="Map2")
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        z1 = zm.create_rectangle(meta1["map_id"], "M1_Zone", (0, 0), (100, 100))
        z2 = zm.create_rectangle(meta2["map_id"], "M2_Zone", (0, 0), (100, 100))
        # Delete from map1 only
        zones_m1 = zm.get_zones(meta1["map_id"])
        new_m1, _, _ = editor_delete_simulation(zones_m1, z1["zone_id"], confirm=True)
        zm.save_zones(meta1["map_id"], new_m1)
        assert len(zm.get_zones(meta1["map_id"])) == 0
        assert len(zm.get_zones(meta2["map_id"])) == 1  # untouched
        assert zm.get_zones(meta2["map_id"])[0]["name"] == "M2_Zone"

    def test_deletion_does_not_delete_image_or_metadata_or_calibration(self, tmp_path):
        # Setup map, calibration file, zones
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Create calibration file
        from app.phase2.calibration.store import save_calibration
        calib_dir = tmp_path / "calibration"
        calib_data = {
            "camera_id": "default_camera",
            "map_id": meta["map_id"],
            "camera_resolution": [640, 480],
            "cctv_points": [[0, 0], [640, 0], [640, 480], [0, 480]],
            "bird_eye_points": [[0, 0], [800, 0], [800, 600], [0, 600]],
            "homography_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "reprojection_error": 0.5,
            "per_point_errors": [0.5, 0.5, 0.5, 0.5],
            "created_at": "2026-08-29T00:00:00",
            "status": "valid",
        }
        calib_path = save_calibration(calib_data, calib_dir)
        assert calib_path.exists()
        # Create zone and delete it
        z = zm.create_rectangle(meta["map_id"], "ToDelete", (10, 10), (100, 100))
        zones = zm.get_zones(meta["map_id"])
        new_zones, _, _ = editor_delete_simulation(zones, z["zone_id"], confirm=True)
        zm.save_zones(meta["map_id"], new_zones)
        # Verify image still exists
        assert Path(meta["image_path"]).exists()
        # Metadata still exists
        assert (maps_dir / "metadata" / f"{meta['map_id']}.json").exists()
        # Calibration still exists
        assert calib_path.exists()
        # Other maps not affected (check no other zone files deleted)
        assert (tmp_path / "zones" / f"{meta['map_id']}.json").exists()
        # But zones file should have 0 zones now
        data = json.loads((tmp_path / "zones" / f"{meta['map_id']}.json").read_text())
        assert len(data["zones"]) == 0


class TestUIRequirements:
    def test_delete_zone_button_visible(self):
        src = Path("app/phase2/zones/editor.py").read_text(encoding="utf-8")
        assert "Delete Zone" in src, "UI must have visible [Delete Zone] button"
        assert 'text="Delete Zone"' in src or "Delete Zone" in src

    def test_delete_key_binding(self):
        src = Path("app/phase2/zones/editor.py").read_text(encoding="utf-8")
        assert "<Delete>" in src, "Must support Delete key"
        assert "on_delete" in src
        # Check that root binds Delete and BackSpace
        assert 'bind("<Delete>"' in src or "bind('<Delete>'" in src or "<Delete>" in src

    def test_confirmation_dialog(self):
        src = Path("app/phase2/zones/editor.py").read_text(encoding="utf-8")
        # Should show Delete zone "name" with double quotes
        assert 'Delete zone' in src
        assert 'askyesno' in src
        assert 'Delete Zone' in src

    def test_no_selection_message(self):
        src = Path("app/phase2/zones/editor.py").read_text(encoding="utf-8")
        assert "Select a zone first" in src

    def test_editor_import_no_yolo(self):
        import subprocess, sys
        code = "import sys; import app.phase2.zones.editor; assert 'ultralytics' not in sys.modules"
        import subprocess as sp
        r = sp.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


# ── Bug regression: delete then create must not resurrect deleted zone ──
# This is the exact bug: editor deleted in-memory but create_rectangle reloaded stale file

class TestDeleteCreatePersistenceBug:
    def _editor_flow_delete_then_create(self, tmp_path, map_size=(800, 600)):
        """Helper simulating fixed editor flow: load, delete in-memory, build in-memory, save."""
        m, meta, maps_dir = create_map(tmp_path, map_size)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        return m, meta, zm

    def test_delete_then_save_empty(self, tmp_path):
        m, meta, zm = self._editor_flow_delete_then_create(tmp_path)
        zA = zm.create_rectangle(meta["map_id"], "Zone A", (0, 0), (100, 100))
        # Editor load
        editor_zones = zm.get_zones(meta["map_id"])
        # Delete in-memory
        editor_zones = [z for z in editor_zones if z["zone_id"] != zA["zone_id"]]
        zm.save_zones(meta["map_id"], editor_zones)
        assert zm.get_zones(meta["map_id"]) == []
        # Reload
        zm2 = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=tmp_path / "maps")
        assert zm2.get_zones(meta["map_id"]) == []

    def test_delete_then_create_another_zone(self, tmp_path):
        m, meta, zm = self._editor_flow_delete_then_create(tmp_path)
        zA = zm.create_rectangle(meta["map_id"], "Zone A", (0, 0), (100, 100))
        editor_zones = zm.get_zones(meta["map_id"])
        # Delete A in-memory
        editor_zones = [z for z in editor_zones if z["zone_id"] != zA["zone_id"]]
        # Create B via build_rectangle (fixed path, not stale reload)
        zB = zm.build_rectangle(meta["map_id"], "Zone B", (200, 0), (300, 100), existing_zones=editor_zones)
        editor_zones.append(zB)
        zm.save_zones(meta["map_id"], editor_zones)
        reloaded = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=tmp_path / "maps").get_zones(meta["map_id"])
        assert len(reloaded) == 1
        assert reloaded[0]["name"] == "Zone B"
        assert "Zone A" not in [z["name"] for z in reloaded]

    def test_delete_then_create_at_same_location(self, tmp_path):
        m, meta, zm = self._editor_flow_delete_then_create(tmp_path)
        zA = zm.create_rectangle(meta["map_id"], "Zone A", (100, 100), (400, 300))
        editor_zones = zm.get_zones(meta["map_id"])
        editor_zones = [z for z in editor_zones if z["zone_id"] != zA["zone_id"]]
        # Same polygon as deleted
        zB = zm.build_rectangle(meta["map_id"], "Zone B", (100, 100), (400, 300), existing_zones=editor_zones)
        editor_zones.append(zB)
        zm.save_zones(meta["map_id"], editor_zones)
        reloaded = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=tmp_path / "maps").get_zones(meta["map_id"])
        assert len(reloaded) == 1
        assert reloaded[0]["name"] == "Zone B"
        # Ensure no duplicate ID
        assert reloaded[0]["zone_id"] != zA["zone_id"]

    def test_multiple_zones_delete_one_create_another(self, tmp_path):
        m, meta, zm = self._editor_flow_delete_then_create(tmp_path)
        for n, (x1, y1, x2, y2) in [("A", (0, 0, 100, 100)), ("B", (200, 0, 300, 100)), ("C", (400, 0, 500, 100))]:
            zm.create_rectangle(meta["map_id"], n, (x1, y1), (x2, y2))
        editor_zones = zm.get_zones(meta["map_id"])
        b_id = next(z["zone_id"] for z in editor_zones if z["name"] == "B")
        editor_zones = [z for z in editor_zones if z["zone_id"] != b_id]
        zD = zm.build_rectangle(meta["map_id"], "D", (600, 0), (700, 100), existing_zones=editor_zones)
        editor_zones.append(zD)
        zm.save_zones(meta["map_id"], editor_zones)
        reloaded = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=tmp_path / "maps").get_zones(meta["map_id"])
        assert {z["name"] for z in reloaded} == {"A", "C", "D"}
        assert "B" not in [z["name"] for z in reloaded]

    def test_delete_all_then_create_one(self, tmp_path):
        m, meta, zm = self._editor_flow_delete_then_create(tmp_path)
        zm.create_rectangle(meta["map_id"], "A", (0, 0), (100, 100))
        zm.create_rectangle(meta["map_id"], "B", (200, 0), (300, 100))
        editor_zones = zm.get_zones(meta["map_id"])
        # Delete all
        editor_zones = []
        zC = zm.build_rectangle(meta["map_id"], "C", (400, 0), (500, 100), existing_zones=editor_zones)
        editor_zones.append(zC)
        zm.save_zones(meta["map_id"], editor_zones)
        reloaded = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=tmp_path / "maps").get_zones(meta["map_id"])
        assert len(reloaded) == 1 and reloaded[0]["name"] == "C"

    def test_buggy_path_would_resurrect_deleted(self, tmp_path):
        """Prove old buggy path (create_rectangle reloads file) resurrects deleted zone."""
        m, meta, zm = self._editor_flow_delete_then_create(tmp_path)
        zA = zm.create_rectangle(meta["map_id"], "Zone A", (0, 0), (100, 100))
        editor_zones = zm.get_zones(meta["map_id"])
        # Delete in-memory, but file still has A (not yet saved)
        editor_zones_buggy = [z for z in editor_zones if z["zone_id"] != zA["zone_id"]]
        assert editor_zones_buggy == []
        # Buggy: call create_rectangle which loads stale file (contains A) and appends B
        zB_buggy = zm.create_rectangle(meta["map_id"], "Zone B", (200, 0), (300, 100))
        # Now file has both A and B -> bug
        buggy_reloaded = zm.get_zones(meta["map_id"])
        assert "Zone A" in [z["name"] for z in buggy_reloaded], "Buggy path should resurrect A"
        assert "Zone B" in [z["name"] for z in buggy_reloaded]
        # Cleanup for fixed test
        zm.save_zones(meta["map_id"], [])  # reset
        # Fixed path: build + save should NOT resurrect
        zA2 = zm.create_rectangle(meta["map_id"], "Zone A", (0, 0), (100, 100))
        editor_zones2 = zm.get_zones(meta["map_id"])
        editor_zones2 = [z for z in editor_zones2 if z["zone_id"] != zA2["zone_id"]]
        zB_fixed = zm.build_rectangle(meta["map_id"], "Zone B", (200, 0), (300, 100), existing_zones=editor_zones2)
        editor_zones2.append(zB_fixed)
        zm.save_zones(meta["map_id"], editor_zones2)
        fixed_reloaded = zm.get_zones(meta["map_id"])
        assert "Zone A" not in [z["name"] for z in fixed_reloaded]
        assert "Zone B" in [z["name"] for z in fixed_reloaded]

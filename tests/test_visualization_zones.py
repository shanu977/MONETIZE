"""Regression tests for visualization zone loading — Phase 2.5A bug fix.

Ensures deleted zones never reappear in Bird's-Eye visualization,
which must load current zones/<map_id>.json via ZoneEngine (authoritative).
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from app.phase2.maps.manager import MapManager
from app.phase2.zones.manager import ZoneManager
from app.phase2.zones.engine import ZoneEngine
from app.phase2.calibration.homography import HomographyCalibrator
from app.phase2.calibration.store import save_calibration


def make_image(path: Path, size, color=(200, 210, 220)):
    Image.new("RGB", size, color).save(path, "PNG")
    return path

def create_map(tmp_path: Path, size=(800, 600), name="Map"):
    maps_dir = tmp_path / "maps"
    m = MapManager(maps_dir)
    src = tmp_path / f"src_{name.replace(' ','_')}.png"
    make_image(src, size)
    meta = m.upload_map(src, name=name)
    return m, meta, maps_dir

def create_calibration_for_map(tmp_path: Path, map_id: str, map_size=(800,600), cam_size=(640,480)):
    c = HomographyCalibrator()
    c.cctv_points = [[0,0],[cam_size[0],0],[cam_size[0],cam_size[1]],[0,cam_size[1]]]
    c.map_points = [[0,0],[map_size[0],0],[map_size[0],map_size[1]],[0,map_size[1]]]
    c.calibrate(camera_id="default_camera", map_id=map_id, camera_resolution=cam_size)
    save_calibration(c.to_dict(), tmp_path / "calibration")
    return c

def visualization_load_zones(map_id: str, zones_dir: Path, maps_dir: Path):
    """Simulate what test_video_zone_pipeline.py does for visualization: load via ZoneEngine (authoritative)."""
    engine = ZoneEngine(map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir))
    return engine.zones, engine.zone_count


class TestVisualizationUsesCurrentJson:
    def test_visualization_uses_current_json(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zA = zm.create_rectangle(meta["map_id"], "A", (0,0), (100,100))
        zones, count = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert len(zones) == 1 and zones[0]["name"] == "A"

    def test_visualization_does_not_use_stale_cache(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zA = zm.create_rectangle(meta["map_id"], "A", (0,0), (100,100))
        # First load
        zones1, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert len(zones1) == 1
        # Create B after first load
        zm.create_rectangle(meta["map_id"], "B", (200,0), (300,100))
        # Second load should see 2, not stale 1
        zones2, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert len(zones2) == 2

    def test_visualization_does_not_create_zones(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (0,0), (100,100))
        # Visualization should not create zones
        zones_before, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        # Simulate visualization load again (should not change file)
        zones_after, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert len(zones_before) == len(zones_after) == 1
        # File should still have 1
        assert len(zm.get_zones(meta["map_id"])) == 1


class TestDeleteVisualization:
    def test_delete_zone_then_visualization(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zA = zm.create_rectangle(meta["map_id"], "A", (0,0), (100,100))
        assert len(zm.get_zones(meta["map_id"])) == 1
        # Delete A
        zm.delete_zone(meta["map_id"], zA["zone_id"])
        # Visualization should see 0
        zones, count = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert count == 0
        assert zones == []

    def test_delete_all_then_visualization_shows_zero(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        for name in ["A","B","C"]:
            zm.create_rectangle(meta["map_id"], name, (0,0), (100,100))
        assert len(zm.get_zones(meta["map_id"])) == 3
        # Delete all
        for z in list(zm.get_zones(meta["map_id"])):
            zm.delete_zone(meta["map_id"], z["zone_id"])
        zones, count = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert count == 0

    def test_delete_one_of_multiple_then_visualization_shows_remaining_only(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, size=(1000,600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zA = zm.create_rectangle(meta["map_id"], "A", (0,0), (100,100))
        zB = zm.create_rectangle(meta["map_id"], "B", (200,0), (300,100))
        zC = zm.create_rectangle(meta["map_id"], "C", (400,0), (500,100))
        # Delete B
        zm.delete_zone(meta["map_id"], zB["zone_id"])
        zones, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert {z["name"] for z in zones} == {"A","C"}
        assert "B" not in [z["name"] for z in zones]

    def test_delete_then_create_new_zone_then_visualization(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zA = zm.create_rectangle(meta["map_id"], "Zone A", (0,0), (100,100))
        # Simulate editor: load, delete in-memory, save
        editor_zones = zm.get_zones(meta["map_id"])
        editor_zones = [z for z in editor_zones if z["zone_id"] != zA["zone_id"]]
        zm.save_zones(meta["map_id"], editor_zones)
        assert len(zm.get_zones(meta["map_id"])) == 0
        # Create B via editor's fixed path (build+append+save)
        zB = zm.build_rectangle(meta["map_id"], "Zone B", (200,0), (300,100), existing_zones=editor_zones)
        editor_zones.append(zB)
        zm.save_zones(meta["map_id"], editor_zones)
        # Visualization should see only B
        zones, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert len(zones) == 1 and zones[0]["name"] == "Zone B"
        assert "Zone A" not in [z["name"] for z in zones]

    def test_delete_then_create_same_location_then_only_new_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, size=(800,600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zA = zm.create_rectangle(meta["map_id"], "Zone A", (100,100), (400,300))
        editor_zones = zm.get_zones(meta["map_id"])
        editor_zones = [z for z in editor_zones if z["zone_id"] != zA["zone_id"]]
        zm.save_zones(meta["map_id"], editor_zones)
        # Same polygon
        zB = zm.build_rectangle(meta["map_id"], "Zone B", (100,100), (400,300), existing_zones=editor_zones)
        editor_zones.append(zB)
        zm.save_zones(meta["map_id"], editor_zones)
        zones, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert len(zones) == 1
        assert zones[0]["name"] == "Zone B"
        assert zones[0]["zone_id"] != zA["zone_id"]

    def test_save_reload_visualization_consistency(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (0,0), (100,100))
        # Save is already done via create
        # Reload via visualization
        zones1, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        # Create another and save
        zm.create_rectangle(meta["map_id"], "B", (200,0), (300,100))
        zones2, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
        assert len(zones2) == 2
        # Both should be consistent with manager
        assert len(zm.get_zones(meta["map_id"])) == len(zones2)


class TestVisualizationMapIsolation:
    def test_visualization_map_isolation(self, tmp_path):
        maps_dir = tmp_path / "maps"
        m = MapManager(maps_dir)
        src1 = tmp_path / "src1.png"
        make_image(src1, (800,600))
        metaA = m.upload_map(src1, name="MapA")
        src2 = tmp_path / "src2.png"
        make_image(src2, (800,600))
        metaB = m.upload_map(src2, name="MapB")
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(metaA["map_id"], "A1", (0,0), (100,100))
        zm.create_rectangle(metaB["map_id"], "B1", (0,0), (100,100))
        zm.create_rectangle(metaB["map_id"], "B2", (200,0), (300,100))
        # Visualization for A should not see B's zones
        zonesA, _ = visualization_load_zones(metaA["map_id"], tmp_path / "zones", maps_dir)
        zonesB, _ = visualization_load_zones(metaB["map_id"], tmp_path / "zones", maps_dir)
        assert len(zonesA) == 1 and zonesA[0]["name"] == "A1"
        assert len(zonesB) == 2 and {z["name"] for z in zonesB} == {"B1","B2"}


class TestVisualizationDoesNotCreateZones:
    def test_visualization_does_not_create_zones(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert len(zm.get_zones(meta["map_id"])) == 0
        # Load visualization multiple times
        for _ in range(3):
            zones, _ = visualization_load_zones(meta["map_id"], tmp_path / "zones", maps_dir)
            assert len(zones) == 0
        # File should still be empty / not created with dummy zones
        assert len(zm.get_zones(meta["map_id"])) == 0

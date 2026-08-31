"""Tests for Phase 2.4 — Zone Engine."""
import json
from pathlib import Path

import pytest
from PIL import Image

from app.phase2.maps.manager import MapManager
from app.phase2.zones.manager import ZoneManager
from app.phase2.zones.engine import ZoneEngine, ZoneAssignment


def make_image(path: Path, size, color=(200, 210, 220)):
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def create_map(tmp_path: Path, size=(800, 600), name="Test Map"):
    maps_dir = tmp_path / "maps"
    m = MapManager(maps_dir)
    src = tmp_path / f"src_{name.replace(' ','_').replace('/','_')}.png"
    make_image(src, size)
    meta = m.upload_map(src, name=name)
    return m, meta, maps_dir


# ── Basic ─────────────────────────────────────────────────────────────

class TestBasic:
    def test_load_zones(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Entrance", (100, 100), (500, 400))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.zone_count == 1
        assert engine.zones[0]["name"] == "Entrance"

    def test_correct_map_id(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "A", (0, 0), (100, 100))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.map_id == meta["map_id"]
        a = engine.assign(12, (50, 50))
        assert a.map_id == meta["map_id"]

    def test_empty_zone_list(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.zone_count == 0
        a = engine.assign(1, (100, 100))
        assert a.zone_id is None and a.zone_name is None

    def test_customer_inside_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Entrance", (100, 100), (500, 400))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zone = engine.get_zone_for_point(200, 200)
        assert zone is not None and zone["name"] == "Entrance"
        a = engine.assign(12, (200, 200))
        assert a.zone_id == zone["zone_id"] and a.zone_name == "Entrance"

    def test_customer_outside_zone(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Entrance", (100, 100), (500, 400))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.get_zone_for_point(10, 10) is None
        a = engine.assign(12, (10, 10))
        assert a.zone_id is None and a.zone_name is None
        d = engine.assign_dict(12, (10, 10))
        assert d["zone_id"] is None


# ── Multiple zones ────────────────────────────────────────────────────

class TestMultipleZones:
    def test_customer_in_zone_a(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (1000, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Entrance", (0, 0), (250, 600))
        zm.create_rectangle(meta["map_id"], "Billing", (250, 0), (500, 600))
        zm.create_rectangle(meta["map_id"], "Electronics", (500, 0), (750, 600))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.get_zone_for_point(100, 300)["name"] == "Entrance"

    def test_customer_in_zone_b(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (1000, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Entrance", (0, 0), (250, 600))
        zm.create_rectangle(meta["map_id"], "Billing", (250, 0), (500, 600))
        zm.create_rectangle(meta["map_id"], "Electronics", (500, 0), (750, 600))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.get_zone_for_point(300, 300)["name"] == "Billing"

    def test_customer_outside_all_zones(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (1000, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Entrance", (0, 0), (250, 600))
        zm.create_rectangle(meta["map_id"], "Billing", (250, 0), (500, 600))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.get_zone_for_point(900, 300) is None
        assert engine.assign(99, (900, 300)).zone_id is None

    def test_multiple_customers_independently(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (1000, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Entrance", (0, 0), (250, 600))
        zm.create_rectangle(meta["map_id"], "Billing", (250, 0), (500, 600))
        zm.create_rectangle(meta["map_id"], "Electronics", (500, 0), (750, 600))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Simulate 4 customers
        c1 = engine.assign(1, (100, 300))
        c2 = engine.assign(2, (300, 300))
        c3 = engine.assign(3, (600, 300))
        c4 = engine.assign(4, (900, 300))
        assert c1.zone_name == "Entrance"
        assert c2.zone_name == "Billing"
        assert c3.zone_name == "Electronics"
        assert c4.zone_name is None


# ── Geometry ──────────────────────────────────────────────────────────

class TestGeometry:
    def test_center_point(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "Center", (100, 100), (300, 300))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.get_zone_for_point(200, 200) is not None

    def test_polygon_edge(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (100, 100), (300, 300))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Edge midpoint (100,200) is on left edge -> should be inside (boundary as inside)
        assert engine.get_zone_for_point(100, 200) is not None, "Edge should be inside"
        assert engine.get_zone_for_point(200, 100) is not None, "Top edge should be inside"

    def test_polygon_corner(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (100, 100), (300, 300))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.get_zone_for_point(100, 100) is not None, "Corner should be inside"
        assert engine.get_zone_for_point(300, 300) is not None

    def test_outside_point(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (100, 100), (300, 300))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.get_zone_for_point(50, 50) is None

    def test_irregular_polygon(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # L-shaped or pentagon: use add_zone with custom points
        points = [[200, 100], [400, 100], [400, 300], [300, 300], [300, 200], [200, 200]]
        zm.add_zone(meta["map_id"], "Irregular", points, zone_type="polygon")
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.get_zone_for_point(250, 150) is not None  # inside
        assert engine.get_zone_for_point(350, 150) is not None
        assert engine.get_zone_for_point(250, 250) is None  # notch outside? Actually shape is like C, so (350,250) inside notch? Let's just test outside far
        assert engine.get_zone_for_point(10, 10) is None


# ── Map isolation ─────────────────────────────────────────────────────

class TestMapIsolation:
    def test_map_a_only_loads_map_a(self, tmp_path):
        maps_dir = tmp_path / "maps"
        m = MapManager(maps_dir)
        src1 = tmp_path / "src1.png"
        make_image(src1, (800, 600))
        metaA = m.upload_map(src1, name="MapA")
        src2 = tmp_path / "src2.png"
        make_image(src2, (800, 600))
        metaB = m.upload_map(src2, name="MapB")
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(metaA["map_id"], "Zone A1", (0, 0), (100, 100))
        zm.create_rectangle(metaB["map_id"], "Zone B1", (500, 500), (600, 600))
        engA = ZoneEngine(metaA["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        engB = ZoneEngine(metaB["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engA.zone_count == 1 and engA.zones[0]["name"] == "Zone A1"
        assert engB.zone_count == 1 and engB.zones[0]["name"] == "Zone B1"
        # Cross-check no contamination
        assert engA.get_zone_for_point(550, 550) is None
        assert engB.get_zone_for_point(50, 50) is None
        assert engA.get_zone_for_point(50, 50) is not None
        assert engB.get_zone_for_point(550, 550) is not None

    def test_map_b_only_loads_map_b(self, tmp_path):
        maps_dir = tmp_path / "maps"
        m = MapManager(maps_dir)
        src1 = tmp_path / "src1b.png"
        make_image(src1, (800, 600))
        metaA = m.upload_map(src1, name="MapA2")
        src2 = tmp_path / "src2b.png"
        make_image(src2, (800, 600))
        metaB = m.upload_map(src2, name="MapB2")
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(metaA["map_id"], "A1", (0, 0), (50, 50))
        # B has no zones
        engB = ZoneEngine(metaB["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engB.zone_count == 0


# ── Error handling ────────────────────────────────────────────────────

class TestErrorHandling:
    def test_missing_zone_file(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        # Don't create any zones → file missing
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.zone_count == 0
        assert engine.get_zone_for_point(50, 50) is None
        assert engine.assign(1, (50, 50)).zone_id is None

    def test_invalid_json(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zones_dir = tmp_path / "zones"
        zones_dir.mkdir(exist_ok=True)
        # Write invalid JSON
        (zones_dir / f"{meta['map_id']}.json").write_text("{ invalid json", encoding="utf-8")
        engine = ZoneEngine(meta["map_id"], zones_dir=zones_dir, maps_dir=maps_dir)
        assert engine.zone_count == 0  # should not crash
        assert engine.get_zone_for_point(10, 10) is None

    def test_invalid_polygon(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zones_dir = tmp_path / "zones"
        zm = ZoneManager(zones_dir=zones_dir, maps_dir=maps_dir)
        # Manually write file with invalid polygon (<3 points, bad format)
        bad_data = {
            "map_id": meta["map_id"],
            "zones": [
                {"zone_id": "bad1", "name": "Bad", "type": "rectangle", "map_id": meta["map_id"], "points": [[0, 0], [1, 1]], "created_at": "now"},
                {"zone_id": "bad2", "name": "Bad2", "type": "rectangle", "map_id": meta["map_id"], "points": "not a list", "created_at": "now"},
                {"zone_id": "good", "name": "Good", "type": "rectangle", "map_id": meta["map_id"], "points": [[0, 0], [100, 0], [100, 100], [0, 100]], "created_at": "now"},
            ]
        }
        (zones_dir / f"{meta['map_id']}.json").write_text(json.dumps(bad_data), encoding="utf-8")
        engine = ZoneEngine(meta["map_id"], zones_dir=zones_dir, maps_dir=maps_dir)
        # Should skip bad, load good
        assert engine.zone_count == 1
        assert engine.zones[0]["zone_id"] == "good"

    def test_empty_polygon(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zones_dir = tmp_path / "zones"
        zm = ZoneManager(zones_dir=zones_dir, maps_dir=maps_dir)
        bad = {
            "map_id": meta["map_id"],
            "zones": [
                {"zone_id": "empty", "name": "Empty", "type": "rectangle", "map_id": meta["map_id"], "points": [], "created_at": "now"},
            ]
        }
        (zones_dir / f"{meta['map_id']}.json").write_text(json.dumps(bad), encoding="utf-8")
        engine = ZoneEngine(meta["map_id"], zones_dir=zones_dir, maps_dir=maps_dir)
        assert engine.zone_count == 0


# ── Overlapping & boundary documentation ──────────────────────────────

class TestOverlappingAndBoundary:
    def test_overlapping_first_wins(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "First", (100, 100), (400, 400))
        zm.create_rectangle(meta["map_id"], "Second", (200, 200), (500, 500))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # Overlapping area (250,250) should return First (saved order)
        assert engine.get_zone_for_point(250, 250)["name"] == "First"
        # Non-overlapping part of Second
        assert engine.get_zone_for_point(450, 450)["name"] == "Second"

    def test_boundary_deterministic(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path, (800, 600))
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (100, 100), (300, 300))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        # All boundary points should be consistently inside
        for pt in [(100, 100), (300, 100), (300, 300), (100, 300), (200, 100), (100, 200)]:
            assert engine.get_zone_for_point(*pt) is not None, f"Boundary {pt} should be inside"


# ── Customer ID handling ──────────────────────────────────────────────

class TestCustomerID:
    def test_does_not_generate_ids(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (0, 0), (100, 100))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        a = engine.assign(42, (50, 50))
        assert a.customer_id == 42
        b = engine.assign("Customer_007", (50, 50))
        assert b.customer_id == "Customer_007"

    def test_empty_zones_returns_none(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        a = engine.assign(1, (10, 10))
        assert a.zone_id is None and a.zone_name is None


# ── Compatibility ─────────────────────────────────────────────────────

class TestCompatibility:
    def test_reload(self, tmp_path):
        m, meta, maps_dir = create_map(tmp_path)
        zm = ZoneManager(zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        zm.create_rectangle(meta["map_id"], "R", (0, 0), (100, 100))
        engine = ZoneEngine(meta["map_id"], zones_dir=tmp_path / "zones", maps_dir=maps_dir)
        assert engine.zone_count == 1
        zm.create_rectangle(meta["map_id"], "R2", (200, 200), (300, 300))
        # Before reload still 1
        assert engine.zone_count == 1
        engine.reload()
        assert engine.zone_count == 2

    def test_import_no_yolo(self):
        import subprocess, sys
        code = "import sys; import app.phase2.zones.engine; assert 'ultralytics' not in sys.modules"
        import subprocess as sp
        r = sp.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

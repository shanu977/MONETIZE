"""Tests for Phase 3B: Admin Zone Management APIs."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.main import app
from app.phase2.maps.manager import MapManager, get_map_manager
from app.phase2.zones.manager import ZoneManager, get_zone_manager


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    """Fixture providing isolated maps/zones directories and FastAPI TestClient."""
    maps_dir = tmp_path / "maps"
    zones_dir = tmp_path / "zones"
    maps_dir.mkdir(parents=True, exist_ok=True)
    zones_dir.mkdir(parents=True, exist_ok=True)

    # Patch default directories in managers
    import app.phase2.maps.manager as mm
    import app.phase2.zones.manager as zm
    import app.phase2.zones.engine as ze

    monkeypatch.setattr(mm, "DEFAULT_MAPS_DIR", maps_dir)
    monkeypatch.setattr(zm, "DEFAULT_MAPS_DIR", maps_dir)
    monkeypatch.setattr(zm, "DEFAULT_ZONES_DIR", zones_dir)
    monkeypatch.setattr(ze, "PROJECT_ROOT", tmp_path)

    # Create a test map image
    map_mgr = MapManager(maps_dir)
    img_path = tmp_path / "test_map_image.png"
    Image.new("RGB", (1000, 800), color=(100, 150, 200)).save(img_path, "PNG")
    map1 = map_mgr.upload_map(img_path, name="Main Store Floor")

    img_path2 = tmp_path / "test_map_image2.png"
    Image.new("RGB", (1200, 900), color=(150, 100, 200)).save(img_path2, "PNG")
    map2 = map_mgr.upload_map(img_path2, name="Second Floor")

    # Select map1 by default
    map_mgr.select_map(map1["map_id"])

    client = TestClient(app)
    return {
        "client": client,
        "map1": map1,
        "map2": map2,
        "maps_dir": maps_dir,
        "zones_dir": zones_dir,
    }


def test_list_maps_and_get_map(test_client):
    client = test_client["client"]
    map1 = test_client["map1"]
    
    res = client.get("/api/maps")
    assert res.status_code == 200
    data = res.json()
    assert "maps" in data
    assert len(data["maps"]) >= 2
    assert data["selected"] == map1["map_id"]
    
    # Check single map get
    res_single = client.get(f"/api/maps/{map1['map_id']}")
    assert res_single.status_code == 200
    single_data = res_single.json()
    assert single_data["name"] == "Main Store Floor"
    assert single_data["width"] == 1000
    assert single_data["height"] == 800
    assert "image_url" in single_data


def test_get_map_image(test_client):
    client = test_client["client"]
    map1 = test_client["map1"]

    res = client.get(f"/api/maps/{map1['map_id']}/image")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/")


def test_create_and_get_zones(test_client):
    client = test_client["client"]
    map1 = test_client["map1"]
    map_id = map1["map_id"]

    # Initial zones should be empty
    res = client.get(f"/api/maps/{map_id}/zones")
    assert res.status_code == 200
    assert res.json()["zones"] == []

    # Create Zone A
    res_add = client.post(f"/api/maps/{map_id}/zones", json={
        "name": "Entrance Area",
        "points": [[10, 10], [200, 10], [200, 150], [10, 150]],
        "type": "rectangle"
    })
    assert res_add.status_code == 200
    zone_a = res_add.json()["zone"]
    assert zone_a["name"] == "Entrance Area"
    assert "zone_id" in zone_a

    # Get zones again
    res = client.get(f"/api/maps/{map_id}/zones")
    assert res.status_code == 200
    zones = res.json()["zones"]
    assert len(zones) == 1
    assert zones[0]["name"] == "Entrance Area"


def test_update_and_delete_zone(test_client):
    client = test_client["client"]
    map1 = test_client["map1"]
    map_id = map1["map_id"]

    # Create zone
    res_add = client.post(f"/api/maps/{map_id}/zones", json={
        "name": "Billing",
        "p1": [100, 100],
        "p2": [300, 250]
    })
    assert res_add.status_code == 200
    zone_id = res_add.json()["zone"]["zone_id"]

    # Update zone name and points
    res_up = client.put(f"/api/maps/{map_id}/zones/{zone_id}", json={
        "name": "Checkout Counters",
        "points": [[120, 120], [320, 120], [320, 270], [120, 270]]
    })
    assert res_up.status_code == 200
    assert res_up.json()["zone"]["name"] == "Checkout Counters"

    # Delete zone
    res_del = client.delete(f"/api/maps/{map_id}/zones/{zone_id}")
    assert res_del.status_code == 200

    # Verify gone
    res = client.get(f"/api/maps/{map_id}/zones")
    assert len(res.json()["zones"]) == 0


def test_bulk_save_authoritative_anti_resurrection(test_client):
    """Critical regression test:
    Start with [A], delete A in memory, create B, save [B].
    Expected: JSON contains ONLY [B], A never resurrects.
    """
    client = test_client["client"]
    map1 = test_client["map1"]
    map_id = map1["map_id"]

    # 1. Add Zone A
    res_a = client.post(f"/api/maps/{map_id}/zones", json={
        "name": "Test A",
        "points": [[50, 50], [150, 50], [150, 150], [50, 150]]
    })
    assert res_a.status_code == 200
    zone_a_id = res_a.json()["zone"]["zone_id"]

    # Verify A exists
    res = client.get(f"/api/maps/{map_id}/zones")
    assert len(res.json()["zones"]) == 1
    assert res.json()["zones"][0]["zone_id"] == zone_a_id

    # 2. In UI simulation: User deleted A, created B in memory:
    zone_b = {
        "zone_id": "zone_b_custom_99",
        "name": "Test B",
        "type": "rectangle",
        "map_id": map_id,
        "points": [[200, 200], [400, 200], [400, 300], [200, 300]],
        "created_at": "2026-08-31T20:00:00"
    }
    authoritative_list = [zone_b]

    # Save bulk list
    res_save = client.put(f"/api/maps/{map_id}/zones", json={"zones": authoritative_list})
    assert res_save.status_code == 200

    # 3. Reload from server
    res_reload = client.get(f"/api/maps/{map_id}/zones")
    loaded_zones = res_reload.json()["zones"]
    assert len(loaded_zones) == 1
    assert loaded_zones[0]["name"] == "Test B"
    assert loaded_zones[0]["zone_id"] == "zone_b_custom_99"

    # Zone A must NOT exist
    zone_ids = [z["zone_id"] for z in loaded_zones]
    assert zone_a_id not in zone_ids


def test_map_isolation(test_client):
    """Map A zones must be isolated from Map B zones."""
    client = test_client["client"]
    map1 = test_client["map1"]
    map2 = test_client["map2"]

    # Add zone on Map 1
    client.post(f"/api/maps/{map1['map_id']}/zones", json={
        "name": "Map1 Zone",
        "points": [[10, 10], [100, 10], [100, 100], [10, 100]]
    })

    # Add zone on Map 2
    client.post(f"/api/maps/{map2['map_id']}/zones", json={
        "name": "Map2 Zone",
        "points": [[20, 20], [200, 20], [200, 200], [20, 200]]
    })

    # Verify Map 1 only has Map1 Zone
    z1 = client.get(f"/api/maps/{map1['map_id']}/zones").json()["zones"]
    assert len(z1) == 1
    assert z1[0]["name"] == "Map1 Zone"

    # Verify Map 2 only has Map2 Zone
    z2 = client.get(f"/api/maps/{map2['map_id']}/zones").json()["zones"]
    assert len(z2) == 1
    assert z2[0]["name"] == "Map2 Zone"


def test_validation_rejects_malformed_zones(test_client):
    client = test_client["client"]
    map1 = test_client["map1"]
    map_id = map1["map_id"]

    # Empty name
    res = client.post(f"/api/maps/{map_id}/zones", json={
        "name": "",
        "points": [[10, 10], [100, 10], [100, 100], [10, 100]]
    })
    assert res.status_code == 400

    # Too small rectangle (< 5px)
    res_small = client.post(f"/api/maps/{map_id}/zones", json={
        "name": "Tiny Zone",
        "points": [[10, 10], [12, 10], [12, 12], [10, 12]]
    })
    assert res_small.status_code == 400

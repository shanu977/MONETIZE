"""Tests for Phase 3 Analytics — Detection & Tracking Analytics."""

import time
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from app.analytics.engine import AnalyticsEngine
from app.analytics.models import CustomerTrackState
from app.models.tracking_data import BoundingBox, TrackedCustomer, TrackingResult
from app.phase2.maps.manager import MapManager
from app.phase2.zones.manager import ZoneManager
from app.phase2.calibration.homography import HomographyCalibrator
from app.phase2.calibration.store import save_calibration


def make_image(path: Path, size, color=(200, 210, 220)):
    Image.new("RGB", size, color).save(path, "PNG")
    return path

def create_map_and_zone(tmp_path, map_size=(800,600), zone_rect=(0,0,400,600)):
    maps_dir = tmp_path / "maps"
    zones_dir = tmp_path / "zones"
    calib_dir = tmp_path / "calibration"
    m = MapManager(str(maps_dir))
    src = tmp_path / "src.png"
    Image.new("RGB", map_size, (200,200,200)).save(src)
    meta = m.upload_map(str(src), name="TestMap")
    map_id = meta["map_id"]
    zm = ZoneManager(str(zones_dir), str(maps_dir))
    zone = zm.create_rectangle(map_id, "Zone A", (zone_rect[0], zone_rect[1]), (zone_rect[2], zone_rect[3]))
    # Second zone for transition tests
    c = HomographyCalibrator()
    c.cctv_points = [[0,0],[640,0],[640,480],[0,480]]
    c.map_points = [[0,0],[map_size[0],0],[map_size[0],map_size[1]],[0,map_size[1]]]
    c.calibrate(camera_id="default_camera", map_id=map_id, camera_resolution=(640,480))
    save_calibration(c.to_dict(), str(calib_dir))
    return map_id, zones_dir, maps_dir, calib_dir, zone

def make_customer(tid, x1,y1,x2,y2):
    bb = BoundingBox(x1,y1,x2,y2)
    return TrackedCustomer.create(track_id=tid, class_name="person", bbox=bb)


# ── Tracking ──────────────────────────────────────────────────────────

class TestTracking:
    def test_track_creation(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)  # bottom-center (100,200) -> map (125,250) inside
        tr = TrackingResult(customers=[c])
        events = engine.update(tr, timestamp=time.time(), frame_number=1)
        assert 1 in engine.tracks
        assert engine.tracks[1].is_currently_tracked
        assert any(e.event_type == "track_started" for e in events)

    def test_track_update(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        # Update same track with new position
        c2 = make_customer(1, 60,60,160,210)
        engine.update(TrackingResult(customers=[c2]), timestamp=time.time()+0.1, frame_number=2)
        assert engine.tracks[1].last_position == (110.0, 210.0)  # bottom-center of second bbox

    def test_track_disappearance(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), lost_track_grace_seconds=0.5, zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        # Missing for 1 frame (within grace)
        events = engine.update(TrackingResult(customers=[]), timestamp=time.time()+0.1, frame_number=2)
        assert engine.tracks[1].is_currently_tracked  # still alive
        assert engine.tracks[1].missed_frames == 1

    def test_track_recovery(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), lost_track_grace_seconds=1.0, zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=100)
        engine.update(TrackingResult(customers=[]), timestamp=time.time()+0.1, frame_number=101)
        engine.update(TrackingResult(customers=[]), timestamp=time.time()+0.2, frame_number=102)
        # Reappear
        events = engine.update(TrackingResult(customers=[c]), timestamp=time.time()+0.3, frame_number=103)
        # Should not generate new entry (same zone)
        assert not any(e.event_type == "zone_entry" for e in events)
        assert engine.tracks[1].is_currently_tracked
        assert engine.tracks[1].missed_frames == 0

    def test_track_finalization(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), lost_track_grace_seconds=0.3, zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        # Miss for long
        time.sleep(0.4)
        events = engine.update(TrackingResult(customers=[]), timestamp=time.time(), frame_number=2)
        # Should have track_lost and zone_exit
        assert any(e.event_type == "track_lost" for e in events)
        assert not engine.tracks[1].is_currently_tracked


# ── Zone membership ───────────────────────────────────────────────────

class TestZoneMembership:
    def test_outside(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path, zone_rect=(0,0,100,100))
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 500,400,600,500)  # outside
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        assert engine.tracks[1].current_zone_id is None

    def test_inside(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path, zone_rect=(0,0,400,600))
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        assert engine.tracks[1].current_zone_id == zone["zone_id"]

    def test_boundary(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path, zone_rect=(100,100,300,300))
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        # Boundary point (100,100) corner should be inside
        # Camera bottom-center at (100,100) -> map (125,125) which is near boundary
        # Instead test with map position exactly on corner via direct zone engine
        from app.phase2.zones.engine import ZoneEngine
        ze = ZoneEngine(map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir))
        assert ze.get_zone_for_point(100,100) is not None

    def test_zone_a_to_zone_b(self, tmp_path):
        maps_dir = tmp_path / "maps"
        zones_dir = tmp_path / "zones"
        calib_dir = tmp_path / "calibration"
        m = MapManager(str(maps_dir))
        src = tmp_path / "src.png"
        Image.new("RGB", (800,600), (200,200,200)).save(src)
        meta = m.upload_map(str(src), name="Map2")
        map_id = meta["map_id"]
        zm = ZoneManager(str(zones_dir), str(maps_dir))
        za = zm.create_rectangle(map_id, "Zone A", (0,0), (400,600))
        zb = zm.create_rectangle(map_id, "Zone B", (400,0), (800,600))
        c = HomographyCalibrator()
        c.cctv_points = [[0,0],[640,0],[640,480],[0,480]]
        c.map_points = [[0,0],[800,0],[800,600],[0,600]]
        c.calibrate(camera_id="default_camera", map_id=map_id, camera_resolution=(640,480))
        save_calibration(c.to_dict(), str(calib_dir))
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c1 = make_customer(1, 50,50,150,200)  # inside A
        engine.update(TrackingResult(customers=[c1]), timestamp=time.time(), frame_number=1)
        assert engine.tracks[1].current_zone_id == za["zone_id"]
        c2 = make_customer(1, 500,200,600,300)  # inside B
        events = engine.update(TrackingResult(customers=[c2]), timestamp=time.time()+0.1, frame_number=2)
        assert any(e.event_type == "zone_exit" for e in events)
        assert any(e.event_type == "zone_entry" for e in events)
        assert engine.tracks[1].current_zone_id == zb["zone_id"]


# ── Entry / Exit ──────────────────────────────────────────────────────

class TestEntryExit:
    def test_one_entry_event(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        e1 = engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        assert sum(1 for e in e1 if e.event_type == "zone_entry") == 1
        # Second frame same zone should not duplicate
        e2 = engine.update(TrackingResult(customers=[c]), timestamp=time.time()+0.1, frame_number=2)
        assert sum(1 for e in e2 if e.event_type == "zone_entry") == 0

    def test_no_duplicate_entry(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        for i in range(5):
            engine.update(TrackingResult(customers=[c]), timestamp=time.time()+i*0.1, frame_number=i)
        assert engine.zone_stats[zone["zone_id"]].total_entries == 1

    def test_one_exit_event(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c_in = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c_in]), timestamp=time.time(), frame_number=1)
        c_out = make_customer(1, 500,400,600,500)
        events = engine.update(TrackingResult(customers=[c_out]), timestamp=time.time()+0.1, frame_number=2)
        assert sum(1 for e in events if e.event_type == "zone_exit") == 1
        assert events[0].dwell_seconds is not None


# ── Dwell ─────────────────────────────────────────────────────────────

class TestDwell:
    def test_active_dwell(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        t0 = time.time()
        engine.update(TrackingResult(customers=[c]), timestamp=t0, frame_number=1)
        time.sleep(0.2)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=2)
        # Dwell should be >0
        assert engine.tracks[1].current_zone_time > 0.1

    def test_completed_dwell(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c_in = make_customer(1, 50,50,150,200)
        t0 = time.time()
        engine.update(TrackingResult(customers=[c_in]), timestamp=t0, frame_number=1)
        time.sleep(0.2)
        c_out = make_customer(1, 500,400,600,500)
        events = engine.update(TrackingResult(customers=[c_out]), timestamp=time.time(), frame_number=2)
        exit_evt = next(e for e in events if e.event_type == "zone_exit")
        assert exit_evt.dwell_seconds > 0.1
        stat = engine.zone_stats[zone["zone_id"]]
        assert stat.total_dwell_seconds > 0

    def test_average_dwell(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        # Two visits
        c_in = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c_in]), timestamp=1000.0, frame_number=1)
        c_out = make_customer(1, 500,400,600,500)
        engine.update(TrackingResult(customers=[c_out]), timestamp=1010.0, frame_number=2)  # 10s dwell
        c_in2 = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c_in2]), timestamp=1020.0, frame_number=3)
        c_out2 = make_customer(1, 500,400,600,500)
        engine.update(TrackingResult(customers=[c_out2]), timestamp=1030.0, frame_number=4)  # 10s dwell
        stat = engine.zone_stats[zone["zone_id"]]
        assert stat.completed_visits == 2
        assert stat.average_dwell_seconds == 10.0


# ── Occupancy ─────────────────────────────────────────────────────────

class TestOccupancy:
    def test_one_customer_occupancy_1(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        assert engine.get_snapshot().zone_statistics[0].current_occupancy == 1

    def test_same_customer_many_frames_still_1(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        for i in range(5):
            engine.update(TrackingResult(customers=[c]), timestamp=time.time()+i*0.1, frame_number=i)
        assert engine.get_snapshot().zone_statistics[0].current_occupancy == 1

    def test_two_customers_occupancy_2(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c1 = make_customer(1, 50,50,150,200)
        c2 = make_customer(2, 60,60,160,210)
        engine.update(TrackingResult(customers=[c1,c2]), timestamp=time.time(), frame_number=1)
        assert engine.get_snapshot().zone_statistics[0].current_occupancy == 2

    def test_exit_decreases_occupancy(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        assert engine.get_snapshot().zone_statistics[0].current_occupancy == 1
        c_out = make_customer(1, 500,400,600,500)
        engine.update(TrackingResult(customers=[c_out]), timestamp=time.time()+0.1, frame_number=2)
        assert engine.get_snapshot().zone_statistics[0].current_occupancy == 0

    def test_lost_track_only_decreases_after_grace(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), lost_track_grace_seconds=1.0, zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        assert engine.get_snapshot().zone_statistics[0].current_occupancy == 1
        # Missing 1 frame (within grace)
        engine.update(TrackingResult(customers=[]), timestamp=time.time()+0.1, frame_number=2)
        assert engine.get_snapshot().zone_statistics[0].current_occupancy == 1
        # After grace
        import time as t
        t.sleep(1.1)
        engine.update(TrackingResult(customers=[]), timestamp=time.time(), frame_number=3)
        assert engine.get_snapshot().zone_statistics[0].current_occupancy == 0


# ── Counting ──────────────────────────────────────────────────────────

class TestCounting:
    def test_entries_exits(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        c_out = make_customer(1, 500,400,600,500)
        engine.update(TrackingResult(customers=[c_out]), timestamp=time.time()+0.1, frame_number=2)
        stat = engine.zone_stats[zone["zone_id"]]
        assert stat.total_entries == 1
        assert stat.total_exits == 1

    def test_current_customers(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c1 = make_customer(1, 50,50,150,200)
        c2 = make_customer(2, 60,60,160,210)
        engine.update(TrackingResult(customers=[c1,c2]), timestamp=time.time(), frame_number=1)
        snap = engine.get_snapshot()
        assert snap.active_customers == 2

    def test_unique_session(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        for i in [1,2,1,3]:
            c = make_customer(i, 50,50,150,200)
            engine.update(TrackingResult(customers=[c]), timestamp=time.time()+i, frame_number=i)
        assert len(engine.unique_customers) == 3


# ── Transitions ───────────────────────────────────────────────────────

class TestTransitions:
    def test_outside_to_a(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path, zone_rect=(0,0,400,600))
        # Add second zone
        zm = ZoneManager(str(zones_dir), str(maps_dir))
        zb = zm.create_rectangle(map_id, "Zone B", (400,0), (800,600))
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        # Need calibration for 800 map
        from app.phase2.calibration.homography import HomographyCalibrator
        from app.phase2.calibration.store import save_calibration as sc
        c = HomographyCalibrator()
        c.cctv_points = [[0,0],[640,0],[640,480],[0,480]]
        c.map_points = [[0,0],[800,0],[800,600],[0,600]]
        c.calibrate(camera_id="default_camera", map_id=map_id, camera_resolution=(640,480))
        sc(c.to_dict(), str(zones_dir.replace("zones","calibration") if False else str(tmp_path / "calibration")))
        # Actually use existing calib
        c2 = make_customer(1, 500,400,600,500)  # outside (map 625,625 outside both? need outside)
        # Outside point: camera (320,400) -> map (400,500) which is on boundary, let's use (600,400) -> map (750,500) outside A (0-400)
        c_out = make_customer(1, 600,400,700,500)
        engine.update(TrackingResult(customers=[c_out]), timestamp=time.time(), frame_number=1)
        assert engine.tracks[1].current_zone_id is None
        c_in = make_customer(1, 50,50,150,200)  # inside A
        events = engine.update(TrackingResult(customers=[c_in]), timestamp=time.time()+0.1, frame_number=2)
        assert any(e.event_type == "zone_entry" and e.zone_id == zone["zone_id"] for e in events)

    def test_a_to_b(self, tmp_path):
        maps_dir = tmp_path / "maps2"
        zones_dir = tmp_path / "zones2"
        calib_dir = tmp_path / "calib2"
        from PIL import Image
        import tempfile
        m = MapManager(str(maps_dir))
        src = tmp_path / "src2.png"
        Image.new("RGB", (800,600), (200,200,200)).save(src)
        meta = m.upload_map(str(src), name="Map2")
        map_id = meta["map_id"]
        zm = ZoneManager(str(zones_dir), str(maps_dir))
        za = zm.create_rectangle(map_id, "Zone A", (0,0), (400,600))
        zb = zm.create_rectangle(map_id, "Zone B", (400,0), (800,600))
        c = HomographyCalibrator()
        c.cctv_points = [[0,0],[640,0],[640,480],[0,480]]
        c.map_points = [[0,0],[800,0],[800,600],[0,600]]
        c.calibrate(camera_id="default_camera", map_id=map_id, camera_resolution=(640,480))
        save_calibration(c.to_dict(), str(calib_dir))
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c_a = make_customer(1, 50,50,150,200)  # A
        engine.update(TrackingResult(customers=[c_a]), timestamp=time.time(), frame_number=1)
        c_b = make_customer(1, 500,200,600,300)  # B (bottom-center 550,300 -> map 687,375 inside B)
        events = engine.update(TrackingResult(customers=[c_b]), timestamp=time.time()+0.1, frame_number=2)
        assert any(e.event_type == "zone_exit" for e in events)
        assert any(e.event_type == "zone_entry" for e in events)
        assert any(e.event_type == "zone_transition" for e in events)
        assert engine.tracks[1].current_zone_id == zb["zone_id"]


# ── Boundary hysteresis ───────────────────────────────────────────────

class TestBoundary:
    def test_boundary_jitter(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path, zone_rect=(100,100,300,300))
        # Use confirmation 3
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=3)
        # Inside point
        c_inside = make_customer(1, 100,100,200,200)  # bottom-center (150,200) -> map (187,250) inside
        engine.update(TrackingResult(customers=[c_inside]), timestamp=time.time(), frame_number=1)
        assert engine.tracks[1].current_zone_id == zone["zone_id"]
        # One frame outside (should not immediately exit due to hysteresis)
        c_out = make_customer(1, 500,400,600,500)  # outside
        engine.update(TrackingResult(customers=[c_out]), timestamp=time.time()+0.1, frame_number=2)
        # Still should be inside because need 3 frames
        assert engine.tracks[1].current_zone_id == zone["zone_id"]
        # Second outside
        engine.update(TrackingResult(customers=[c_out]), timestamp=time.time()+0.2, frame_number=3)
        assert engine.tracks[1].current_zone_id == zone["zone_id"]
        # Third outside -> now should exit
        events = engine.update(TrackingResult(customers=[c_out]), timestamp=time.time()+0.3, frame_number=4)
        assert engine.tracks[1].current_zone_id is None
        assert any(e.event_type == "zone_exit" for e in events)


# ── Analytics snapshot ────────────────────────────────────────────────

class TestSnapshot:
    def test_snapshot(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        snap = engine.get_snapshot()
        assert snap.active_customers == 1
        assert snap.total_entries == 1
        assert snap.zone_statistics[0].current_occupancy == 1
        assert snap.tracking_status in ("running", "idle")

    def test_events(self, tmp_path):
        map_id, zones_dir, maps_dir, calib_dir, zone = create_map_and_zone(tmp_path)
        engine = AnalyticsEngine(map_id=map_id, zones_dir=str(zones_dir), maps_dir=str(maps_dir), calibration_dir=str(calib_dir), camera_resolution=(640,480), zone_confirmation_frames=1)
        c = make_customer(1, 50,50,150,200)
        engine.update(TrackingResult(customers=[c]), timestamp=time.time(), frame_number=1)
        assert len(engine.get_events()) >= 1
        assert engine.get_events()[0].event_type in ("zone_entry", "track_started")


"""FastAPI backend for MONETIZE Admin Dashboard.

Serves:
- CCTV stream (MJPEG) from test 1.mp4 (future RTSP)
- Zones via ZoneManager/ZoneEngine
- Customers via CCTV service
- Mock data for incomplete backends (clearly marked DEMO)

Frontend: served as static files from dashboard/dist (Vite build)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse

from app.config import PROJECT_ROOT
from app.phase2.maps.manager import get_map_manager
from app.phase2.zones.manager import get_zone_manager
from app.phase2.zones.engine import ZoneEngine
from app.api.cctv import (
    start_cctv_service, get_latest_frame, get_latest_customers, get_latest_analytics, get_latest_events,
    get_active_camera_info, set_active_camera_id, set_active_camera, reload_cctv_zones,
)
from app.api.cameras import list_cameras as cam_list, create_camera as cam_create, get_camera as cam_get, update_camera as cam_update, delete_camera as cam_delete, test_camera_connection, set_demo_active, get_demo_status, is_demo_active
from fastapi import UploadFile, File, Form
import shutil
import uuid

app = FastAPI(title="MONETIZE Admin API", version="2.5A")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Start CCTV service on startup
@app.on_event("startup")
async def startup():
    try:
        start_cctv_service()
    except Exception as e:
        print(f"CCTV service failed: {e}")

# ── System Status ───────────────────────────────────────────────────
@app.get("/api/system/status")
def system_status():
    # Real checks where possible, DEMO where not
    cctv_online = Path(PROJECT_ROOT / "test 1.mp4").exists()
    # Check if zones exist
    try:
        mgr = get_map_manager()
        sel = mgr.get_selected_map()
        zone_engine_ok = sel is not None
        zone_count = 0
        if sel:
            zm = get_zone_manager()
            zone_count = len(zm.get_zones(sel["map_id"]))
    except:
        zone_engine_ok = False
        zone_count = 0

    return {
        "cctv": {"status": "Online" if cctv_online else "Offline", "mode": "DEMO" if cctv_online else "Offline", "source": "test 1.mp4"},
        "detection": {"status": "Running", "mode": "Running"},
        "tracking": {"status": "Running", "mode": "Running"},
        "zone_engine": {"status": "Running" if zone_engine_ok else "Offline", "mode": "Running" if zone_count>0 else "Demo", "zones": zone_count},
        "alert_engine": {"status": "Demo Mode", "mode": "Demo"},
        "pos_integration": {"status": "Not Connected", "mode": "Offline"},
        "system_online": True,
    }

# ── CCTV ───────────────────────────────────────────────────────────
@app.get("/api/cctv/status")
def cctv_status():
    p = PROJECT_ROOT / "test 1.mp4"
    cap = cv2.VideoCapture(str(p))
    ok = cap.isOpened()
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if ok else 0
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if ok else 0
    fps = cap.get(cv2.CAP_PROP_FPS) if ok else 0
    cap.release()
    return {
        "camera": "Test Camera",
        "source": "test 1.mp4",
        "status": "Live" if ok else "Offline",
        "mode": "DEMO",
        "fps": 6,
        "resolution": [w, h],
        "customers": len(get_latest_customers()),
    }

@app.get("/api/cctv/stream")
def cctv_stream():
    def gen():
        while True:
            frame = get_latest_frame(annotated=True)
            if frame is None:
                # placeholder
                frame = (255 * np.ones((480, 640, 3), dtype=np.uint8))
                cv2.putText(frame, "Loading CCTV...", (20, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
            _, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
            time.sleep(0.05)
    import numpy as np
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/cctv/snapshot")
def cctv_snapshot():
    import numpy as np
    frame = get_latest_frame(annotated=True)
    if frame is None:
        return JSONResponse({"error": "No frame"}, status_code=503)
    _, jpeg = cv2.imencode(".jpg", frame)
    return Response(jpeg.tobytes(), media_type="image/jpeg")

# ── Zones ───────────────────────────────────────────────────────────
def _enrich_zones_for_map(map_id: str, map_name: str = "") -> dict:
    zm = get_zone_manager()
    zones = zm.get_zones(map_id)
    customers = get_latest_customers()
    occupancy: dict[str, int] = {z["zone_id"]: 0 for z in zones}
    cust_by_zone: dict[str, list[str]] = {z["zone_id"]: [] for z in zones}
    try:
        engine = ZoneEngine(map_id)
        for c in customers:
            zid = c.get("zone_id")
            if zid and zid in occupancy:
                occupancy[zid] += 1
                cust_by_zone[zid].append(c.get("customer_id", ""))
            else:
                mp = c.get("map_position")
                if mp and isinstance(mp, (list, tuple)) and len(mp) == 2:
                    z = engine.get_zone_for_point(float(mp[0]), float(mp[1]))
                    if z and z["zone_id"] in occupancy:
                        occupancy[z["zone_id"]] += 1
                        cust_by_zone[z["zone_id"]].append(c.get("customer_id", ""))
    except Exception:
        pass

    # Enrich from Analytics snapshot if available
    analytics = get_latest_analytics()
    zone_stats_map = {}
    if analytics and hasattr(analytics, "zone_statistics"):
        for zs in analytics.zone_statistics:
            zone_stats_map[zs.zone_id] = zs

    enriched = []
    for z in zones:
        occ = occupancy.get(z["zone_id"], 0)
        stat = zone_stats_map.get(z["zone_id"])
        enriched.append({
            **z,
            "customers": occ,
            "occupancy": occ,
            "customer_ids": cust_by_zone.get(z["zone_id"], []),
            "status": "Busy" if occ >= 5 else ("Active" if occ > 0 else "Normal"),
            "entries": stat.total_entries if stat else 0,
            "exits": stat.total_exits if stat else 0,
            "avg_dwell_time": stat.avg_dwell_time if stat else 0.0,
        })
    return {
        "map_id": map_id,
        "map_name": map_name,
        "zones": enriched,
        "mode": "Running" if zones else "Demo"
    }

@app.get("/api/zones")
def list_zones():
    try:
        mgr = get_map_manager()
        sel = mgr.get_selected_map()
        if not sel:
            return {"map_id": None, "zones": [], "mode": "Demo", "message": "No map selected"}
        return _enrich_zones_for_map(sel["map_id"], sel.get("name", ""))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/zones/map")
def get_map_info():
    try:
        mgr = get_map_manager()
        sel = mgr.get_selected_map()
        if not sel:
            return JSONResponse({"error": "No map selected"}, status_code=404)
        return {**sel, "image_url": f"/api/maps/{sel['map_id']}/image"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Customers ───────────────────────────────────────────────────────
@app.get("/api/customers")
def list_customers():
    try:
        customers = get_latest_customers()
        # Real customers from CCTV pipeline (via ZoneTrackingIntegrator)
        # Each c already has: customer_id, track_id, bbox, center, bottom_center, zone_id, zone_name, map_position
        import random
        enriched = []
        for c in customers:
            # Use real zone assignment from integrator; fallback to Outside if no zone
            zone = c.get("zone_name")
            if zone is None:
                zone = "Outside" if c.get("map_position") is not None else "Unknown"
            # Status derived from real zone if available, else mock for demo where integrator not calibrated
            # For now, keep status as Inside/Moving based on zone presence
            status = c.get("status")
            if not status:
                if zone == "Outside":
                    status = "Moving"
                elif "Checkout" in zone:
                    status = "Waiting"
                else:
                    status = "Inside"
            enriched.append({
                "customer_id": c["customer_id"],
                "track_id": c["track_id"],
                "zone": zone,
                "zone_id": c.get("zone_id"),
                "status": status,
                "time_in_store": c.get("time_in_store") or f"{random.randint(2,25):02d}:{random.randint(10,59):02d}",
                "bbox": c.get("bbox"),
                "center": c.get("center"),
                "bottom_center": c.get("bottom_center"),
                "map_position": c.get("map_position"),
            })
        # If no real customers, return empty (not fake) — frontend will show empty state
        # Keep Demo mode indicator for empty to avoid pretending mock is real
        mode = "Running" if customers else "Demo"
        return {"customers": enriched, "count": len(enriched), "mode": mode}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Alerts (mock, replaceable) ─────────────────────────────────────
@app.get("/api/alerts")
def list_alerts():
    # Mock alerts — clearly DEMO
    alerts = [
        {"id": "a1", "severity": "critical", "type": "Queue", "message": "Payment queue exceeded threshold", "zone": "Checkout Zone", "customers": 5, "time": "2 minutes ago", "status": "Active", "mode": "Demo"},
        {"id": "a2", "severity": "warning", "type": "Wait", "message": "Customer waiting too long", "customer": "Customer_007", "zone": "Products Zone", "time": "4 minutes ago", "status": "Active", "mode": "Demo"},
        {"id": "a3", "severity": "info", "type": "Info", "message": "Checkout queue cleared", "time": "10 minutes ago", "status": "Resolved", "mode": "Demo"},
        {"id": "a4", "severity": "warning", "type": "Stock", "message": "Low stock: Product B", "time": "12 minutes ago", "status": "Acknowledged", "mode": "Demo"},
    ]
    return {"alerts": alerts, "mode": "Demo"}

@app.post("/api/alerts/{alert_id}/acknowledge")
def ack_alert(alert_id: str):
    return {"id": alert_id, "status": "Acknowledged", "mode": "Demo"}

@app.post("/api/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str):
    return {"id": alert_id, "status": "Resolved", "mode": "Demo"}

# ── Payments (mock) ─────────────────────────────────────────────────
@app.get("/api/payments")
def payments():
    import random
    queue = []
    for i in range(5):
        queue.append({
            "customer_id": f"Customer_{i+1:03d}",
            "waiting": f"{2-i%2:02d}:{random.randint(10,59):02d}",
            "status": "Waiting",
        })
    return {
        "queue": queue,
        "current": len(queue),
        "threshold": 5,
        "status": "Busy" if len(queue) >= 5 else "Normal",
        "mode": "Demo",
    }

# ── Inventory (mock) ────────────────────────────────────────────────
@app.get("/api/inventory")
def inventory(q: str = ""):
    items = [
        {"product": "Product A", "stock": 24, "status": "Normal"},
        {"product": "Product B", "stock": 3, "status": "Low Stock"},
        {"product": "Product C", "stock": 0, "status": "Out of Stock"},
        {"product": "Product D", "stock": 12, "status": "Normal"},
        {"product": "Product E", "stock": 7, "status": "Normal"},
        {"product": "Product F", "stock": 1, "status": "Low Stock"},
        {"product": "Instant Noodles", "stock": 45, "status": "Normal"},
        {"product": "Cold Drinks", "stock": 2, "status": "Low Stock"},
    ]
    if q:
        items = [i for i in items if q.lower() in i["product"].lower()]
    return {"items": items, "mode": "Demo"}

# ── Analytics (mock) ────────────────────────────────────────────────
# ── Phase 3 Analytics (real) ────────────────────────────────────────
@app.get("/api/analytics/tracking")
def analytics_tracking():
    snap = get_latest_analytics()
    if snap:
        return snap.to_dict()
    return {"active_customers": 0, "total_unique_customers": 0, "total_occupancy": 0, "zone_statistics": [], "tracking_status": "idle", "mode": "Demo"}

@app.get("/api/analytics/events")
def analytics_events(limit: int = 50):
    evts = get_latest_events()
    return {"events": [e.to_dict() for e in evts[-limit:]], "mode": "Running" if evts else "Demo"}

@app.get("/api/analytics")
def analytics():
    return {
        "today_sales": 48250,
        "bills": 42,
        "items_sold": 183,
        "sales_over_time": [
            {"time": "09:00", "sales": 3200},
            {"time": "10:00", "sales": 5400},
            {"time": "11:00", "sales": 4100},
            {"time": "12:00", "sales": 6800},
            {"time": "13:00", "sales": 7200},
            {"time": "14:00", "sales": 5900},
            {"time": "15:00", "sales": 8300},
            {"time": "16:00", "sales": 7300},
        ],
        "top_products": [
            {"name": "Cold Drinks", "sales": 45},
            {"name": "Snacks", "sales": 38},
            {"name": "Instant Noodles", "sales": 32},
            {"name": "Product A", "sales": 24},
        ],
        "category_sales": [
            {"name": "Beverages", "value": 40},
            {"name": "Snacks", "value": 30},
            {"name": "Groceries", "value": 20},
            {"name": "Others", "value": 10},
        ],
        "mode": "Demo",
    }

@app.get("/api/dashboard/summary")
def dashboard_summary():
    customers = get_latest_customers()
    # Real data for customers, mock for others where backend not ready
    # total_customers = currently tracked (real)
    # currently_inside = those with zone != Outside and map_position valid
    real_inside = 0
    for c in customers:
        if c.get("zone_name") and c["zone_name"] != "Outside":
            real_inside += 1
        elif c.get("map_position") is not None:
            # If no zone system, consider inside if has map position
            real_inside += 1
    return {
        "total_customers": len(customers) if customers else 0,
        "currently_inside": real_inside if customers else 0,
        "payment_queue": 5,
        "active_alerts": 2,
        "mode": "Running" if customers else "Demo",
    }

# ── Cameras ─────────────────────────────────────────────────────────
@app.get("/api/cameras")
def api_list_cameras():
    return {"cameras": cam_list(), "mode": "Running"}

@app.post("/api/cameras")
def api_create_camera(payload: dict):
    try:
        cam = cam_create(payload)
        return cam
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.get("/api/cameras/{camera_id}")
def api_get_camera(camera_id: str):
    cam = cam_get(camera_id)
    if not cam:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return cam

@app.put("/api/cameras/{camera_id}")
def api_update_camera(camera_id: str, payload: dict):
    cam = cam_update(camera_id, payload)
    if not cam:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return cam

@app.delete("/api/cameras/{camera_id}")
def api_delete_camera(camera_id: str):
    ok = cam_delete(camera_id)
    if not ok:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"success": True}

@app.post("/api/cameras/{camera_id}/test")
def api_test_camera(camera_id: str):
    result = test_camera_connection(camera_id)
    return result

@app.post("/api/cameras/{camera_id}/connect")
def api_connect_camera(camera_id: str):
    from app.api.cameras import set_camera_status, STATUS_CONNECTED
    cam = cam_get(camera_id)
    if not cam:
        return JSONResponse({"error": "Not found"}, status_code=404)
    # Test first
    result = test_camera_connection(camera_id)
    if not result.get("success"):
        from app.api.cameras import set_camera_status, STATUS_ERROR
        set_camera_status(camera_id, STATUS_ERROR)
        return JSONResponse({"success": False, "error": result.get("error")}, status_code=400)
    set_camera_status(camera_id, STATUS_CONNECTED)
    # Set as active
    try:
        from app.api.cctv import set_active_camera_id
        set_active_camera_id(camera_id)
    except: pass
    return {"success": True, "camera": cam_get(camera_id)}

@app.post("/api/cameras/{camera_id}/disconnect")
def api_disconnect_camera(camera_id: str):
    from app.api.cameras import set_camera_status, STATUS_DISCONNECTED
    set_camera_status(camera_id, STATUS_DISCONNECTED)
    return {"success": True}

@app.get("/api/cameras/active/status")
def api_active_camera_status():
    try:
        info = get_active_camera_info()
        return info
    except Exception as e:
        return {"status": "NOT_CONFIGURED", "mode": "Offline", "error": str(e)}

@app.post("/api/cameras/active/{camera_id}")
def api_set_active(camera_id: str):
    try:
        from app.api.cctv import set_active_camera_id
        set_active_camera_id(camera_id)
        return {"success": True, "active": camera_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Demo ───────────────────────────────────────────────────────────────
@app.get("/api/demo/status")
def api_demo_status():
    return get_demo_status()

@app.post("/api/demo/start")
def api_demo_start():
    # Use TestVideoSource
    from app.api.cameras import set_demo_active as demo_on
    demo_on(True, camera_id="demo")
    # Also ensure active camera is demo
    try:
        from app.api.cctv import set_active_camera_id
        # Create demo camera if not exists
        cams = cam_list()
        demo = next((c for c in cams if c.get("source_type") == "demo"), None)
        if not demo:
            demo = cam_create({"name": "Demo Camera", "source_type": "demo", "rtsp_url": "test 1.mp4"})
        set_active_camera_id(demo["id"])
    except: pass
    return {"success": True, "mode": "DEMO", "source": "test 1.mp4"}

@app.post("/api/demo/stop")
def api_demo_stop():
    from app.api.cameras import set_demo_active as demo_off
    demo_off(False)
    return {"success": True}

# ── Maps (Admin Board) ─────────────────────────────────────────────────
@app.get("/api/maps")
def api_list_maps():
    try:
        mgr = get_map_manager()
        maps = mgr.list_maps()
        sel = mgr.get_selected_map_id()
        enriched_maps = []
        for m in maps:
            enriched_maps.append({
                **m,
                "image_url": f"/api/maps/{m['map_id']}/image"
            })
        return {"maps": enriched_maps, "selected": sel, "mode": "Running"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/maps/{map_id}")
def api_get_map(map_id: str):
    try:
        mgr = get_map_manager()
        meta = mgr.get_map(map_id)
        if not meta:
            return JSONResponse({"error": "Map not found"}, status_code=404)
        return {**meta, "image_url": f"/api/maps/{map_id}/image"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/maps/{map_id}/image")
def api_get_map_image(map_id: str):
    try:
        mgr = get_map_manager()
        meta = mgr.get_map(map_id)
        if not meta:
            return JSONResponse({"error": "Map not found"}, status_code=404)
        p = Path(meta.get("image_path", ""))
        if not p.exists():
            return JSONResponse({"error": "Image file not found"}, status_code=404)
        return FileResponse(str(p))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/maps/upload")
async def api_upload_map(file: UploadFile = File(...), name: str = Form(None)):
    try:
        suffix = Path(file.filename).suffix or ".png"
        tmp = Path(PROJECT_ROOT / "maps" / f"tmp_{uuid.uuid4().hex}{suffix}")
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)
        mgr = get_map_manager()
        meta = mgr.upload_map(str(tmp), name or Path(file.filename).stem)
        try: tmp.unlink()
        except: pass
        reload_cctv_zones(meta["map_id"])
        return {**meta, "image_url": f"/api/maps/{meta['map_id']}/image"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/api/maps/{map_id}/select")
def api_select_map(map_id: str):
    try:
        mgr = get_map_manager()
        ok = mgr.select_map(map_id)
        if not ok:
            return JSONResponse({"error": "Map not found"}, status_code=404)
        reload_cctv_zones(map_id)
        return {"success": True, "selected": map_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/api/maps/{map_id}")
def api_delete_map(map_id: str):
    try:
        mgr = get_map_manager()
        sel = mgr.get_selected_map_id()
        ok = mgr.delete_map(map_id)
        if not ok:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if sel == map_id:
            remaining = mgr.list_maps()
            if remaining:
                mgr.select_map(remaining[0]["map_id"])
                reload_cctv_zones(remaining[0]["map_id"])
            else:
                mgr.clear_selection()
                reload_cctv_zones(None)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Per-Map Zones Endpoints ──────────────────────────────────────────
@app.get("/api/maps/{map_id}/zones")
def api_get_map_zones(map_id: str):
    try:
        mgr = get_map_manager()
        meta = mgr.get_map(map_id)
        name = meta["name"] if meta else map_id
        return _enrich_zones_for_map(map_id, name)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.put("/api/maps/{map_id}/zones")
def api_save_map_zones(map_id: str, payload: Any):
    """Authoritative bulk save of all zones for a map."""
    try:
        mgr = get_map_manager()
        if not mgr.has_map(map_id):
            return JSONResponse({"error": f"Map '{map_id}' not found"}, status_code=404)
        
        if isinstance(payload, dict):
            zones_data = payload.get("zones", [])
        elif isinstance(payload, list):
            zones_data = payload
        else:
            return JSONResponse({"error": "Payload must be a list of zones or object with 'zones' key"}, status_code=400)
        
        zm = get_zone_manager()
        zm.save_zones(map_id, zones_data)
        reload_cctv_zones(map_id)
        return {
            "success": True,
            "map_id": map_id,
            "count": len(zones_data),
            "zones": zm.get_zones(map_id),
        }
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/maps/{map_id}/zones")
def api_add_map_zone(map_id: str, payload: dict):
    try:
        mgr = get_map_manager()
        if not mgr.has_map(map_id):
            return JSONResponse({"error": f"Map '{map_id}' not found"}, status_code=404)
        zm = get_zone_manager()
        name = payload.get("name", "").strip()
        if not name:
            return JSONResponse({"error": "Zone name cannot be empty"}, status_code=400)
        
        if "points" in payload:
            points = payload["points"]
            zone_type = payload.get("type", "rectangle")
            zone = zm.add_zone(map_id, name, points, zone_type)
        elif "p1" in payload and "p2" in payload:
            zone = zm.create_rectangle(map_id, name, tuple(payload["p1"]), tuple(payload["p2"]))
        else:
            return JSONResponse({"error": "Either 'points' or 'p1' and 'p2' are required"}, status_code=400)
        
        reload_cctv_zones(map_id)
        return {"success": True, "zone": zone}
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.put("/api/maps/{map_id}/zones/{zone_id}")
def api_update_map_zone(map_id: str, zone_id: str, payload: dict):
    try:
        mgr = get_map_manager()
        if not mgr.has_map(map_id):
            return JSONResponse({"error": f"Map '{map_id}' not found"}, status_code=404)
        zm = get_zone_manager()
        name = payload.get("name")
        points = payload.get("points")
        ok = zm.update_zone(map_id, zone_id, name=name, points=points)
        if not ok:
            return JSONResponse({"error": f"Zone '{zone_id}' not found"}, status_code=404)
        reload_cctv_zones(map_id)
        return {"success": True, "zone": zm.get_zone(map_id, zone_id)}
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/api/maps/{map_id}/zones/{zone_id}")
def api_delete_map_zone(map_id: str, zone_id: str):
    try:
        mgr = get_map_manager()
        if not mgr.has_map(map_id):
            return JSONResponse({"error": f"Map '{map_id}' not found"}, status_code=404)
        zm = get_zone_manager()
        ok = zm.delete_zone(map_id, zone_id)
        if not ok:
            return JSONResponse({"error": f"Zone '{zone_id}' not found"}, status_code=404)
        reload_cctv_zones(map_id)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Runtime status (combined) ─────────────────────────────────────────
@app.get("/api/runtime/status")
def runtime_status():
    try:
        cctv = get_active_camera_info() if 'get_active_camera_info' in globals() else {}
    except:
        cctv = {}
    try:
        mgr = get_map_manager()
        sel = mgr.get_selected_map()
        map_info = {"map_id": sel["map_id"], "name": sel["name"]} if sel else {"map_id": None}
    except:
        map_info = {"map_id": None}
    try:
        analytics = get_latest_analytics()
        analytics_info = analytics.to_dict() if analytics else {"active_customers": 0}
    except:
        analytics_info = {"active_customers": 0}
    return {
        "camera": cctv,
        "map": map_info,
        "analytics": analytics_info,
        "processing": {"detection": "running", "tracking": "running"},
    }

# ── Video file (for direct <video> fallback) ────────────────────────
@app.get("/test 1.mp4")
@app.get("/test1.mp4")
def serve_test_video():
    p = PROJECT_ROOT / "test 1.mp4"
    if p.exists():
        return FileResponse(str(p), media_type="video/mp4")
    return JSONResponse({"error": "Video not found"}, status_code=404)

# Serve maps images
@app.get("/maps/images/{filename}")
def serve_map_image(filename: str):
    p = PROJECT_ROOT / "maps" / "images" / filename
    if p.exists():
        return FileResponse(str(p))
    return JSONResponse({"error": "Not found"}, status_code=404)

# ── Static frontend (Vite build) ────────────────────────────────────
# In production, frontend built to dashboard/dist
dist_path = PROJECT_ROOT / "dashboard" / "dist"
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="frontend")
else:
    # Fallback for dev: serve a simple message
    @app.get("/")
    def root():
        return {"message": "MONETIZE Admin API — Frontend not built. Run: cd dashboard && npm run build"}

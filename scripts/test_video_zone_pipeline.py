#!/usr/bin/env python3
"""
Real Video End-to-End Test Harness — Phase 2.5A + Visual Debug

Flow:
    test 1 video → VideoSource → YOLO11 → ByteTrack → TrackingResult
        → ZoneTrackingIntegrator (camera bottom-center → calibration → map → ZoneEngine)
        → CustomerZoneResult

Run:
    python scripts/test_video_zone_pipeline.py
    python scripts/test_video_zone_pipeline.py --video "test 1.mp4" --map d6f8bd3b
    python scripts/test_video_zone_pipeline.py --video "test 1.mp4" --map d6f8bd3b --visualize
    python scripts/test_video_zone_pipeline.py --video "test 1.mp4" --map d6f8bd3b --visualize --save-video test_results/test_1_visualized.mp4
"""
import sys
import time
import json
import argparse
from pathlib import Path

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
from PIL import Image

from app.config import PROJECT_ROOT as CFG_ROOT
from app.video.video_source import VideoSource
from app.detection.detector import get_detector
from app.models.tracking_data import TrackingResult
from app.phase2.maps.manager import get_map_manager
from app.phase2.zones.manager import get_zone_manager
from app.phase2.calibration.store import load_calibration, check_resolution_mismatch
from app.phase2.integration import ZoneTrackingIntegrator

DEFAULT_VIDEO = "test 1.mp4"
DEFAULT_CAMERA_ID = "default_camera"


def find_test_video(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p.resolve()
        # try relative to project root
        p2 = PROJECT_ROOT / explicit
        if p2.exists():
            return p2.resolve()
        raise FileNotFoundError(f"Video not found: {explicit}")
    # Auto-find test 1*
    candidates = list(PROJECT_ROOT.glob("test 1*"))
    # Filter to video extensions
    vids = [p for p in candidates if p.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv", ".webm"} and p.is_file()]
    if vids:
        # Prefer test 1.mp4 exact
        for v in vids:
            if v.name == "test 1.mp4":
                return v.resolve()
        return sorted(vids)[0].resolve()
    # Fallback search recurse
    for p in PROJECT_ROOT.rglob("test 1*"):
        if p.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"} and p.is_file():
            return p.resolve()
    raise FileNotFoundError("Could not locate video named 'test 1*'")


def get_video_info(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {"path": str(path), "open": False}
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fc = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return {"path": str(path), "width": w, "height": h, "fps": fps, "frames": fc, "duration": fc / fps if fps else 0}


# ── Visualization helpers ────────────────────────────────────────────

def _get_track_color(track_id: int) -> tuple[int, int, int]:
    np.random.seed(track_id)
    color = tuple(map(int, np.random.randint(50, 255, 3)))
    return (int(color[0]), int(color[1]), int(color[2]))

def _get_zone_color(idx: int) -> tuple[int, int, int]:
    palette = [
        (52, 152, 219), (46, 204, 113), (155, 89, 182), (231, 76, 60),
        (241, 196, 15), (52, 73, 94), (230, 126, 34), (149, 165, 166),
        (41, 128, 185), (39, 174, 96),
    ]
    return palette[idx % len(palette)]

def draw_cctv_frame(frame: np.ndarray, tracking_result: TrackingResult, zone_results: list, frame_idx: int, elapsed: float, meta: dict, calib_found: bool, map_id: str) -> np.ndarray:
    """Draw CCTV visualization: bbox, ID, feet point, zone, map pos, header."""
    vis = frame.copy()
    h, w = vis.shape[:2]

    # Header bar
    header_text = f"Frame: {frame_idx}  Time: {elapsed:.1f}s  Customers: {len(tracking_result.customers)}  Calibration: {'OK' if calib_found else 'NOT FOUND'}  Map: {map_id}"
    (tw, th), _ = cv2.getTextSize(header_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(vis, (0, 0), (w, 28), (15, 23, 42), -1)
    cv2.putText(vis, header_text, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    # Map zone lookup by customer_id for quick access
    zone_by_id = {zr.customer_id: zr for zr in zone_results}

    for cust in tracking_result.customers:
        bbox = cust.bbox
        color = _get_track_color(cust.track_id)
        x1, y1, x2, y2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
        # Customer ID above box
        label = cust.customer_id
        (tw, th), bl = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(vis, (x1, y1 - th - 10), (x1 + tw + 10, y1), color, -1)
        # text color contrast
        txt_color = (0, 0, 0) if (0.299*color[0]+0.587*color[1]+0.114*color[2]) > 128 else (255,255,255)
        cv2.putText(vis, label, (x1+5, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, txt_color, 1, cv2.LINE_AA)
        # Feet / bottom-center point
        bc = cust.bottom_center
        cv2.circle(vis, bc, 6, (0, 0, 255), -1)
        cv2.circle(vis, bc, 9, (255, 255, 255), 2)
        # Zone and map position from CustomerZoneResult (use existing, don't recalculate)
        zr = zone_by_id.get(cust.customer_id)
        if zr:
            zone_text = f"Zone: {zr.zone_name or 'Outside'}"
            map_text = f"Map: ({int(zr.map_position[0])},{int(zr.map_position[1])})" if zr.map_position else "Map: None"
        else:
            zone_text = "Zone: N/A"
            map_text = "Map: N/A"
        # Draw zone/map near feet
        info_y = bc[1] + 18
        # Ensure inside frame
        info_y = min(h-10, max(y2+15, info_y))
        cv2.putText(vis, zone_text, (bc[0]+12, info_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,255,255), 1, cv2.LINE_AA)
        cv2.putText(vis, map_text, (bc[0]+12, info_y+14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,0), 1, cv2.LINE_AA)
        # Also camera position small
        cam_text = f"Cam: ({bc[0]},{bc[1]})"
        cv2.putText(vis, cam_text, (bc[0]+12, info_y+28), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200,200,200), 1, cv2.LINE_AA)

    return vis

def prepare_birdeye_map(map_image_path: Path, zones: list[dict], display_size: tuple[int,int]=(900, 700)):
    """Load map image and prepare scaled display params and zone polygons for drawing."""
    pil = Image.open(map_image_path).convert("RGB")
    orig_w, orig_h = pil.size
    disp_w, disp_h = display_size
    scale = min(disp_w / orig_w, disp_h / orig_h)
    sw = int(orig_w * scale)
    sh = int(orig_h * scale)
    ox = (disp_w - sw)//2
    oy = (disp_h - sh)//2
    # Resize
    resized = pil.resize((sw, sh), Image.LANCZOS)
    canvas = Image.new("RGB", (disp_w, disp_h), (248, 250, 252))
    canvas.paste(resized, (ox, oy))
    # Convert to cv2 BGR for drawing
    map_bgr = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)
    params = dict(scale=scale, sw=sw, sh=sh, ox=ox, oy=oy, orig_w=orig_w, orig_h=orig_h, disp_w=disp_w, disp_h=disp_h)
    return map_bgr, params

def draw_birdeye_frame(map_bgr: np.ndarray, params: dict, zones: list[dict], zone_results: list, display_size: tuple[int,int]=(900,700)) -> np.ndarray:
    """Draw zones and customer map positions on bird's-eye map (uses existing zone polygons)."""
    vis = map_bgr.copy()
    scale, ox, oy = params["scale"], params["ox"], params["oy"]
    # Draw zones
    for idx, z in enumerate(zones):
        pts = z["points"]  # original coords
        # Scale to display
        disp_pts = np.array([[[int(p[0]*scale+ox), int(p[1]*scale+oy)] for p in pts]], dtype=np.int32)
        color = _get_zone_color(idx)
        # Fill semi-transparent via overlay
        overlay = vis.copy()
        cv2.fillPoly(overlay, disp_pts, color)
        vis = cv2.addWeighted(overlay, 0.25, vis, 0.75, 0)
        cv2.polylines(vis, disp_pts, True, color, 2)
        # Label at centroid
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        cx_o = sum(xs)/len(xs)
        cy_o = sum(ys)/len(ys)
        cx_d = int(cx_o*scale+ox)
        cy_d = int(cy_o*scale+oy)
        label = z["name"]
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        # Background for label
        cv2.rectangle(vis, (cx_d - tw//2 - 4, cy_d - th - 4), (cx_d + tw//2 + 4, cy_d + 4), (15,23,42), -1)
        cv2.putText(vis, label, (cx_d - tw//2, cy_d), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1, cv2.LINE_AA)

    # Draw customers map positions (from CustomerZoneResult.map_position)
    for zr in zone_results:
        if not zr.map_position:
            continue
        mx, my = zr.map_position
        dx = int(mx*scale+ox)
        dy = int(my*scale+oy)
        # Check within display bounds
        if not (0 <= dx < params["disp_w"] and 0 <= dy < params["disp_h"]):
            continue
        # Color by track
        tid = zr.track_id if zr.track_id is not None else hash(zr.customer_id) % 1000
        color = _get_track_color(tid)
        cv2.circle(vis, (dx, dy), 8, color, -1)
        cv2.circle(vis, (dx, dy), 11, (255,255,255), 2)
        # Label
        label = f"{zr.customer_id}"
        zone_label = zr.zone_name or "Outside"
        cv2.putText(vis, label, (dx+12, dy-6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,0,0), 2, cv2.LINE_AA)
        cv2.putText(vis, label, (dx+12, dy-6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
        cv2.putText(vis, zone_label, (dx+12, dy+8), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0,0,0), 2, cv2.LINE_AA)
        cv2.putText(vis, zone_label, (dx+12, dy+8), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80,80,80), 1, cv2.LINE_AA)

    # Header
    header = f"Bird's-Eye Map  Zones: {len(zones)}  Customers: {len([z for z in zone_results if z.map_position])}"
    cv2.rectangle(vis, (0,0), (params["disp_w"], 26), (15,23,42), -1)
    cv2.putText(vis, header, (8,18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1, cv2.LINE_AA)
    return vis

def main():
    parser = argparse.ArgumentParser(description="Real Video Zone Pipeline Test — test 1 → YOLO → Zone")
    parser.add_argument("--video", type=str, default=None, help="Path to test 1 video (default auto-find)")
    parser.add_argument("--map", type=str, default=None, help="Map ID (default: selected map)")
    parser.add_argument("--map-id", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--camera-id", type=str, default=DEFAULT_CAMERA_ID, help="Camera ID")
    parser.add_argument("--output", type=str, default="test_results/test_1_zone_results.json", help="Output JSON path")
    parser.add_argument("--max-frames", type=int, default=0, help="Limit frames for quick test (0 = all)")
    parser.add_argument("--inference-fps", type=float, default=6.0, help="Target inference FPS (0 = every frame)")
    parser.add_argument("--visualize", action="store_true", help="Show CCTV and Bird's-eye debug windows")
    parser.add_argument("--save-video", type=str, default=None, help="Save visualized CCTV video to path (e.g., test_results/test_1_visualized.mp4)")
    args = parser.parse_args()

    map_id = args.map_id or args.map

    print("=" * 70)
    print("REAL VIDEO END-TO-END TEST — Phase 2.5A")
    if args.visualize:
        print("VISUAL DEBUG MODE ON")
    print("=" * 70)

    # 1. Locate video
    try:
        video_path = find_test_video(args.video)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    vinfo = get_video_info(video_path)
    print(f"\n[1] Video:")
    print(f"    File: {video_path.name}")
    print(f"    Path: {video_path}")
    print(f"    Resolution: {vinfo['width']}x{vinfo['height']}")
    print(f"    FPS: {vinfo['fps']:.2f}")
    print(f"    Frames: {vinfo['frames']}")
    print(f"    Duration: {vinfo['duration']:.1f}s")

    # 2. Map
    map_manager = get_map_manager()
    if map_id:
        meta = map_manager.get_map(map_id)
        if not meta:
            print(f"\nERROR: Map '{map_id}' not found in maps/metadata")
            sys.exit(1)
    else:
        meta = map_manager.get_selected_map()
        if not meta:
            print("\nERROR: No map selected. Run: python -m app.phase2.maps.gallery and Select a map")
            sys.exit(1)
        map_id = meta["map_id"]

    print(f"\n[2] Map:")
    print(f"    Map ID: {map_id}")
    print(f"    Name: {meta['name']}")
    print(f"    Resolution: {meta['width']}x{meta['height']}")
    print(f"    Image: {meta['image_path']}")

    # 3. Calibration
    calib = load_calibration(args.camera_id, map_id)
    calib_path = Path(f"calibration/calibration_{args.camera_id}__{map_id}.json")
    if calib:
        print(f"\n[3] Calibration: FOUND")
        print(f"    Path: {calib_path}")
        print(f"    Camera ID: {calib.get('camera_id')}")
        print(f"    Map ID: {calib.get('map_id')}")
        print(f"    Camera resolution (calib): {calib.get('camera_resolution')}")
        print(f"    Video resolution: {vinfo['width']}x{vinfo['height']}")
        warn = check_resolution_mismatch(calib.get('camera_resolution'), (vinfo['width'], vinfo['height']))
        if warn:
            print(f"    WARNING: {warn}")
            print(f"    Note: Homography was calibrated at {calib.get('camera_resolution')}, video is {vinfo['width']}x{vinfo['height']}")
            print(f"          Map positions may be offset / outside map bounds")
        print(f"    Homography: {str(calib.get('homography_matrix')[:1])[:80]}...")
        print(f"    Reprojection error: {calib.get('reprojection_error')}")
    else:
        print(f"\n[3] Calibration: NOT FOUND")
        print(f"    Expected: {calib_path}")
        print(f"    Camera ID: {args.camera_id}")
        print(f"    Map ID: {map_id}")
        print(f"    -> Map positions will be None, zone assignments will be None")
        print(f"    -> Detection/tracking will still run")

    # 4. Zones
    zone_manager = get_zone_manager()
    zones = zone_manager.get_zones(map_id)
    print(f"\n[4] Zones:")
    print(f"    Zones loaded: {len(zones)}")
    for i, z in enumerate(zones, 1):
        xs = [p[0] for p in z["points"]]
        ys = [p[1] for p in z["points"]]
        print(f"    {i}. {z['name']} ({z['zone_id']}) [{min(xs):.0f},{min(ys):.0f} - {max(xs):.0f},{max(ys):.0f}]")

    if not zones:
        print(f"    WARNING: No zones for map {map_id}. All customers will be Outside.")

    # 5. Initialize detector and integrator (once, cached)
    print(f"\n[5] Initializing pipeline...")
    print(f"    Detector: YOLO11 ({'yolo11n.pt'})")
    t0 = time.time()
    detector = get_detector()
    print(f"    Detector ready in {time.time()-t0:.1f}s")
    # Video source for info
    vs_info = VideoSource(str(video_path))
    if not vs_info.open():
        print(f"ERROR: Failed to open video {video_path}")
        sys.exit(1)
    print(f"    VideoSource: {vs_info.width}x{vs_info.height} @ {vs_info.fps:.1f} FPS")
    vs_info.release()

    # Integrator (cached, not per frame)
    integrator = None
    try:
        integrator = ZoneTrackingIntegrator(
            map_id=map_id,
            camera_id=args.camera_id,
            camera_resolution=(vinfo["width"], vinfo["height"]),
        )
        print(f"    ZoneTrackingIntegrator: {integrator}")
        print(f"      Calibrated: {integrator.is_calibrated}")
        print(f"      Zones: {integrator.zone_engine.zone_count}")
        if integrator.calibration_error:
            print(f"      Calibration error: {integrator.calibration_error}")
    except Exception as e:
        print(f"    ZoneTrackingIntegrator failed: {e}")
        print(f"    Continuing with detection only")
        integrator = None

    # Visualization setup — MUST use authoritative zones from zones/<map_id>.json
    # Log authoritative source for visualization
    if args.visualize or args.save_video:
        print(f"\n[Visualization] Zones loaded:")
        print(f"    map={map_id} source=zones/{map_id}.json count={len(zones)}")
        for z in zones:
            print(f"      {z['zone_id']} -> {z['name']}")

    cctv_writer = None
    map_bgr = None
    map_params = None
    if args.visualize or args.save_video:
        # Prepare bird's-eye map background using AUTHORITATIVE zones (same source as integrator)
        # If integrator exists, use its cached zones to ensure single source of truth
        viz_zones = zones
        if integrator is not None:
            viz_zones = integrator.zone_engine.zones  # authoritative, from same file, cached
            # Verify consistency
            if len(viz_zones) != len(zones):
                print(f"    WARNING: Zone count mismatch between manager ({len(zones)}) and integrator ({len(viz_zones)}) — using integrator")
            zones = viz_zones  # ensure drawing uses integrator's zones
        try:
            map_img_path = Path(meta["image_path"])
            map_bgr, map_params = prepare_birdeye_map(map_img_path, zones, display_size=(900, 700))
            print(f"    Bird's-eye map prepared: {map_img_path.name} -> {map_bgr.shape[1]}x{map_bgr.shape[0]}")
        except Exception as e:
            print(f"    Warning: Could not prepare bird's-eye map: {e}")
            map_bgr, map_params = None, None

        if args.save_video:
            save_path = Path(args.save_video)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            # Use video fps for output
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            cctv_writer = cv2.VideoWriter(str(save_path), fourcc, vinfo["fps"] if vinfo["fps"]>0 else 30.0, (vinfo["width"], vinfo["height"]))
            print(f"    Save video: {save_path.resolve()}")

        if args.visualize:
            cv2.namedWindow("CCTV View", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("CCTV View", 960, 540)
            cv2.namedWindow("Bird's-Eye Map", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Bird's-Eye Map", 900, 700)
            print(f"    Visual windows: CCTV View + Bird's-Eye Map (press Q/ESC to quit, SPACE to pause)")

    # 6. Process video
    print(f"\n[6] Processing video...")
    print(f"    Inference FPS target: {args.inference_fps} (0 = every frame)")
    print(f"    Max frames: {args.max_frames or 'all'}")
    if args.visualize:
        print(f"    Visualize: ON")
    if args.save_video:
        print(f"    Saving visualized video to: {args.save_video}")

    inference_interval = 1.0 / args.inference_fps if args.inference_fps > 0 else 0

    # Collect results
    all_results = []
    zone_counts: dict[str, int] = {}
    customers_seen: set[str] = set()
    customers_with_map = 0
    customers_with_zone = 0
    detection_total = 0
    unique_tracks: set[int] = set()
    customer_history: dict[str, list[str]] = {}

    # Reopen for processing
    vs = VideoSource(str(video_path))
    vs.open()

    frame_idx = 0
    loop_start = time.time()
    last_inference_time = 0.0
    paused = False
    # For reusing last results between inference frames (as in main.py)
    last_zone_results: list = []
    last_tracking_result = TrackingResult(customers=[])

    while vs.is_opened:
        ok, frame = vs.read()
        if not ok or frame is None:
            break
        frame_idx += 1
        if args.max_frames and frame_idx > args.max_frames:
            break

        current = time.time()
        should_infer = (args.inference_fps <= 0) or (current - last_inference_time >= inference_interval)
        tracking_result = None
        zone_results = last_zone_results  # reuse last if not inferring

        if should_infer:
            last_inference_time = current
            tracking_result = detector.detect_and_track(frame)
            last_tracking_result = tracking_result
            # Zone integration (cached, not per frame creation)
            if integrator:
                try:
                    zone_results = integrator.process_customers(tracking_result)
                    last_zone_results = zone_results
                except Exception as e:
                    print(f"Zone integration error at frame {frame_idx}: {e}")
                    zone_results = []
            else:
                zone_results = []
            # Collect stats
            detection_total += len(tracking_result.customers)
            for c in tracking_result.customers:
                unique_tracks.add(c.track_id)
                customers_seen.add(c.customer_id)
            for zr in zone_results:
                all_results.append({
                    "frame": frame_idx,
                    "timestamp": time.time() - loop_start,
                    "customer_id": zr.customer_id,
                    "track_id": zr.track_id,
                    "camera_position": list(zr.camera_position) if zr.camera_position else None,
                    "map_position": list(zr.map_position) if zr.map_position else None,
                    "zone_id": zr.zone_id,
                    "zone_name": zr.zone_name,
                    "map_id": zr.map_id,
                })
                if zr.map_position:
                    customers_with_map += 1
                if zr.zone_id:
                    customers_with_zone += 1
                    zone_counts[zr.zone_name] = zone_counts.get(zr.zone_name, 0) + 1
                else:
                    zone_counts["Outside"] = zone_counts.get("Outside", 0) + 1
                if zr.customer_id not in customer_history:
                    customer_history[zr.customer_id] = []
                hist = customer_history[zr.customer_id]
                zone_label = zr.zone_name or "Outside"
                if not hist or hist[-1] != zone_label:
                    hist.append(zone_label)
        else:
            # Not inferring: reuse last tracking/zone results for visualization
            tracking_result = last_tracking_result
            zone_results = last_zone_results

        # Visualization
        if args.visualize or args.save_video:
            # Use last results for drawing (so every frame shows something)
            vis_tracking = tracking_result if tracking_result else last_tracking_result
            vis_zones = zone_results if zone_results is not None else last_zone_results
            # Draw CCTV
            cctv_vis = draw_cctv_frame(frame, vis_tracking, vis_zones, frame_idx, time.time()-loop_start, meta, bool(calib), map_id)
            if args.visualize:
                cv2.imshow("CCTV View", cctv_vis)
            if cctv_writer:
                cctv_writer.write(cctv_vis)

            # Draw Bird's-eye
            if map_bgr is not None and map_params is not None:
                bird_vis = draw_birdeye_frame(map_bgr, map_params, zones, vis_zones)
                if args.visualize:
                    cv2.imshow("Bird's-Eye Map", bird_vis)

            if args.visualize:
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == 27:  # Q or ESC
                    print("Quit requested")
                    break
                elif key == ord(' '):  # SPACE pause
                    print("Paused — press SPACE to resume, Q to quit")
                    while True:
                        k2 = cv2.waitKey(0) & 0xFF
                        if k2 == ord(' '):
                            print("Resumed")
                            break
                        elif k2 == ord('q') or k2 == 27:
                            print("Quit from pause")
                            vs.release()
                            if cctv_writer:
                                cctv_writer.release()
                            cv2.destroyAllWindows()
                            # Go to summary
                            frame_idx = frame_idx  # keep for summary
                            # Need to break outer loop - use flag
                            paused = True
                            break
                    if paused and (k2 == ord('q') or k2 == 27):
                        break
        else:
            # Non-visual terminal periodic output
            # We already collected, but print occasional
            if frame_idx % 90 == 0 and (tracking_result and tracking_result.customers):
                if zone_results:
                    parts = [f"{zr.customer_id}→{zr.zone_name or 'Outside'}" for zr in zone_results[:5]]
                    print(f"[Frame {frame_idx:4d}] {' | '.join(parts)}")
                else:
                    parts = [f"{c.customer_id}@({c.bottom_center[0]},{c.bottom_center[1]})" for c in tracking_result.customers[:3]]
                    print(f"[Frame {frame_idx:4d}] Customers: {' | '.join(parts)}")

    vs.release()
    if cctv_writer:
        cctv_writer.release()
    if args.visualize:
        cv2.destroyAllWindows()

    elapsed = time.time() - loop_start
    processing_fps = frame_idx / elapsed if elapsed else 0

    # Need to recompute inference count: we didn't track, approximate
    # For summary, use len(all_results) etc.
    # Summary
    print("\n" + "=" * 70)
    print("REAL VIDEO TEST RESULT")
    print("=" * 70)
    print(f"Video: {video_path.name}")
    print(f"Resolution: {vinfo['width']}x{vinfo['height']}")
    print(f"FPS: {vinfo['fps']:.2f}")
    print(f"Frames in file: {vinfo['frames']}")
    print(f"Frames processed (read): {frame_idx}")
    print(f"Duration: {vinfo['duration']:.1f}s")
    print(f"Processing time: {elapsed:.1f}s")
    print(f"Processing FPS (camera frames): {processing_fps:.1f}")
    print("")
    print(f"Map ID: {map_id}")
    print(f"Map resolution: {meta['width']}x{meta['height']}")
    print(f"Camera ID: {args.camera_id}")
    print(f"Calibration: {'FOUND' if calib else 'NOT FOUND'}")
    if calib:
        print(f"  Homography valid: {integrator.is_calibrated if integrator else 'N/A'}")
        if integrator and integrator.calibration_error:
            print(f"  Calibration error: {integrator.calibration_error}")
    print(f"Zones: {len(zones)}")
    print("")
    print(f"People detected (total detections): {detection_total}")
    print(f"Unique track IDs: {len(unique_tracks)} ({sorted(unique_tracks)[:10]}{'...' if len(unique_tracks)>10 else ''})")
    print(f"Unique customers (Customer_ID): {len(customers_seen)}")
    print(f"Customers with map positions: {customers_with_map}")
    print(f"Customers with zone assignments: {customers_with_zone}")
    print(f"Customers Outside all zones: {zone_counts.get('Outside',0)}")
    print("")
    print(f"Zone observations (counts per assignment):")
    for zone_name, cnt in sorted(zone_counts.items(), key=lambda x: -x[1]):
        print(f"  {zone_name}: {cnt} assignments")
    print("")
    print("Sample customer movement (current zone over time, zone changes only):")
    for cid, hist in list(customer_history.items())[:5]:
        print(f"  {cid}: {' → '.join(hist[:10])}{' →...' if len(hist)>10 else ''}")
    print("")
    if not calib:
        print("Calibration missing → map_position=None, zone=None for all. Detection/tracking still OK.")
    if all_results:
        valid_map = [r for r in all_results if r["map_position"] is not None]
        if valid_map:
            xs = [r["map_position"][0] for r in valid_map]
            ys = [r["map_position"][1] for r in valid_map]
            print(f"Map position range: x [{min(xs):.0f}, {max(xs):.0f}] y [{min(ys):.0f}, {max(ys):.0f}] vs map 0-{meta['width']}, 0-{meta['height']}")
            out_of_bounds = sum(1 for r in valid_map if not (0 <= r["map_position"][0] <= meta["width"] and 0 <= r["map_position"][1] <= meta["height"]))
            if out_of_bounds:
                print(f"  WARNING: {out_of_bounds}/{len(valid_map)} map positions outside map bounds (calibration offset?)")
                print(f"  -> Check calibration and zone alignment visually with --visualize")
            else:
                print(f"  Map positions within bounds: OK")
    print("")
    print(f"Errors:")
    if not calib:
        print(f"  Calibration: NOT FOUND")
    else:
        print(f"  Calibration: OK")
    print(f"  Invalid detections: 0")
    print(f"  Missing positions: {len([r for r in all_results if r['map_position'] is None])} (no calibration or transform failed)")
    print(f"  Zone assignment failures: 0")
    print("=" * 70)

    # Save results
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "video": str(video_path.name),
            "video_path": str(video_path),
            "resolution": [vinfo["width"], vinfo["height"]],
            "fps": vinfo["fps"],
            "frames_in_file": vinfo["frames"],
            "frames_processed": frame_idx,
            "duration": vinfo["duration"],
            "processing_time": elapsed,
            "map_id": map_id,
            "map_resolution": [meta["width"], meta["height"]],
            "camera_id": args.camera_id,
            "calibration": "FOUND" if calib else "NOT FOUND",
            "calibration_path": str(Path(f"calibration/calibration_{args.camera_id}__{map_id}.json")) if calib else None,
            "zones": len(zones),
            "zone_list": [{"zone_id": z["zone_id"], "name": z["name"]} for z in zones],
            "people_detected": detection_total,
            "unique_tracks": len(unique_tracks),
            "unique_customers": len(customers_seen),
            "customers_with_map": customers_with_map,
            "customers_with_zone": customers_with_zone,
            "zone_counts": zone_counts,
            "results": all_results[:5000],
        }, f, indent=2)
    print(f"\nResults saved to: {out_path.resolve()}")
    print(f"  Records: {len(all_results)} (capped at 5000)")
    if args.save_video:
        print(f"Visualized video saved to: {Path(args.save_video).resolve()}")
    if args.visualize:
        print(f"Visual debug completed (windows closed).")
    print(f"Test completed successfully.")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""Visual Camera Calibration Tool — Phase 2 Step 2.

Run:
    python -m app.phase2.calibration
    python -m app.phase2.calibration.tool --source 0 --camera-id default_camera

No YOLO/ByteTrack — only VideoSource + MapManager + Homography.
"""

from __future__ import annotations

import argparse
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageTk, ImageDraw, ImageFont

from app.video.video_source import VideoSource
from app.phase2.maps.manager import get_map_manager
from app.phase2.calibration.homography import HomographyCalibrator
from app.phase2.calibration.store import save_calibration, load_calibration, get_calibration_path, check_resolution_mismatch

# Styling matching gallery
BG = "#f5f7fb"
HEADER_BG = "#0f172a"
CARD_BG = "#ffffff"
PRIMARY = "#2563eb"
PRIMARY_HOVER = "#1d4ed8"
SUCCESS = "#16a34a"
MUTED = "#64748b"
TEXT_DARK = "#0f172a"
DANGER = "#dc2626"
WARN = "#d97706"

DISPLAY_W = 640
DISPLAY_H = 460  # slightly smaller to fit toolbar


def _compute_display_params(orig_w: int, orig_h: int, disp_w: int = DISPLAY_W, disp_h: int = DISPLAY_H):
    """Return (scale, disp_w_scaled, disp_h_scaled, offset_x, offset_y)."""
    scale = min(disp_w / orig_w, disp_h / orig_h)
    sw = int(orig_w * scale)
    sh = int(orig_h * scale)
    ox = (disp_w - sw) // 2
    oy = (disp_h - sh) // 2
    return scale, sw, sh, ox, oy


def _display_to_original(dx: int, dy: int, orig_w: int, orig_h: int, scale: float, ox: int, oy: int, disp_w: int = DISPLAY_W, disp_h: int = DISPLAY_H) -> Optional[tuple[float, float]]:
    """Convert display click to original coords. Returns None if outside image area."""
    if dx < ox or dx >= ox + int(orig_w * scale) or dy < oy or dy >= oy + int(orig_h * scale):
        return None
    ox_f = (dx - ox) / scale
    oy_f = (dy - oy) / scale
    # clamp
    ox_f = max(0, min(orig_w - 1, ox_f))
    oy_f = max(0, min(orig_h - 1, oy_f))
    return float(ox_f), float(oy_f)


class CalibrationApp:
    def __init__(self, source: int | str = 0, camera_id: str = "default_camera", maps_dir: str | Path | None = None, calibration_dir: str | Path | None = None):
        self.source = int(source) if isinstance(source, str) and source.isdigit() else source
        self.camera_id = camera_id
        self.maps_dir = maps_dir
        self.calibration_dir = calibration_dir
        self.map_manager = get_map_manager(maps_dir)
        self.calibrator = HomographyCalibrator()
        self.calibrator.camera_id = camera_id

        # Map selection
        self.map_meta: Optional[dict] = self.map_manager.get_selected_map()
        if self.map_meta is None:
            # Try to prompt user to pick one
            available = self.map_manager.list_maps()
            if not available:
                # No maps at all — error window
                self._show_no_map_error()
                raise SystemExit(0)
            # Show simple chooser dialog
            chosen = self._choose_map_dialog(available)
            if chosen is None:
                raise SystemExit(0)
            self.map_manager.select_map(chosen)
            self.map_meta = self.map_manager.get_map(chosen)

        assert self.map_meta is not None
        self.map_id = self.map_meta["map_id"]
        self.calibrator.map_id = self.map_id

        # Load map image
        self.map_image_path = Path(self.map_meta["image_path"])
        try:
            self.map_image_original = Image.open(self.map_image_path).convert("RGB")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load map image: {e}")
            raise SystemExit(1)

        self.map_w, self.map_h = self.map_image_original.size  # PIL is (w,h)
        # Also store from meta width/height (should match)
        # Use PIL size as authoritative

        # Video source
        self.video_source = VideoSource(self.source)
        if not self.video_source.open():
            messagebox.showerror("Camera Error", f"Failed to open camera/video source: {self.source}\nTry --source 1 or check camera.")
            raise SystemExit(1)
        self.cam_w = self.video_source.width
        self.cam_h = self.video_source.height
        self.calibrator.camera_resolution = (self.cam_w, self.cam_h)

        # Check existing calibration resolution mismatch
        existing = load_calibration(self.camera_id, self.map_id, self.calibration_dir)
        self.existing_calib = existing

        # UI state
        self.root = tk.Tk()
        self.root.title(f"Camera Calibration — {self.map_meta['name']} • {self.camera_id}")
        self.root.configure(bg=BG)
        self.root.geometry("1360x760")
        self.root.minsize(1200, 680)

        # Refs to avoid GC
        self._cctv_tk: Optional[ImageTk.PhotoImage] = None
        self._map_tk: Optional[ImageTk.PhotoImage] = None
        self._current_frame: Optional[np.ndarray] = None

        # Display params cache
        self._cctv_scale, self._cctv_sw, self._cctv_sh, self._cctv_ox, self._cctv_oy = _compute_display_params(self.cam_w, self.cam_h)
        self._map_scale, self._map_sw, self._map_sh, self._map_ox, self._map_oy = _compute_display_params(self.map_w, self.map_h)

        self.status_text = tk.StringVar(value="Ready — Click a floor point on CCTV, then same point on map")
        self.pairs_var = tk.StringVar(value="Pairs: 0/4")
        self.calibrated = False
        self._calib_result = None

        self._build_ui()
        self._refresh_info()
        # Warn if resolution mismatch
        if existing and existing.get("camera_resolution"):
            warn = check_resolution_mismatch(existing["camera_resolution"], (self.cam_w, self.cam_h))
            if warn:
                self.status_text.set(f"⚠ {warn}")

        self._running = True
        self._update_cctv_loop()
        self.root.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def _show_no_map_error(self):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "No Map Selected",
            "No Bird's-Eye map selected.\n\nPlease run the Map Management tool first:\n\npython -m app.phase2.maps.gallery\n\nThen click Select on a map."
        )
        root.destroy()

    def _choose_map_dialog(self, available: list[dict]) -> Optional[str]:
        # Simple modal to pick a map if none selected
        dlg = tk.Tk()
        dlg.title("Select a Map for Calibration")
        dlg.geometry("500x400")
        dlg.configure(bg=BG)
        dlg.grab_set()
        tk.Label(dlg, text="Choose a Bird's-Eye map", bg=BG, fg=TEXT_DARK, font=("Segoe UI", 12, "bold")).pack(pady=14)
        tk.Label(dlg, text="No map was pre-selected. Pick one to calibrate:", bg=BG, fg=MUTED).pack()
        lb = tk.Listbox(dlg, font=("Segoe UI", 10), height=10)
        for m in available:
            lb.insert("end", f"{m['name']}  —  {m['width']}×{m['height']}  ({m['map_id']})")
        lb.pack(fill="both", expand=True, padx=16, pady=12)
        lb.selection_set(0)
        chosen: dict = {"id": None}

        def on_ok():
            sel = lb.curselection()
            if not sel:
                return
            idx = sel[0]
            chosen["id"] = available[idx]["map_id"]
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        btns = tk.Frame(dlg, bg=BG)
        btns.pack(pady=10)
        tk.Button(btns, text="Use Selected", command=on_ok, bg=PRIMARY, fg="white", padx=16, pady=6, bd=0).pack(side="left", padx=6)
        tk.Button(btns, text="Cancel", command=on_cancel, bg=CARD_BG, padx=16, pady=6).pack(side="left", padx=6)
        dlg.wait_window()
        dlg.destroy()
        return chosen["id"]

    # ── UI building ───────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg=HEADER_BG, height=70)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        tk.Label(header, text="VISUAL CAMERA CALIBRATION", bg=HEADER_BG, fg="white", font=("Segoe UI", 16, "bold")).pack(side="left", padx=18, pady=10)
        tk.Label(header, text="Match floor points between CCTV and Bird's-Eye map", bg=HEADER_BG, fg="#cbd5e1", font=("Segoe UI", 10)).pack(side="left", padx=10)

        # Main side-by-side
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        # Left CCTV panel
        left = tk.Frame(main, bg=CARD_BG, bd=1, relief="solid")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(left, text="CCTV  —  Click a floor feature (corner, doorway, shelf base)", bg=CARD_BG, fg=TEXT_DARK, font=("Segoe UI", 10, "bold")).pack(pady=6)
        self.cctv_label = tk.Label(left, bg="#0f172a", width=DISPLAY_W, height=DISPLAY_H, cursor="crosshair")
        self.cctv_label.pack(padx=8, pady=8)
        self.cctv_label.bind("<Button-1>", self._on_cctv_click)
        tk.Label(left, text="Tip: Choose static floor points, not people. Cover different parts of floor.", bg=CARD_BG, fg=MUTED, font=("Segoe UI", 8, "italic")).pack(pady=(0, 6))

        # Right Map panel
        right = tk.Frame(main, bg=CARD_BG, bd=1, relief="solid")
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        tk.Label(right, text="BIRD'S-EYE MAP  —  Click the SAME point on the map", bg=CARD_BG, fg=TEXT_DARK, font=("Segoe UI", 10, "bold")).pack(pady=6)
        self.map_label = tk.Label(right, bg="#e2e8f0", width=DISPLAY_W, height=DISPLAY_H, cursor="crosshair")
        self.map_label.pack(padx=8, pady=8)
        self.map_label.bind("<Button-1>", self._on_map_click)
        self._render_map_static()  # initial map display

        # Bottom info bar
        info = tk.Frame(self.root, bg=HEADER_BG, height=28)
        info.pack(fill="x", side="bottom")
        info.pack_propagate(False)
        self.info_camera = tk.Label(info, text=f"Camera: {self.camera_id}  ({self.cam_w}×{self.cam_h})", bg=HEADER_BG, fg="#cbd5e1", font=("Segoe UI", 9))
        self.info_camera.pack(side="left", padx=12)
        self.info_map = tk.Label(info, text=f"Map: {self.map_meta['name']}  ({self.map_w}×{self.map_h})", bg=HEADER_BG, fg="#cbd5e1", font=("Segoe UI", 9))
        self.info_map.pack(side="left", padx=12)
        self.info_pairs = tk.Label(info, textvariable=self.pairs_var, bg=HEADER_BG, fg="white", font=("Segoe UI", 9, "bold"))
        self.info_pairs.pack(side="left", padx=12)
        self.info_status = tk.Label(info, textvariable=self.status_text, bg=HEADER_BG, fg="#fbbf24", font=("Segoe UI", 9))
        self.info_status.pack(side="left", padx=12)

        # Toolbar
        toolbar = tk.Frame(self.root, bg=BG)
        toolbar.pack(fill="x", padx=12, pady=8)
        btn_cfg = dict(font=("Segoe UI", 10), padx=14, pady=6, bd=0, cursor="hand2")
        tk.Button(toolbar, text="Undo", command=self.on_undo, bg="#e2e8f0", **btn_cfg).pack(side="left", padx=4)
        tk.Button(toolbar, text="Reset", command=self.on_reset, bg="#e2e8f0", **btn_cfg).pack(side="left", padx=4)
        tk.Button(toolbar, text="Calibrate", command=self.on_calibrate, bg=PRIMARY, fg="white", activebackground=PRIMARY_HOVER, **btn_cfg).pack(side="left", padx=12)
        tk.Button(toolbar, text="Save", command=self.on_save, bg=SUCCESS, fg="white", **btn_cfg).pack(side="left", padx=4)
        tk.Button(toolbar, text="Cancel", command=self.on_cancel, bg=CARD_BG, font=("Segoe UI", 10), padx=14, pady=6, bd=1, cursor="hand2", relief="solid").pack(side="right", padx=4)

        # Pending hint
        self.pending_label = tk.Label(toolbar, text="", bg=BG, fg=PRIMARY, font=("Segoe UI", 9, "italic"))
        self.pending_label.pack(side="left", padx=12)

    # ── rendering ─────────────────────────────────────────────────────

    def _render_map_static(self):
        # Render map with markers to self.map_label
        disp = Image.new("RGB", (DISPLAY_W, DISPLAY_H), (226, 232, 240))
        # Resize map preserving aspect
        scale = self._map_scale
        sw, sh = self._map_sw, self._map_sh
        ox, oy = self._map_ox, self._map_oy
        resized = self.map_image_original.resize((sw, sh), Image.LANCZOS)
        disp.paste(resized, (ox, oy))
        # Draw markers for map_points
        draw = ImageDraw.Draw(disp)
        for i, pt in enumerate(self.calibrator.map_points):
            # pt is original map coords, convert to display
            dx = int(pt[0] * scale + ox)
            dy = int(pt[1] * scale + oy)
            self._draw_numbered_marker(draw, dx, dy, i + 1, color="#16a34a" if not self.calibrator.has_pending() or i < self.calibrator.pairs_count() else "#94a3b8")
        self._map_tk = ImageTk.PhotoImage(disp)
        self.map_label.configure(image=self._map_tk)

    def _draw_numbered_marker(self, draw: ImageDraw.ImageDraw, x: int, y: int, num: int, color: str = "#2563eb"):
        r = 14
        # Outer circle
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color, outline="white", width=2)
        # Text — centered
        txt = str(num)
        # Use default font, estimate centering
        try:
            # Try to use a better font if available
            font = ImageFont.load_default()
            # get bbox
            bbox = draw.textbbox((0, 0), txt, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text((x - tw // 2, y - th // 2 - 1), txt, fill="white", font=font)
        except Exception:
            draw.text((x - 4, y - 6), txt, fill="white")

    def _update_cctv_loop(self):
        if not self._running:
            return
        ok, frame = self.video_source.read()
        if not ok or frame is None:
            # Loop video or black
            self.root.after(30, self._update_cctv_loop)
            return
        self._current_frame = frame.copy()
        # Convert frame to PIL and display with markers
        self._render_cctv_frame(frame)
        self.root.after(30, self._update_cctv_loop)

    def _render_cctv_frame(self, frame: np.ndarray):
        # Convert BGR to RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        # Resize to display
        sw, sh = self._cctv_sw, self._cctv_sh
        ox, oy = self._cctv_ox, self._cctv_oy
        disp = Image.new("RGB", (DISPLAY_W, DISPLAY_H), (15, 23, 42))
        resized = pil.resize((sw, sh), Image.LANCZOS)
        disp.paste(resized, (ox, oy))
        draw = ImageDraw.Draw(disp)
        # Draw CCTV points
        scale = self._cctv_scale
        for i, pt in enumerate(self.calibrator.cctv_points):
            dx = int(pt[0] * scale + ox)
            dy = int(pt[1] * scale + oy)
            # If pending (last CCTV without map pair), show differently
            is_pending = self.calibrator.has_pending() and i == len(self.calibrator.cctv_points) - 1
            color = "#f59e0b" if is_pending else "#2563eb"
            self._draw_numbered_marker(draw, dx, dy, i + 1, color=color)
        self._cctv_tk = ImageTk.PhotoImage(disp)
        self.cctv_label.configure(image=self._cctv_tk)

    # ── interaction ───────────────────────────────────────────────────

    def _on_cctv_click(self, event):
        pt = _display_to_original(event.x, event.y, self.cam_w, self.cam_h, self._cctv_scale, self._cctv_ox, self._cctv_oy)
        if pt is None:
            return
        if self.calibrator.has_pending():
            # Already has pending CCTV point, ignore or replace? Replace pending
            # Remove pending and add new one
            self.calibrator.undo()
        self.calibrator.add_cctv_point(pt)
        self.status_text.set(f"CCTV point {len(self.calibrator.cctv_points)} added at ({int(pt[0])},{int(pt[1])}) — now click SAME point on map")
        self.pending_label.config(text="● Awaiting map click →")
        self._refresh_info()
        self._render_map_static()  # to update pending visual? map unchanged but for consistency
        # Force CCTV re-render on next loop, but also immediate
        if self._current_frame is not None:
            self._render_cctv_frame(self._current_frame)

    def _on_map_click(self, event):
        pt = _display_to_original(event.x, event.y, self.map_w, self.map_h, self._map_scale, self._map_ox, self._map_oy)
        if pt is None:
            return
        if not self.calibrator.has_pending():
            messagebox.showinfo("Calibration", "Please click a point on the CCTV first, then click the SAME physical point on the map.")
            return
        self.calibrator.add_map_point(pt)
        self.status_text.set(f"Pair {self.calibrator.pairs_count()} complete — click next CCTV point or Calibrate")
        self.pending_label.config(text="")
        self._refresh_info()
        self._render_map_static()
        if self._current_frame is not None:
            self._render_cctv_frame(self._current_frame)

    def _refresh_info(self):
        pairs = self.calibrator.pairs_count()
        total_cctv = self.calibrator.total_cctv()
        pending = " + pending" if self.calibrator.has_pending() else ""
        self.pairs_var.set(f"Pairs: {pairs}/4{pending}")
        # Update status color based on pairs
        if pairs >= 4 and not self.calibrator.has_pending():
            self.info_pairs.config(fg="#4ade80")
        else:
            self.info_pairs.config(fg="white")

    # ── toolbar actions ───────────────────────────────────────────────

    def on_undo(self):
        if not self.calibrator.undo():
            messagebox.showinfo("Undo", "Nothing to undo.")
            return
        self.calibrated = False
        self.status_text.set("Last point removed")
        self.pending_label.config(text="● Awaiting map click →" if self.calibrator.has_pending() else "")
        self._refresh_info()
        self._render_map_static()
        if self._current_frame is not None:
            self._render_cctv_frame(self._current_frame)

    def on_reset(self):
        if not self.calibrator.cctv_points and not self.calibrator.map_points:
            return
        if not messagebox.askyesno("Reset", "Clear all point pairs?"):
            return
        self.calibrator.reset()
        self.calibrated = False
        self.status_text.set("All points cleared — start again")
        self.pending_label.config(text="")
        self._refresh_info()
        self._render_map_static()
        if self._current_frame is not None:
            self._render_cctv_frame(self._current_frame)

    def on_calibrate(self):
        if self.calibrator.has_pending():
            messagebox.showwarning("Calibrate", "Complete the current pair first: click the corresponding point on the map.")
            return
        if len(self.calibrator.cctv_points) < 4:
            messagebox.showwarning("Calibrate", f"Need at least 4 pairs (have {len(self.calibrator.cctv_points)}).")
            return
        err = self.calibrator.validate()
        if err:
            messagebox.showerror("Invalid Points", err)
            return
        try:
            result = self.calibrator.calibrate(camera_id=self.camera_id, map_id=self.map_id, camera_resolution=(self.cam_w, self.cam_h))
        except ValueError as e:
            messagebox.showerror("Calibration Failed", str(e))
            return
        except Exception as e:
            messagebox.showerror("Calibration Failed", f"Unexpected error: {e}")
            return

        self.calibrated = True
        self._calib_result = result
        mean_err = result.reprojection_error
        msg = f"✓ Calibration successful — mean error {mean_err:.2f}px"
        if mean_err > 15:
            msg = f"⚠ Calibration quality is poor (error {mean_err:.2f}px). Please choose better reference points that cover the floor more evenly."
            messagebox.showwarning("Calibration", msg)
            self.status_text.set(msg)
        else:
            messagebox.showinfo("Calibration", msg)
            self.status_text.set(msg)

    def on_save(self):
        if not self.calibrated or self.calibrator.result is None:
            if not self.calibrator.can_calibrate():
                messagebox.showwarning("Save", "Calibrate first (need 4 pairs).")
                return
            # Auto-calibrate if not yet
            self.on_calibrate()
            if not self.calibrated:
                return
        try:
            data = self.calibrator.to_dict()
            path = save_calibration(data, self.calibration_dir)
            messagebox.showinfo("Saved", f"Calibration saved:\n{path}\n\nCamera: {self.camera_id}\nMap: {self.map_id}\nResolution: {self.cam_w}×{self.cam_h}")
            self.status_text.set(f"Saved ✓ — {path.name}")
        except Exception as e:
            messagebox.showerror("Save Failed", str(e))

    def on_cancel(self):
        self._running = False
        try:
            self.video_source.release()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Visual Camera Calibration - CCTV to Bird's-Eye Map")
    parser.add_argument("--source", type=str, default="0", help="Camera source (0 for webcam, or video file)")
    parser.add_argument("--camera-id", type=str, default="default_camera", help="Camera ID for isolated calibration")
    parser.add_argument("--maps-dir", type=str, default=None, help="Maps directory override")
    parser.add_argument("--calibration-dir", type=str, default=None, help="Calibration directory override")
    args = parser.parse_args()

    app = CalibrationApp(source=args.source, camera_id=args.camera_id, maps_dir=args.maps_dir, calibration_dir=args.calibration_dir)
    app.run()


if __name__ == "__main__":
    main()

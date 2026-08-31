"""Visual Zone Editor — Phase 2 Step 3.

Run:
    python -m app.phase2.zones
    python -m app.phase2.zones.editor

Draw zones by LEFT CLICK + DRAG on Bird's-Eye map. No coordinate typing.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog
from pathlib import Path
from typing import Optional

from PIL import Image, ImageTk

from app.phase2.maps.manager import get_map_manager
from app.phase2.zones.manager import get_zone_manager

# Styling
BG = "#f5f7fb"
HEADER_BG = "#0f172a"
CARD_BG = "#ffffff"
PRIMARY = "#2563eb"
PRIMARY_HOVER = "#1d4ed8"
SUCCESS = "#16a34a"
MUTED = "#64748b"
TEXT_DARK = "#0f172a"
DANGER = "#dc2626"

CANVAS_W = 980
CANVAS_H = 620

# Zone colors
ZONE_FILL = "#3b82f6"  # blue, will use stipple
ZONE_OUTLINE = "#2563eb"
ZONE_FILL_SELECTED = "#22c55e"
ZONE_OUTLINE_SELECTED = "#16a34a"
HANDLE_SIZE = 8  # display px
MIN_DRAG_DISPLAY = 5  # min drag in display px to consider valid
MIN_ZONE_ORIGINAL = 5  # min size in original px


def _compute_display_params(orig_w: int, orig_h: int, disp_w: int = CANVAS_W, disp_h: int = CANVAS_H):
    scale = min(disp_w / orig_w, disp_h / orig_h, 1.0)  # never upscale beyond original? allow but keep 1.0 max to preserve quality? spec says preserve aspect, but if map smaller than canvas we could center without upscale. Use min to fit.
    # Actually allow upscale a bit if map is tiny, but cap at 1.5 maybe. Simpler: allow scale >1 as well to fill canvas.
    # Recompute without cap: we want to display FULL image filling canvas as much as possible
    scale = min(disp_w / orig_w, disp_h / orig_h)
    sw = int(orig_w * scale)
    sh = int(orig_h * scale)
    ox = (disp_w - sw) // 2
    oy = (disp_h - sh) // 2
    return scale, sw, sh, ox, oy


class ZoneEditorApp:
    def __init__(self, maps_dir: str | Path | None = None, zones_dir: str | Path | None = None):
        self.maps_dir = maps_dir
        self.zones_dir = zones_dir
        self.map_manager = get_map_manager(maps_dir)
        self.zone_manager = get_zone_manager(zones_dir, maps_dir)

        self.map_meta = self.map_manager.get_selected_map()
        if self.map_meta is None:
            self._show_no_map_error()
            raise SystemExit(0)

        self.map_id = self.map_meta["map_id"]
        self.map_name = self.map_meta["name"]
        self.map_image_path = Path(self.map_meta["image_path"])
        try:
            self.map_image_original = Image.open(self.map_image_path).convert("RGB")
        except Exception as e:
            # Fallback: show error and exit
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Error", f"Failed to load map image: {e}")
            root.destroy()
            raise SystemExit(1)

        self.map_w, self.map_h = self.map_image_original.size
        # Use meta width/height but PIL size is authoritative; ensure consistency
        self.zones: list[dict] = self.zone_manager.get_zones(self.map_id)
        self.selected_id: Optional[str] = None

        # --- DEBUG LOGGING FOR BUG INVESTIGATION ---
        try:
            zone_file = self.zone_manager.zones_dir / f"{self.map_id}.json"
            import json as _json
            file_exists = zone_file.exists()
            file_zone_count = 0
            if file_exists:
                try:
                    file_zone_count = len(_json.loads(zone_file.read_text(encoding="utf-8")).get("zones", []))
                except Exception:
                    file_zone_count = -1
            print(f"[ZONE DEBUG] EDITOR INIT\nmap_id={self.map_id}\nzone_file={zone_file.resolve()}\nfile_exists={file_exists}\nfile_zone_count={file_zone_count}\nloaded_zone_count={len(self.zones)}\nloaded_zone_ids={[z.get('zone_id') for z in self.zones]}")
        except Exception as _e:
            print(f"[ZONE DEBUG] EDITOR INIT logging failed: {_e}")

        # Drag state
        self._drag_start: Optional[tuple[int, int]] = None
        self._drag_current: Optional[tuple[int, int]] = None
        self._drag_mode: Optional[str] = None  # "create", "move", "resize"
        self._resize_corner: Optional[str] = None  # "tl", "tr", "br", "bl"
        self._move_offset: Optional[tuple[float, float]] = None  # original offset
        self._preview_rect: Optional[int] = None

        # Tk
        self.root = tk.Tk()
        self.root.title(f"Zone Editor — {self.map_name}")
        self.root.configure(bg=BG)
        self.root.geometry("1100x780")
        self.root.minsize(900, 650)

        # Display params
        self.scale, self.sw, self.sh, self.ox, self.oy = _compute_display_params(self.map_w, self.map_h)

        # Image refs
        self._bg_tk: Optional[ImageTk.PhotoImage] = None

        self._build_ui()
        self._render()

        self.root.protocol("WM_DELETE_WINDOW", self.on_cancel)

    def _show_no_map_error(self):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("No Map Selected", "No Bird's-Eye map selected.\n\nPlease run the Map Management tool first:\n\npython -m app.phase2.maps.gallery\n\nThen click Select on a map.")
        root.destroy()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg=HEADER_BG, height=70)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        tk.Label(header, text="ZONE EDITOR", bg=HEADER_BG, fg="white", font=("Segoe UI", 16, "bold")).pack(side="left", padx=18, pady=10)
        tk.Label(header, text=self.map_name, bg=HEADER_BG, fg="#cbd5e1", font=("Segoe UI", 11)).pack(side="left", padx=10)
        tk.Label(header, text=f"{self.map_w} × {self.map_h}", bg=HEADER_BG, fg="#94a3b8", font=("Segoe UI", 9)).pack(side="left", padx=6)

        # Canvas container
        container = tk.Frame(self.root, bg="#e2e8f0", bd=0)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        self.canvas = tk.Canvas(container, width=CANVAS_W, height=CANVAS_H, bg="#f8fafc", highlightthickness=1, highlightbackground="#cbd5e1", cursor="crosshair")
        self.canvas.pack(expand=True)

        # Bindings
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)

        # Instructions
        tk.Label(self.root, text="Left click + drag to create rectangle  •  Click zone to select  •  Drag inside selected zone to move  •  Drag corner handle to resize", bg=BG, fg=MUTED, font=("Segoe UI", 9, "italic")).pack(pady=(0, 4))

        # Info bar
        info = tk.Frame(self.root, bg=HEADER_BG, height=24)
        info.pack(fill="x", side="bottom")
        info.pack_propagate(False)
        self.info_zones = tk.Label(info, text=f"Zones: {len(self.zones)}", bg=HEADER_BG, fg="white", font=("Segoe UI", 9, "bold"))
        self.info_zones.pack(side="left", padx=12)
        self.info_selected = tk.Label(info, text="No zone selected", bg=HEADER_BG, fg="#cbd5e1", font=("Segoe UI", 9))
        self.info_selected.pack(side="left", padx=12)

        # Toolbar
        toolbar = tk.Frame(self.root, bg=BG)
        toolbar.pack(fill="x", padx=12, pady=8)
        btn_cfg = dict(font=("Segoe UI", 10), padx=14, pady=6, bd=0, cursor="hand2")
        # Rectangle Zone is default create mode — just an indicator, not a toggle needed
        self.rect_btn = tk.Label(toolbar, text="Rectangle Zone  ●", bg=PRIMARY, fg="white", font=("Segoe UI", 10, "bold"), padx=14, pady=6)
        self.rect_btn.pack(side="left", padx=4)

        tk.Button(toolbar, text="Rename", command=self.on_rename, bg="#e2e8f0", **btn_cfg).pack(side="left", padx=4)
        tk.Button(toolbar, text="Delete Zone", command=self.on_delete, bg="#fee2e2", fg=DANGER, **btn_cfg).pack(side="left", padx=4)
        tk.Button(toolbar, text="Save Zones", command=self.on_save, bg=SUCCESS, fg="white", **btn_cfg).pack(side="left", padx=12)
        tk.Button(toolbar, text="Cancel", command=self.on_cancel, bg=CARD_BG, font=("Segoe UI", 10), padx=14, pady=6, bd=1, cursor="hand2", relief="solid").pack(side="right", padx=4)

        # Keyboard Delete support (Delete / BackSpace) when a zone is selected
        self.root.bind("<Delete>", lambda e: self.on_delete())
        self.root.bind("<BackSpace>", lambda e: self.on_delete())
        # Ensure canvas can receive focus for key events
        self.canvas.focus_set()
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set(), add="+")

    # ── helpers ─────────────────────────────────────────────────────────

    def _display_to_original(self, dx: int, dy: int) -> Optional[tuple[float, float]]:
        if dx < self.ox or dx >= self.ox + self.sw or dy < self.oy or dy >= self.oy + self.sh:
            return None
        ox = (dx - self.ox) / self.scale
        oy = (dy - self.oy) / self.scale
        ox = max(0, min(self.map_w, ox))
        oy = max(0, min(self.map_h, oy))
        return float(ox), float(oy)

    def _original_to_display(self, ox: float, oy: float) -> tuple[int, int]:
        return int(ox * self.scale + self.ox), int(oy * self.scale + self.oy)

    def _get_selected_zone(self) -> Optional[dict]:
        if not self.selected_id:
            return None
        for z in self.zones:
            if z["zone_id"] == self.selected_id:
                return z
        return None

    def _hit_test(self, dx: int, dy: int) -> Optional[dict]:
        """Return zone hit at display coords, or None. Checks top-most first (last drawn)."""
        for z in reversed(self.zones):
            x1, y1, x2, y2 = self._zone_bbox_display(z)
            if x1 <= dx <= x2 and y1 <= dy <= y2:
                return z
        return None

    def _zone_bbox_display(self, zone: dict) -> tuple[int, int, int, int]:
        xs = [p[0] for p in zone["points"]]
        ys = [p[1] for p in zone["points"]]
        x1o, y1o = min(xs), min(ys)
        x2o, y2o = max(xs), max(ys)
        x1d, y1d = self._original_to_display(x1o, y1o)
        x2d, y2d = self._original_to_display(x2o, y2o)
        return x1d, y1d, x2d, y2d

    def _corner_hit(self, dx: int, dy: int, zone: dict) -> Optional[str]:
        """If near a corner of zone, return corner id."""
        x1, y1, x2, y2 = self._zone_bbox_display(zone)
        corners = {"tl": (x1, y1), "tr": (x2, y1), "br": (x2, y2), "bl": (x1, y2)}
        for cid, (cx, cy) in corners.items():
            if abs(dx - cx) <= 10 and abs(dy - cy) <= 10:
                return cid
        return None

    # ── rendering ───────────────────────────────────────────────────────

    def _render(self):
        self.canvas.delete("all")
        # Background image
        # Resize map to display size
        resized = self.map_image_original.resize((self.sw, self.sh), Image.LANCZOS)
        # Create display image centered
        disp_img = Image.new("RGB", (CANVAS_W, CANVAS_H), "#f8fafc")
        disp_img.paste(resized, (self.ox, self.oy))
        self._bg_tk = ImageTk.PhotoImage(disp_img)
        self.canvas.create_image(0, 0, anchor="nw", image=self._bg_tk)

        # Draw zones
        for z in self.zones:
            self._draw_zone(z, is_selected=(z["zone_id"] == self.selected_id))

        # Draw preview rect if dragging create
        if self._drag_mode == "create" and self._drag_start and self._drag_current:
            x1, y1 = self._drag_start
            x2, y2 = self._drag_current
            # Clamp to canvas image area
            self.canvas.create_rectangle(x1, y1, x2, y2, outline=PRIMARY, width=2, dash=(4, 4), fill="", stipple="")

        self.info_zones.config(text=f"Zones: {len(self.zones)}")
        sel = self._get_selected_zone()
        if sel:
            self.info_selected.config(text=f"Selected: {sel['name']}")
        else:
            self.info_selected.config(text="No zone selected")

    def _draw_zone(self, zone: dict, is_selected: bool):
        x1, y1, x2, y2 = self._zone_bbox_display(zone)
        fill = ZONE_FILL_SELECTED if is_selected else ZONE_FILL
        outline = ZONE_OUTLINE_SELECTED if is_selected else ZONE_OUTLINE
        width = 3 if is_selected else 2
        # Semi-transparent fill via stipple
        self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, stipple="gray50", outline=outline, width=width)
        # Label at top-center with background
        cx = (x1 + x2) // 2
        ly = y1 + 14
        # Keep label inside canvas
        ly = max(14, min(CANVAS_H - 14, ly))
        # Draw label bg and text
        txt = zone["name"]
        # Use canvas text with background rectangle
        self.canvas.create_text(cx, ly, text=txt, fill="white", font=("Segoe UI", 9, "bold"), anchor="center")
        # Slight shadow for readability — add white outline via duplicate text offset? Keep simple.

        if is_selected:
            # Draw handles at corners
            for cxh, cyh in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
                self.canvas.create_rectangle(cxh - 4, cyh - 4, cxh + 4, cyh + 4, fill="white", outline=outline, width=2)

    # ── mouse events ────────────────────────────────────────────────────

    def _on_press(self, event):
        dx, dy = event.x, event.y
        # Check if click inside image area; if outside, ignore
        if self._display_to_original(dx, dy) is None:
            return

        # Check if clicking on selected zone's corner -> resize
        sel = self._get_selected_zone()
        if sel:
            corner = self._corner_hit(dx, dy, sel)
            if corner:
                self._drag_mode = "resize"
                self._resize_corner = corner
                self._drag_start = (dx, dy)
                # Store original points for reference
                xs = [p[0] for p in sel["points"]]
                ys = [p[1] for p in sel["points"]]
                self._resize_orig_bbox = (min(xs), min(ys), max(xs), max(ys))
                return
            # Check if inside selected zone -> move
            x1, y1, x2, y2 = self._zone_bbox_display(sel)
            if x1 <= dx <= x2 and y1 <= dy <= y2:
                self._drag_mode = "move"
                self._drag_start = (dx, dy)
                orig_pt = self._display_to_original(dx, dy)
                if orig_pt:
                    # Store offset from zone's top-left to click point in original coords
                    zx1 = min(p[0] for p in sel["points"])
                    zy1 = min(p[1] for p in sel["points"])
                    self._move_offset = (orig_pt[0] - zx1, orig_pt[1] - zy1)
                    self._move_orig_bbox = (zx1, zy1, max(p[0] for p in sel["points"]), max(p[1] for p in sel["points"]))
                return

        # Check if clicking inside any other zone -> select it
        hit = self._hit_test(dx, dy)
        if hit:
            self.selected_id = hit["zone_id"]
            self._render()
            return

        # Otherwise start create
        self._drag_mode = "create"
        self._drag_start = (dx, dy)
        self._drag_current = (dx, dy)
        # Clear selection to indicate new creation
        self.selected_id = None
        self._render()

    def _on_drag(self, event):
        if not self._drag_start:
            return
        dx, dy = event.x, event.y
        # Clamp to image area for display
        dx = max(self.ox, min(self.ox + self.sw, dx))
        dy = max(self.oy, min(self.oy + self.sh, dy))
        self._drag_current = (dx, dy)

        if self._drag_mode == "create":
            self._render()
        elif self._drag_mode == "move":
            sel = self._get_selected_zone()
            if not sel or not self._move_offset:
                return
            orig_pt = self._display_to_original(dx, dy)
            if not orig_pt:
                return
            # Compute new top-left in original
            new_x1 = orig_pt[0] - self._move_offset[0]
            new_y1 = orig_pt[1] - self._move_offset[1]
            x1o, y1o, x2o, y2o = self._move_orig_bbox  # type: ignore
            w = x2o - x1o
            h = y2o - y1o
            # Clamp to map bounds
            new_x1 = max(0, min(self.map_w - w, new_x1))
            new_y1 = max(0, min(self.map_h - h, new_y1))
            new_x2 = new_x1 + w
            new_y2 = new_y1 + h
            # Update zone points
            sel["points"] = [[new_x1, new_y1], [new_x2, new_y1], [new_x2, new_y2], [new_x1, new_y2]]
            self._render()
        elif self._drag_mode == "resize":
            sel = self._get_selected_zone()
            if not sel or not self._resize_corner:
                return
            orig_pt = self._display_to_original(dx, dy)
            if not orig_pt:
                return
            x1o, y1o, x2o, y2o = self._resize_orig_bbox  # type: ignore
            nx1, ny1, nx2, ny2 = x1o, y1o, x2o, y2o
            if self._resize_corner == "tl":
                nx1, ny1 = orig_pt
            elif self._resize_corner == "tr":
                nx2, ny1 = orig_pt
            elif self._resize_corner == "br":
                nx2, ny2 = orig_pt
            elif self._resize_corner == "bl":
                nx1, ny2 = orig_pt
            # Ensure at least min size and within bounds
            # Clamp each
            nx1 = max(0, min(self.map_w, nx1))
            nx2 = max(0, min(self.map_w, nx2))
            ny1 = max(0, min(self.map_h, ny1))
            ny2 = max(0, min(self.map_h, ny2))
            # Ensure ordering
            lx, rx = (nx1, nx2) if nx1 < nx2 else (nx2, nx1)
            ty, by = (ny1, ny2) if ny1 < ny2 else (ny2, ny1)
            if rx - lx < MIN_ZONE_ORIGINAL or by - ty < MIN_ZONE_ORIGINAL:
                return
            sel["points"] = [[lx, ty], [rx, ty], [rx, by], [lx, by]]
            self._render()

    def _on_release(self, event):
        if not self._drag_start or not self._drag_mode:
            return
        dx, dy = event.x, event.y
        dx = max(self.ox, min(self.ox + self.sw, dx))
        dy = max(self.oy, min(self.oy + self.sh, dy))
        start = self._drag_start

        if self._drag_mode == "create":
            # Check drag distance
            if abs(dx - start[0]) < MIN_DRAG_DISPLAY or abs(dy - start[1]) < MIN_DRAG_DISPLAY:
                self._drag_start = None
                self._drag_current = None
                self._drag_mode = None
                self._render()
                return
            # Convert start and end to original coords
            p1 = self._display_to_original(start[0], start[1])
            p2 = self._display_to_original(dx, dy)
            if not p1 or not p2:
                self._drag_start = None
                self._drag_current = None
                self._drag_mode = None
                return
            # Validate size in original
            lx = min(p1[0], p2[0])
            rx = max(p1[0], p2[0])
            ty = min(p1[1], p2[1])
            by = max(p1[1], p2[1])
            if rx - lx < MIN_ZONE_ORIGINAL or by - ty < MIN_ZONE_ORIGINAL:
                messagebox.showwarning("Zone too small", "Zone is too small. Drag a larger rectangle.")
                self._drag_start = None
                self._drag_current = None
                self._drag_mode = None
                self._render()
                return
            # Ask for name
            name = simpledialog.askstring("Zone Name", "Enter zone name:", parent=self.root)
            if name is None:
                # Cancel creation
                self._drag_start = None
                self._drag_current = None
                self._drag_mode = None
                self._render()
                return
            name = name.strip()
            if not name:
                messagebox.showwarning("Invalid Name", "Zone name cannot be empty.")
                self._drag_start = None
                self._drag_current = None
                self._drag_mode = None
                self._render()
                return
            # Create in-memory authoritative (do NOT reload stale file)
            try:
                zone = self.zone_manager.build_rectangle(self.map_id, name, p1, p2, existing_zones=self.zones)
                self.zones.append(zone)
                self.selected_id = zone["zone_id"]
                print(f"[ZONE DEBUG] CREATE\nmap_id={self.map_id}\nzone_id={zone['zone_id']}\nname={zone['name']}\npoints={zone['points']}\nself.zones_count={len(self.zones)}\nself.zones_ids={[z['zone_id'] for z in self.zones]}")
                print(f"[ZoneEditor] Created zone: map_id={self.map_id} zone_id={zone['zone_id']} name={zone['name']} points={zone['points']} self.zones count={len(self.zones)}")
                print(f"[ZoneEditor] ZoneManager path: {self.zone_manager.zones_dir / (self.map_id + '.json')}")
            except ValueError as e:
                messagebox.showerror("Error", str(e))
        elif self._drag_mode in ("move", "resize"):
            # Already updated live, just need to persist? We'll persist on Save, but we have mutated self.zones directly
            # For move/resize we mutated in place, but not yet saved to disk — keep in memory until Save
            pass

        self._drag_start = None
        self._drag_current = None
        self._drag_mode = None
        self._resize_corner = None
        self._move_offset = None
        self._render()

    def _on_motion(self, event):
        dx, dy = event.x, event.y
        sel = self._get_selected_zone()
        if sel and self._corner_hit(dx, dy, sel):
            self.canvas.config(cursor="sizing")
        elif sel:
            x1, y1, x2, y2 = self._zone_bbox_display(sel)
            if x1 <= dx <= x2 and y1 <= dy <= y2:
                self.canvas.config(cursor="fleur")
            else:
                self.canvas.config(cursor="crosshair")
        else:
            # Check if over any zone
            hit = self._hit_test(dx, dy)
            if hit:
                self.canvas.config(cursor="hand2")
            else:
                self.canvas.config(cursor="crosshair")

    # ── toolbar actions ─────────────────────────────────────────────────

    def on_rename(self):
        sel = self._get_selected_zone()
        if not sel:
            messagebox.showinfo("Rename", "Select a zone first.")
            return
        new_name = simpledialog.askstring("Rename Zone", "Enter new name:", initialvalue=sel["name"], parent=self.root)
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning("Rename", "Name cannot be empty.")
            return
        sel["name"] = new_name
        self._render()

    def on_delete(self, event=None):
        # Keyboard Delete may pass event; ignore it
        sel = self._get_selected_zone()
        if not sel:
            messagebox.showinfo("Delete Zone", "Select a zone first.", parent=self.root)
            return
        if not messagebox.askyesno("Delete Zone", f'Delete zone "{sel["name"]}"?', parent=self.root):
            return
        # Remove immediately from editor, update count, clear selection, redraw
        self.zones = [z for z in self.zones if z["zone_id"] != sel["zone_id"]]
        self.selected_id = None
        # Clear any pending drag state that might reference deleted zone
        self._drag_start = None
        self._drag_current = None
        self._drag_mode = None
        self._resize_corner = None
        self._move_offset = None
        self._render()

    def on_save(self):
        print(f"[ZONE DEBUG] SAVE START\nmap_id={self.map_id}\nself.zones_count={len(self.zones)}\nself.zones_ids={[z['zone_id'] for z in self.zones]}")
        print(f"[ZoneEditor] SAVE map_id={self.map_id} self.zones count={len(self.zones)} zone_ids={[z['zone_id'] for z in self.zones]}")
        print(f"[ZoneEditor] Save path: {self.zone_manager.zones_dir / (self.map_id + '.json')}")
        # Validate all zones before save
        for z in self.zones:
            xs = [p[0] for p in z["points"]]
            ys = [p[1] for p in z["points"]]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            if w < MIN_ZONE_ORIGINAL or h < MIN_ZONE_ORIGINAL:
                messagebox.showerror("Save Failed", f"Zone '{z['name']}' is too small.")
                return
            # Clamp check already done, but ensure within bounds
            for x, y in z["points"]:
                if not (0 <= x <= self.map_w and 0 <= y <= self.map_h):
                    messagebox.showerror("Save Failed", f"Zone '{z['name']}' is outside map bounds.")
                    return
        try:
            self.zone_manager.save_zones(self.map_id, self.zones)
            # Verify file immediately after saving
            import json
            p = self.zone_manager.zones_dir / f"{self.map_id}.json"
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                print(f"[ZONE DEBUG] SAVE COMPLETE\npath={p.resolve()}\nexists={p.exists()}\nfile_size={p.stat().st_size if p.exists() else 0}\nfile_contents={json.dumps(data, indent=2)}\nfile_zone_count={len(data.get('zones', []))}\nfile_zone_ids={[z.get('zone_id') for z in data.get('zones', [])]}")
                print(f"[ZoneEditor] Saved file: {p} count={len(data.get('zones', []))} zones={[z['name'] for z in data.get('zones', [])]}")
            except Exception as ve:
                print(f"[ZoneEditor] Saved file verification failed: {ve}")
            messagebox.showinfo("Saved", f"Saved {len(self.zones)} zone(s) for map '{self.map_name}'.")
        except Exception as e:
            print(f"[ZoneEditor] Save failed: {e}")
            messagebox.showerror("Save Failed", str(e))

    def on_cancel(self):
        # Check for unsaved changes and prompt to save
        try:
            saved = self.zone_manager.get_zones(self.map_id)
            # Compare by zone_id and name/points
            current_ids = {z["zone_id"] for z in self.zones}
            saved_ids = {z["zone_id"] for z in saved}
            if current_ids != saved_ids or len(self.zones) != len(saved):
                # Also check if any zone content differs
                needs_save = True
                if len(self.zones) == len(saved):
                    # Deep compare
                    cur_sorted = sorted(self.zones, key=lambda z: z["zone_id"])
                    saved_sorted = sorted(saved, key=lambda z: z["zone_id"])
                    needs_save = cur_sorted != saved_sorted
                else:
                    needs_save = True
                if needs_save:
                    resp = messagebox.askyesnocancel("Unsaved Changes", f"You have {len(self.zones)} zone(s) with unsaved changes.\n\nSave before closing?", parent=self.root)
                    if resp is None:  # Cancel
                        return
                    elif resp is True:  # Yes, save
                        # Reuse save logic without showing info dialog twice
                        try:
                            self.zone_manager.save_zones(self.map_id, self.zones)
                            print(f"[ZONE DEBUG] AUTO-SAVE ON CLOSE map_id={self.map_id} count={len(self.zones)}")
                        except Exception as e:
                            messagebox.showerror("Save Failed", str(e))
                            return
                    # else No: discard changes
        except Exception:
            pass
        try:
            print(f"[ZONE DEBUG] EDITOR CLOSE\nmap_id={self.map_id}\nself.zones_count={len(self.zones)}\nself.zones_ids={[z['zone_id'] for z in self.zones]}")
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Visual Zone Editor - Draw zones on Bird's-Eye Map")
    parser.add_argument("--maps-dir", type=str, default=None, help="Maps directory override")
    parser.add_argument("--zones-dir", type=str, default=None, help="Zones directory override")
    args = parser.parse_args()
    app = ZoneEditorApp(maps_dir=args.maps_dir, zones_dir=args.zones_dir)
    app.run()


if __name__ == "__main__":
    main()

"""Bird's-Eye Map Management UI — Phase 2 Step 1.

Run:
    python -m app.phase2.maps.gallery

No CCTV, no YOLO, no ByteTrack. Only Tkinter + Pillow + file handling.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path
from typing import Optional

from PIL import Image, ImageTk

from app.phase2.maps.manager import MapManager, get_map_manager

# ── styling ───────────────────────────────────────────────────────────
BG = "#f5f7fb"
CARD_BG = "#ffffff"
CARD_BORDER = "#e3e8ef"
HEADER_BG = "#0f172a"
PRIMARY = "#2563eb"
PRIMARY_HOVER = "#1d4ed8"
SUCCESS = "#16a34a"
MUTED = "#64748b"
TEXT_DARK = "#0f172a"
TEXT_MED = "#334155"
CARD_RADIUS = 12  # visual only via padding
THUMB_MAX = (320, 200)  # max thumbnail size, preserves aspect ratio


class GalleryApp:
    def __init__(self, maps_dir: str | Path | None = None):
        self.manager = get_map_manager(maps_dir)
        self.root = tk.Tk()
        self.root.title("Bird's-Eye Maps — MONETIZE Retail Analytics")
        self.root.configure(bg=BG)
        self.root.geometry("1000x700")
        self.root.minsize(850, 600)

        # keep image refs to prevent GC
        self._thumb_refs: dict[str, ImageTk.PhotoImage] = {}

        self._build_ui()
        self.refresh()

        # status auto-clear
        self._status_after: Optional[str] = None

    # ── layout ────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg=HEADER_BG, height=110)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Label(
            header, text="BIRD'S-EYE MAPS", bg=HEADER_BG, fg="white",
            font=("Segoe UI", 20, "bold")
        ).pack(pady=(22, 2))

        tk.Label(
            header, text="Select a floor / map for the store", bg=HEADER_BG, fg="#cbd5e1",
            font=("Segoe UI", 11)
        ).pack()

        # Toolbar
        toolbar = tk.Frame(self.root, bg=BG)
        toolbar.pack(fill="x", padx=18, pady=14)

        # Left: upload button (very obvious, primary)
        self.upload_btn = tk.Button(
            toolbar, text="＋  Upload Map", command=self.on_upload,
            bg=PRIMARY, fg="white", activebackground=PRIMARY_HOVER, activeforeground="white",
            font=("Segoe UI", 11, "bold"), padx=18, pady=8, bd=0, cursor="hand2",
            relief="flat"
        )
        self.upload_btn.pack(side="left")
        self.upload_btn.bind("<Enter>", lambda e: self.upload_btn.config(bg=PRIMARY_HOVER))
        self.upload_btn.bind("<Leave>", lambda e: self.upload_btn.config(bg=PRIMARY))

        tk.Label(toolbar, text="  JPG · JPEG · PNG · WEBP  ", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=10)

        # Right: helper text
        tk.Label(toolbar, text="Click Select to choose the active floor", bg=BG, fg=MUTED, font=("Segoe UI", 9, "italic")).pack(side="right")

        # Status bar
        self.status = tk.Label(self.root, text="", bg=BG, fg=SUCCESS, font=("Segoe UI", 10), anchor="w")
        self.status.pack(fill="x", padx=18, pady=(0, 6))

        # Scrollable cards area
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.canvas = tk.Canvas(container, bg=BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = tk.Frame(self.canvas, bg=BG)

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Empty state label (hidden when maps exist)
        self.empty_label = tk.Label(
            self.scroll_frame, text="No maps yet.\nClick \"Upload Map\" to add your first floor plan.",
            bg=BG, fg=MUTED, font=("Segoe UI", 11), justify="center"
        )

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── helpers ───────────────────────────────────────────────────────

    def set_status(self, msg: str, is_error: bool = False):
        self.status.config(text=msg, fg="#dc2626" if is_error else SUCCESS)
        if self._status_after:
            self.root.after_cancel(self._status_after)
        self._status_after = self.root.after(3500, lambda: self.status.config(text=""))

    def _clear_cards(self):
        for w in self.scroll_frame.winfo_children():
            if w is not self.empty_label:
                w.destroy()
        self._thumb_refs.clear()

    # ── actions ───────────────────────────────────────────────────────

    def on_upload(self):
        path = filedialog.askopenfilename(
            title="Select Bird's-Eye Map Image",
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.webp"),
                ("JPEG", "*.jpg *.jpeg"),
                ("PNG", "*.png"),
                ("WEBP", "*.webp"),
                ("All files", "*.*"),
            ]
        )
        if not path:
            return
        try:
            meta = self.manager.upload_map(path)
            self.set_status(f"Map uploaded successfully — {meta['width']} × {meta['height']}")
            self.refresh()
        except ValueError as e:
            messagebox.showerror("Upload failed", str(e))
            self.set_status(str(e), is_error=True)
        except Exception as e:
            messagebox.showerror("Upload failed", f"Unexpected error: {e}")
            self.set_status("Upload failed", is_error=True)

    def on_select(self, map_id: str):
        if self.manager.select_map(map_id):
            self.set_status("Map selected ✓")
            self.refresh()
        else:
            messagebox.showerror("Error", "Failed to select map.")

    def on_rename(self, map_id: str, current_name: str):
        new_name = simpledialog.askstring("Rename Map", "Enter new name:", initialvalue=current_name, parent=self.root)
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning("Rename", "Name cannot be empty.")
            return
        try:
            ok = self.manager.rename_map(map_id, new_name)
            if ok:
                self.set_status(f"Renamed to \"{new_name}\"")
                self.refresh()
            else:
                messagebox.showerror("Error", "Map not found.")
        except ValueError as e:
            messagebox.showerror("Rename failed", str(e))

    def on_delete(self, map_id: str, name: str):
        if not messagebox.askyesno("Delete Map", f"Delete this Bird's-Eye map?\n\n\"{name}\"\nThis cannot be undone.", parent=self.root):
            return
        ok = self.manager.delete_map(map_id)
        if ok:
            self.set_status("Map deleted")
            self.refresh()
        else:
            messagebox.showerror("Error", "Map not found or already deleted.")

    # ── render ────────────────────────────────────────────────────────

    def refresh(self):
        self._clear_cards()
        maps = self.manager.list_maps()
        selected_id = self.manager.get_selected_map_id()

        if not maps:
            self.empty_label.pack(pady=60)
            return
        else:
            self.empty_label.pack_forget()

        # Grid: 2 columns on narrow, 3 on wide — use 2 fixed for simplicity, responsive
        cols = 2
        # Use grid inside scroll_frame
        for idx, meta in enumerate(maps):
            r, c = divmod(idx, cols)
            card = self._create_card(meta, is_selected=(meta["map_id"] == selected_id))
            card.grid(row=r, column=c, padx=10, pady=10, sticky="n")

        # Make columns expand evenly
        for col in range(cols):
            self.scroll_frame.grid_columnconfigure(col, weight=1)

    def _create_card(self, meta: dict, is_selected: bool) -> tk.Frame:
        map_id = meta["map_id"]
        name = meta["name"]
        w, h = meta["width"], meta["height"]
        image_path = meta["image_path"]

        outer = tk.Frame(self.scroll_frame, bg=CARD_BORDER, bd=0, padx=1, pady=1)
        card = tk.Frame(outer, bg=CARD_BG, bd=0)
        card.pack(fill="both", expand=True)

        # Selected accent top border
        if is_selected:
            accent = tk.Frame(card, bg=SUCCESS, height=4)
            accent.pack(fill="x", side="top")

        # Thumbnail area — fixed height, centered, aspect preserved
        thumb_frame = tk.Frame(card, bg="#f8fafc", width=340, height=210)
        thumb_frame.pack(fill="x", padx=12, pady=(12, 8))
        thumb_frame.pack_propagate(False)

        # Load thumbnail preserving aspect ratio
        try:
            thumb_img = MapManager.generate_thumbnail(image_path, THUMB_MAX)
            tk_img = ImageTk.PhotoImage(thumb_img)
            self._thumb_refs[map_id] = tk_img  # keep ref
            lbl = tk.Label(thumb_frame, image=tk_img, bg="#f8fafc")
            lbl.pack(expand=True)
        except Exception:
            tk.Label(thumb_frame, text="Preview unavailable", bg="#f8fafc", fg=MUTED, font=("Segoe UI", 9, "italic")).pack(expand=True)

        # Name
        tk.Label(card, text=name, bg=CARD_BG, fg=TEXT_DARK, font=("Segoe UI", 11, "bold"), anchor="w", wraplength=300, justify="left").pack(fill="x", padx=12)

        # Dimensions
        tk.Label(card, text=f"{w} × {h}", bg=CARD_BG, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=12, pady=(2, 10))

        # Buttons row
        btn_row = tk.Frame(card, bg=CARD_BG)
        btn_row.pack(fill="x", padx=12, pady=(0, 12))

        if is_selected:
            sel_btn = tk.Label(btn_row, text="Selected ✓", bg=SUCCESS, fg="white", font=("Segoe UI", 9, "bold"), padx=14, pady=6)
            sel_btn.pack(side="left")
        else:
            sel_btn = tk.Button(
                btn_row, text="Select", command=lambda mid=map_id: self.on_select(mid),
                bg=PRIMARY, fg="white", activebackground=PRIMARY_HOVER, bd=0, padx=14, pady=4,
                font=("Segoe UI", 9, "bold"), cursor="hand2"
            )
            sel_btn.pack(side="left")

        # Rename / Delete — subtle text buttons
        tk.Button(
            btn_row, text="Rename", command=lambda mid=map_id, n=name: self.on_rename(mid, n),
            bg=CARD_BG, fg=TEXT_MED, bd=0, font=("Segoe UI", 9), cursor="hand2",
            activebackground="#f1f5f9"
        ).pack(side="left", padx=(10, 2))

        tk.Button(
            btn_row, text="Delete", command=lambda mid=map_id, n=name: self.on_delete(mid, n),
            bg=CARD_BG, fg="#dc2626", bd=0, font=("Segoe UI", 9), cursor="hand2",
            activebackground="#fef2f2"
        ).pack(side="left", padx=2)

        # Card hover subtle
        for widget in [card, thumb_frame]:
            widget.bind("<Enter>", lambda e, c=card: None)

        return outer

    # ── run ───────────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


def main():
    """Entry point for `python -m app.phase2.maps.gallery`."""
    app = GalleryApp()
    app.run()


if __name__ == "__main__":
    main()

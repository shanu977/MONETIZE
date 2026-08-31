"""Map storage manager for Bird's-Eye Map Management (Phase 2 Step 1).

Storage layout:
    maps/
        images/
            <map_id>.png|jpg|webp  (preserved extension)
        metadata/
            <map_id>.json          {map_id, name, image_path, width, height, created_at}
        selected.json              {selected_map_id: str|None}

No YOLO / ByteTrack / CCTV dependencies. Pure file + image validation.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from app.config import PROJECT_ROOT

DEFAULT_MAPS_DIR = PROJECT_ROOT / "maps"
IMAGES_DIRNAME = "images"
METADATA_DIRNAME = "metadata"
SELECTED_FILENAME = "selected.json"

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _maps_dir(maps_dir: str | Path | None) -> Path:
    return Path(maps_dir) if maps_dir else DEFAULT_MAPS_DIR


def _images_dir(maps_dir: Path) -> Path:
    return maps_dir / IMAGES_DIRNAME


def _metadata_dir(maps_dir: Path) -> Path:
    return maps_dir / METADATA_DIRNAME


def _selected_path(maps_dir: Path) -> Path:
    return maps_dir / SELECTED_FILENAME


def _ensure_dirs(maps_dir: Path) -> None:
    _images_dir(maps_dir).mkdir(parents=True, exist_ok=True)
    _metadata_dir(maps_dir).mkdir(parents=True, exist_ok=True)


def _generate_map_id() -> str:
    # 8-char hex is enough for uniqueness in this project, collision check done by caller
    return uuid.uuid4().hex[:8]


def _validate_extension(path: Path) -> None:
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")


def _validate_and_get_dimensions(image_path: Path) -> tuple[int, int]:
    """Validate that image is readable and return (width, height). Raises ValueError on failure."""
    if not image_path.exists():
        raise ValueError(f"File not found: {image_path}")
    _validate_extension(image_path)
    try:
        with Image.open(image_path) as img:
            img.verify()  # check corruption without loading full data
    except Exception as e:
        raise ValueError(f"Invalid or corrupted image: {e}")
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            if w <= 0 or h <= 0:
                raise ValueError("Image has invalid dimensions")
            return w, h
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to read image dimensions: {e}")


def _write_metadata(maps_dir: Path, map_id: str, name: str, image_path: Path, width: int, height: int, created_at: str) -> Path:
    meta = {
        "map_id": map_id,
        "name": name,
        "image_path": str(image_path),
        "width": width,
        "height": height,
        "created_at": created_at,
    }
    meta_path = _metadata_dir(maps_dir) / f"{map_id}.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta_path


class MapManager:
    """Handles all file operations for Bird's-Eye maps."""

    def __init__(self, maps_dir: str | Path | None = None):
        self.maps_dir = _maps_dir(maps_dir)
        _ensure_dirs(self.maps_dir)

    # ── upload ──────────────────────────────────────────────────────────

    def upload_map(self, source_path: str | Path, name: Optional[str] = None) -> dict:
        """
        Validate, copy image to storage, create metadata, auto-select.
        Returns metadata dict. Raises ValueError on invalid input.
        Safe: never crashes, always raises ValueError with message.
        """
        src = Path(source_path)
        w, h = _validate_and_get_dimensions(src)

        # Generate unique ID
        _ensure_dirs(self.maps_dir)
        for _ in range(10):
            map_id = _generate_map_id()
            if not (_metadata_dir(self.maps_dir) / f"{map_id}.json").exists():
                break
        else:
            raise ValueError("Failed to generate unique map ID")

        ext = src.suffix.lower()
        # Use map_id as filename to avoid collisions, preserve extension
        dest_image = _images_dir(self.maps_dir) / f"{map_id}{ext}"
        try:
            shutil.copy2(src, dest_image)
        except Exception as e:
            raise ValueError(f"Failed to copy image: {e}")

        display_name = (name.strip() if name and name.strip() else src.stem)
        # Fallback if name empty
        if not display_name:
            display_name = f"Map {map_id}"

        created_at = datetime.now().isoformat(timespec="seconds")
        _write_metadata(self.maps_dir, map_id, display_name, dest_image, w, h, created_at)

        # Auto-select newly uploaded map
        self.select_map(map_id)

        return self.get_map(map_id)  # type: ignore

    # ── listing ─────────────────────────────────────────────────────────

    def list_maps(self) -> list[dict]:
        """Return all maps sorted by created_at descending (newest first)."""
        meta_dir = _metadata_dir(self.maps_dir)
        if not meta_dir.exists():
            return []
        maps = []
        for p in meta_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                # basic sanity
                if "map_id" in data and "name" in data:
                    maps.append(data)
            except Exception:
                continue
        # sort newest first
        maps.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        return maps

    def get_map(self, map_id: str) -> Optional[dict]:
        p = _metadata_dir(self.maps_dir) / f"{map_id}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def has_map(self, map_id: str) -> bool:
        return (_metadata_dir(self.maps_dir) / f"{map_id}.json").exists()

    # ── rename ──────────────────────────────────────────────────────────

    def rename_map(self, map_id: str, new_name: str) -> bool:
        if not new_name or not new_name.strip():
            raise ValueError("Map name cannot be empty")
        meta = self.get_map(map_id)
        if meta is None:
            return False
        meta["name"] = new_name.strip()
        # keep map_id stable, keep image_path, width, height, update? keep created_at
        meta_path = _metadata_dir(self.maps_dir) / f"{map_id}.json"
        try:
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    # ── delete ──────────────────────────────────────────────────────────

    def delete_map(self, map_id: str) -> bool:
        """Delete image + metadata. Clears selection if needed. Returns False if not found, never crashes."""
        meta = self.get_map(map_id)
        if meta is None:
            return False
        # Remove image file (best effort)
        try:
            img_path = Path(meta.get("image_path", ""))
            # Ensure path is inside maps_dir to avoid arbitrary deletion
            # Only delete if it resides under maps/images
            if img_path.exists():
                try:
                    # safety: must be inside maps_dir
                    img_path.resolve().relative_to(self.maps_dir.resolve())
                    img_path.unlink(missing_ok=True)
                except ValueError:
                    # outside maps_dir — do not delete, just skip
                    pass
                except Exception:
                    pass
        except Exception:
            pass
        # Remove metadata
        try:
            (_metadata_dir(self.maps_dir) / f"{map_id}.json").unlink(missing_ok=True)
        except Exception:
            pass
        # Clear selection if this was selected
        try:
            if self.get_selected_map_id() == map_id:
                self.clear_selection()
        except Exception:
            pass
        return True

    # ── selection ───────────────────────────────────────────────────────

    def select_map(self, map_id: str) -> bool:
        if not self.has_map(map_id):
            return False
        sel_path = _selected_path(self.maps_dir)
        try:
            sel_path.write_text(json.dumps({"selected_map_id": map_id}, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    def get_selected_map_id(self) -> Optional[str]:
        p = _selected_path(self.maps_dir)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            mid = data.get("selected_map_id")
            # Validate that it still exists
            if mid and self.has_map(mid):
                return str(mid)
            # stale selection → clear
            if mid and not self.has_map(mid):
                return None
            return mid
        except Exception:
            return None

    def get_selected_map(self) -> Optional[dict]:
        mid = self.get_selected_map_id()
        if not mid:
            return None
        return self.get_map(mid)

    def clear_selection(self) -> None:
        p = _selected_path(self.maps_dir)
        try:
            if p.exists():
                p.write_text(json.dumps({"selected_map_id": None}, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ── thumbnail helper ────────────────────────────────────────────────

    @staticmethod
    def generate_thumbnail(image_path: str | Path, thumb_size: tuple[int, int] = (400, 280)) -> Image.Image:
        """
        Generate thumbnail PIL Image preserving aspect ratio.
        thumb_size is max width, max height. Never stretches.
        """
        p = Path(image_path)
        with Image.open(p) as img:
            # Convert to RGB if needed (for webp etc)
            if img.mode in ("RGBA", "LA"):
                # keep alpha? convert to RGB with white bg for thumbnail
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img_copy = img.copy()
            img_copy.thumbnail(thumb_size, Image.LANCZOS)
            return img_copy


def get_map_manager(maps_dir: str | Path | None = None) -> MapManager:
    return MapManager(maps_dir=maps_dir)

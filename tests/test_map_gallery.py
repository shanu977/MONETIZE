"""Tests for Phase 2 Step 1 — Bird's-Eye Map Management."""
import shutil
import tempfile
from pathlib import Path
import json

import pytest
from PIL import Image

from app.phase2.maps.manager import MapManager, get_map_manager


# ── helpers ───────────────────────────────────────────────────────────
def make_image(path: Path, size: tuple[int, int], fmt: str = "PNG", color=(120, 180, 200)):
    img = Image.new("RGB", size, color)
    img.save(path, fmt)
    return path


@pytest.fixture
def tmp_maps(tmp_path):
    """Isolated maps dir per test."""
    return tmp_path / "maps"


# ── upload valid formats ──────────────────────────────────────────────

class TestUploadValidFormats:
    def test_upload_valid_png(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "src.png"
        make_image(src, (640, 480), "PNG")
        meta = m.upload_map(src)
        assert meta["width"] == 640 and meta["height"] == 480
        assert Path(meta["image_path"]).exists()
        assert Path(meta["image_path"]).suffix == ".png"

    def test_upload_valid_jpg(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "src.jpg"
        make_image(src, (800, 600), "JPEG")
        meta = m.upload_map(src)
        assert meta["width"] == 800 and meta["height"] == 600
        assert Path(meta["image_path"]).suffix == ".jpg"

    def test_upload_valid_jpeg(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "src.jpeg"
        make_image(src, (1024, 768), "JPEG")
        # rename to .jpeg explicitly
        assert src.suffix == ".jpeg"
        meta = m.upload_map(src)
        assert meta["width"] == 1024

    def test_upload_valid_webp(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "src.webp"
        make_image(src, (320, 240), "WEBP")
        meta = m.upload_map(src)
        assert meta["width"] == 320 and meta["height"] == 240
        assert Path(meta["image_path"]).suffix == ".webp"


# ── invalid / corrupted ───────────────────────────────────────────────

class TestInvalidImages:
    def test_invalid_extension_rejected(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "bad.txt"
        src.write_text("not an image")
        with pytest.raises(ValueError, match="Unsupported"):
            m.upload_map(src)

    def test_invalid_image_content(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "fake.png"
        src.write_bytes(b"this is not png data \x00\x01\x02")
        with pytest.raises(ValueError, match="Invalid or corrupted"):
            m.upload_map(src)

    def test_corrupted_image(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "corrupt.jpg"
        make_image(src, (100, 100), "JPEG")
        # corrupt after creation
        with open(src, "r+b") as f:
            f.seek(10)
            f.write(b"\x00\xff\x00\xff\x00\xff")
            f.truncate(50)
        # Some corruptions still readable, so force fully broken
        src2 = tmp_maps.parent / "corrupt2.png"
        src2.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00garbage")
        with pytest.raises(ValueError):
            m.upload_map(src2)

    def test_missing_file(self, tmp_maps):
        m = MapManager(tmp_maps)
        with pytest.raises(ValueError, match="File not found"):
            m.upload_map("/nonexistent/path.png")

    def test_unsupported_extension_bmp(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "img.bmp"
        make_image(src, (100, 100), "BMP")
        with pytest.raises(ValueError, match="Unsupported"):
            m.upload_map(src)


# ── dimensions & metadata ─────────────────────────────────────────────

class TestDimensionsAndMetadata:
    def test_dimensions_correctly_detected(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "dim.png"
        make_image(src, (1920, 1080), "PNG")
        meta = m.upload_map(src)
        assert meta["width"] == 1920
        assert meta["height"] == 1080

    def test_metadata_creation(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "meta.png"
        make_image(src, (400, 300), "PNG")
        meta = m.upload_map(src)
        # Must contain required fields
        for key in ("map_id", "name", "image_path", "width", "height", "created_at"):
            assert key in meta
        # Files exist in new layout
        assert (tmp_maps / "images" / (meta["map_id"] + Path(meta["image_path"]).suffix)).exists()
        assert (tmp_maps / "metadata" / f"{meta['map_id']}.json").exists()
        stored = json.loads((tmp_maps / "metadata" / f"{meta['map_id']}.json").read_text())
        assert stored["map_id"] == meta["map_id"]
        assert stored["width"] == 400

    def test_unique_map_id_generation(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "a.png"
        make_image(src, (100, 100), "PNG")
        meta1 = m.upload_map(src)
        meta2 = m.upload_map(src)
        assert meta1["map_id"] != meta2["map_id"]
        assert len(m.list_maps()) == 2

    def test_safe_file_handling_no_arbitrary_path(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "safe.png"
        make_image(src, (100, 100), "PNG")
        meta = m.upload_map(src)
        # stored path must be inside maps/images, not the source arbitrary path
        stored_path = Path(meta["image_path"])
        assert str(stored_path).startswith(str(tmp_maps / "images"))
        assert stored_path.name.startswith(meta["map_id"])


# ── listing / selection / rename / deletion ───────────────────────────

class TestMapOperations:
    def test_map_listing(self, tmp_maps):
        m = MapManager(tmp_maps)
        for i in range(3):
            src = tmp_maps.parent / f"l{i}.png"
            make_image(src, (100 + i * 10, 100), "PNG")
            m.upload_map(src)
        assert len(m.list_maps()) == 3

    def test_map_selection(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "sel.png"
        make_image(src, (200, 200), "PNG")
        meta = m.upload_map(src)
        # upload auto-selects
        assert m.get_selected_map_id() == meta["map_id"]
        # select another
        src2 = tmp_maps.parent / "sel2.png"
        make_image(src2, (200, 200), "PNG")
        meta2 = m.upload_map(src2)
        assert m.get_selected_map_id() == meta2["map_id"]
        # manually select first again
        assert m.select_map(meta["map_id"]) is True
        assert m.get_selected_map_id() == meta["map_id"]

    def test_newly_uploaded_becomes_selected(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "first.png"
        make_image(src, (100, 100), "PNG")
        m1 = m.upload_map(src)
        assert m.get_selected_map_id() == m1["map_id"]
        src2 = tmp_maps.parent / "second.png"
        make_image(src2, (100, 100), "PNG")
        m2 = m.upload_map(src2)
        assert m.get_selected_map_id() == m2["map_id"]

    def test_gallery_refresh_after_upload(self, tmp_maps):
        m = MapManager(tmp_maps)
        assert len(m.list_maps()) == 0
        src = tmp_maps.parent / "g.png"
        make_image(src, (100, 100), "PNG")
        m.upload_map(src)
        assert len(m.list_maps()) == 1
        src2 = tmp_maps.parent / "g2.png"
        make_image(src2, (100, 100), "PNG")
        m.upload_map(src2)
        assert len(m.list_maps()) == 2

    def test_map_rename(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "rn.png"
        make_image(src, (100, 100), "PNG")
        meta = m.upload_map(src)
        assert m.rename_map(meta["map_id"], "Hyderabad Main Store") is True
        updated = m.get_map(meta["map_id"])
        assert updated["name"] == "Hyderabad Main Store"
        assert updated["map_id"] == meta["map_id"]  # ID stable

    def test_rename_preserves_id(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "rp.png"
        make_image(src, (100, 100), "PNG")
        meta = m.upload_map(src)
        old_id = meta["map_id"]
        m.rename_map(old_id, "New Name")
        assert m.get_map(old_id) is not None
        assert m.get_map(old_id)["map_id"] == old_id

    def test_map_deletion(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "del.png"
        make_image(src, (150, 150), "PNG")
        meta = m.upload_map(src)
        img_path = Path(meta["image_path"])
        assert img_path.exists()
        assert m.delete_map(meta["map_id"]) is True
        assert not img_path.exists()
        assert not (tmp_maps / "metadata" / f"{meta['map_id']}.json").exists()
        assert m.get_selected_map_id() is None  # was selected, cleared

    def test_delete_missing_file_safe(self, tmp_maps):
        m = MapManager(tmp_maps)
        # delete non-existent should not crash, return False
        assert m.delete_map("nonexistent") is False
        # double delete
        src = tmp_maps.parent / "dd.png"
        make_image(src, (100, 100), "PNG")
        meta = m.upload_map(src)
        assert m.delete_map(meta["map_id"]) is True
        assert m.delete_map(meta["map_id"]) is False  # already gone, no crash

    def test_deleting_one_does_not_affect_another(self, tmp_maps):
        m = MapManager(tmp_maps)
        src1 = tmp_maps.parent / "a1.png"
        src2 = tmp_maps.parent / "a2.png"
        make_image(src1, (100, 100), "PNG")
        make_image(src2, (200, 200), "PNG")
        m1 = m.upload_map(src1)
        m2 = m.upload_map(src2)
        assert m.delete_map(m1["map_id"]) is True
        assert m.get_map(m2["map_id"]) is not None
        assert m.get_map(m1["map_id"]) is None
        assert len(m.list_maps()) == 1
        assert Path(m2["image_path"]).exists()

    def test_delete_clears_selection_only_if_needed(self, tmp_maps):
        m = MapManager(tmp_maps)
        src1 = tmp_maps.parent / "s1.png"
        src2 = tmp_maps.parent / "s2.png"
        make_image(src1, (100, 100), "PNG")
        make_image(src2, (100, 100), "PNG")
        m1 = m.upload_map(src1)
        m2 = m.upload_map(src2)
        # m2 selected
        m.select_map(m1["map_id"])
        assert m.get_selected_map_id() == m1["map_id"]
        # delete non-selected m2 → selection should stay m1
        m.delete_map(m2["map_id"])
        assert m.get_selected_map_id() == m1["map_id"]
        # delete selected m1 → selection cleared
        m.delete_map(m1["map_id"])
        assert m.get_selected_map_id() is None


# ── thumbnail & aspect ratio ──────────────────────────────────────────

class TestThumbnail:
    def test_thumbnail_generation(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "thumb.png"
        make_image(src, (800, 600), "PNG")
        meta = m.upload_map(src)
        thumb = MapManager.generate_thumbnail(meta["image_path"], (400, 280))
        assert thumb.size[0] <= 400 and thumb.size[1] <= 280
        assert thumb.size[0] > 0 and thumb.size[1] > 0

    def test_aspect_ratio_preservation_wide(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "wide.png"
        make_image(src, (800, 400), "PNG")  # 2:1
        meta = m.upload_map(src)
        thumb = MapManager.generate_thumbnail(meta["image_path"], (400, 280))
        w, h = thumb.size
        # Original 2:1, thumb should still be ~2:1, not stretched to 400x280
        assert abs((w / h) - 2.0) < 0.05

    def test_aspect_ratio_preservation_tall(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "tall.png"
        make_image(src, (400, 800), "PNG")  # 0.5
        meta = m.upload_map(src)
        thumb = MapManager.generate_thumbnail(meta["image_path"], (400, 280))
        w, h = thumb.size
        assert abs((w / h) - 0.5) < 0.05

    def test_thumbnail_never_stretches(self, tmp_maps):
        m = MapManager(tmp_maps)
        src = tmp_maps.parent / "small.png"
        make_image(src, (100, 100), "PNG")
        meta = m.upload_map(src)
        thumb = MapManager.generate_thumbnail(meta["image_path"], (400, 280))
        # small image should not be upscaled by thumbnail() (Pillow thumbnail never enlarges)
        assert thumb.size[0] <= 100 and thumb.size[1] <= 100


# ── isolation from Phase 1 ────────────────────────────────────────────

class TestIsolation:
    def test_gallery_import_does_not_load_yolo(self):
        import subprocess, sys
        code = (
            "import sys; "
            "import app.phase2.maps.gallery; "
            "mods = [m for m in sys.modules if 'ultralytics' in m.lower() or 'yolo' in m.lower()]; "
            "print(mods); "
            "assert not mods, f'YOLO modules loaded: {mods}'; "
            "assert 'app.detection.detector' not in sys.modules; "
            "assert 'app.tracking.tracker' not in sys.modules"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert result.returncode == 0, f"Subprocess failed: {result.stdout} {result.stderr}"

    def test_phase1_still_importable(self):
        from app.config import PROJECT_ROOT
        from app.models.tracking_data import BoundingBox
        b = BoundingBox(0, 0, 10, 10)
        assert b.width == 10

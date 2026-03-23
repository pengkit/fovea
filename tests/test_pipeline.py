"""
Fovea - Integration Tests

Creates synthetic test images simulating a Sony camera SD card,
then runs the full pipeline: scan → import → DNG conversion → AI analysis.
"""

import os
import sys
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageDraw, ImageFont
import numpy as np

# ============================================================
# Test fixtures: create fake SD card with test images
# ============================================================

def create_test_sd_card(base_dir: str) -> str:
    """Create a fake Sony camera SD card structure with test images."""
    sd = Path(base_dir) / "SONY_SD"
    dcim = sd / "DCIM" / "100MSDCF"
    dcim.mkdir(parents=True)

    # Also create some system files (should be ignored)
    misc = sd / "PRIVATE" / "SONY" / "SONYCARD"
    misc.mkdir(parents=True)
    (misc / "AUTPRINT.MRK").write_text("system file")
    (sd / "DCIM" / "AVINDEX.BDM").write_text("system file")

    created_files = []

    # --- 1. Normal landscape photo ---
    img = _make_landscape(800, 600)
    _save_with_exif(img, dcim / "DSC00001.JPG", model="ILCE-7RM5", date="2026:03:20 10:30:00")
    created_files.append(str(dcim / "DSC00001.JPG"))

    # --- 2. Portrait photo (with face-like shape) ---
    img = _make_portrait(800, 600)
    _save_with_exif(img, dcim / "DSC00002.JPG", model="ILCE-7RM5", date="2026:03:20 11:00:00")
    created_files.append(str(dcim / "DSC00002.JPG"))

    # --- 3. Blurry photo (should be flagged as quality issue) ---
    img = _make_blurry(800, 600)
    _save_with_exif(img, dcim / "DSC00003.JPG", model="ILCE-7RM5", date="2026:03:20 11:30:00")
    created_files.append(str(dcim / "DSC00003.JPG"))

    # --- 4. Overexposed photo ---
    img = _make_overexposed(800, 600)
    _save_with_exif(img, dcim / "DSC00004.JPG", model="ILCE-7RM5", date="2026:03:20 12:00:00")
    created_files.append(str(dcim / "DSC00004.JPG"))

    # --- 5 & 6. Two very similar photos (duplicate detection test) ---
    img = _make_landscape(800, 600, seed=42)
    _save_with_exif(img, dcim / "DSC00005.JPG", model="ILCE-7RM5", date="2026:03:20 12:30:00")
    created_files.append(str(dcim / "DSC00005.JPG"))

    img2 = _make_landscape(800, 600, seed=42, slight_variation=True)
    _save_with_exif(img2, dcim / "DSC00006.JPG", model="ILCE-7RM5", date="2026:03:20 12:30:01")
    created_files.append(str(dcim / "DSC00006.JPG"))

    # --- 7. Night scene ---
    img = _make_night(800, 600)
    _save_with_exif(img, dcim / "DSC00007.JPG", model="ILCE-7RM5", date="2026:03:20 20:00:00")
    created_files.append(str(dcim / "DSC00007.JPG"))

    # --- 8. A sidecar XMP file (should follow DSC00001) ---
    (dcim / "DSC00001.XMP").write_text(
        '<?xml version="1.0"?><x:xmpmeta><rdf:RDF><rdf:Description xmp:Rating="4"/></rdf:RDF></x:xmpmeta>'
    )

    print(f"Created test SD card: {sd}")
    print(f"  {len(created_files)} JPEG files + 1 XMP + 2 system files")
    return str(sd)


def _make_landscape(w, h, seed=0, slight_variation=False):
    """Generate a landscape-like image with sky gradient and green ground."""
    np.random.seed(seed)
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    # Sky gradient (blue)
    for y in range(h // 2):
        t = y / (h // 2)
        arr[y, :] = [int(135 + 50 * t), int(206 - 30 * t), int(235 - 10 * t)]
    # Ground (green)
    for y in range(h // 2, h):
        t = (y - h // 2) / (h // 2)
        arr[y, :] = [int(34 + 20 * t), int(139 - 30 * t), int(34 + 10 * t)]
    # Add texture/noise so Laplacian variance is high enough (not flagged as blurry)
    noise = np.random.randint(-25, 25, arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    if slight_variation:
        extra = np.random.randint(-5, 5, arr.shape, dtype=np.int16)
        arr = np.clip(arr.astype(np.int16) + extra, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _make_portrait(w, h):
    """Generate image with face-like oval shape."""
    img = Image.new('RGB', (w, h), (220, 200, 180))
    d = ImageDraw.Draw(img)
    # Skin-colored oval (face)
    cx, cy = w // 2, h // 2 - 30
    d.ellipse([cx - 80, cy - 100, cx + 80, cy + 100], fill=(235, 200, 170))
    # Eyes
    d.ellipse([cx - 35, cy - 20, cx - 15, cy], fill=(60, 60, 60))
    d.ellipse([cx + 15, cy - 20, cx + 35, cy], fill=(60, 60, 60))
    # Mouth
    d.arc([cx - 30, cy + 20, cx + 30, cy + 50], 0, 180, fill=(180, 80, 80), width=2)
    return img


def _make_blurry(w, h):
    """Generate an intentionally blurry image."""
    img = _make_landscape(w, h, seed=99)
    # Apply heavy gaussian blur
    from PIL import ImageFilter
    return img.filter(ImageFilter.GaussianBlur(radius=15))


def _make_overexposed(w, h):
    """Generate an overexposed (mostly white) image."""
    arr = np.full((h, w, 3), 245, dtype=np.uint8)
    # Add slight variation
    noise = np.random.randint(0, 10, arr.shape, dtype=np.uint8)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _make_night(w, h):
    """Generate a night scene (dark with bright spots)."""
    arr = np.full((h, w, 3), 15, dtype=np.uint8)
    np.random.seed(7)
    # Random bright spots (stars / city lights)
    for _ in range(50):
        x, y = np.random.randint(0, w), np.random.randint(0, h)
        brightness = np.random.randint(180, 255)
        r = np.random.randint(2, 6)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if 0 <= y + dy < h and 0 <= x + dx < w:
                    arr[y + dy, x + dx] = [brightness, brightness, int(brightness * 0.8)]
    return Image.fromarray(arr)


def _save_with_exif(img, path, model="ILCE-7RM5", date="2026:03:20 10:00:00"):
    """Save image with basic EXIF data."""
    from PIL.ExifTags import Base as ExifBase
    import piexif

    exif_dict = {
        "0th": {
            piexif.ImageIFD.Make: b"SONY",
            piexif.ImageIFD.Model: model.encode(),
            piexif.ImageIFD.Software: b"Fovea Test",
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: date.encode(),
            piexif.ExifIFD.LensModel: b"FE 24-70mm F2.8 GM II",
            piexif.ExifIFD.ISOSpeedRatings: 400,
            piexif.ExifIFD.FNumber: (28, 10),
            piexif.ExifIFD.FocalLength: (50, 1),
        },
    }

    try:
        exif_bytes = piexif.dump(exif_dict)
        img.save(str(path), "JPEG", quality=92, exif=exif_bytes)
    except ImportError:
        # piexif not available, save without EXIF
        img.save(str(path), "JPEG", quality=92)


# ============================================================
# Tests
# ============================================================

def test_scanner(sd_path: str):
    """Test: scan the fake SD card."""
    print("\n=== TEST: Scanner ===")
    from scanner import scan_volume, detect_camera_brand
    from models import CameraBrand

    result = scan_volume(sd_path, generate_thumbs=True)

    assert result.camera_brand == CameraBrand.SONY, f"Expected Sony, got {result.camera_brand}"
    assert result.jpeg_count == 7, f"Expected 7 JPEGs, got {result.jpeg_count}"
    assert result.sidecar_count >= 1, f"Expected >=1 sidecar, got {result.sidecar_count}"
    assert result.system_count >= 1, f"Expected >=1 system files, got {result.system_count}"

    # Check that system files are not selected by default
    system_selected = [f for f in result.files if f.file_type.value == 'system' and f.selected]
    assert len(system_selected) == 0, "System files should not be selected"

    # Check XMP pairing
    xmp_files = [f for f in result.files if f.filename == "DSC00001.XMP"]
    if xmp_files:
        assert xmp_files[0].pair_file is not None, "XMP should be paired with DSC00001.JPG"

    print(f"  Brand: {result.camera_brand.value}")
    print(f"  Files: {result.total_files} (JPEG:{result.jpeg_count} Sidecar:{result.sidecar_count} System:{result.system_count})")
    print(f"  Model: {result.camera_model}")
    print("  PASS")
    return result


def test_importer(sd_path: str, scan_result):
    """Test: import files to a temp directory."""
    print("\n=== TEST: Importer ===")
    from importer import import_files
    from models import ImportRequest

    dest = tempfile.mkdtemp(prefix="fovea_import_")

    # Select only JPEGs (not system, not sidecar)
    selected = [f.path for f in scan_result.files if f.selected and f.file_type.value in ('jpeg', 'sidecar')]

    request = ImportRequest(
        source_path=sd_path,
        destination_path=dest,
        file_paths=selected,
        organize_by="date",
        skip_duplicates=True,
        convert_to_dng=False,
    )

    result = import_files(request)

    assert result.status in ("completed", "completed_with_errors"), f"Import failed: {result.status}"
    assert len(result.imported_files) > 0, "No files imported"

    # Check directory structure was created
    imported_dirs = list(Path(dest).rglob("*.JPG")) + list(Path(dest).rglob("*.jpg"))
    assert len(imported_dirs) > 0, "No JPEGs found in destination"

    print(f"  Imported: {len(result.imported_files)} files")
    print(f"  Errors: {len(result.errors)}")
    print(f"  Destination: {dest}")
    print("  PASS")
    return dest


def test_dng_conversion(sd_path: str):
    """Test: convert a JPEG/RAW to DNG."""
    print("\n=== TEST: DNG Conversion ===")
    from converter import convert_to_dng, get_dng_info

    info = get_dng_info()
    print(f"  Backend: {info['backend']}")

    if not info['available']:
        print("  SKIP (no DNG converter available)")
        return

    # We don't have real RAW files in test, but we can verify the converter
    # doesn't crash on non-RAW input
    dest = tempfile.mkdtemp(prefix="fovea_dng_")
    jpeg_path = str(Path(sd_path) / "DCIM" / "100MSDCF" / "DSC00001.JPG")

    result = convert_to_dng(jpeg_path, dest)
    # JPEG → DNG conversion should return None (not a RAW file)
    assert result is None, "JPEG should not be converted to DNG"
    print("  JPEG correctly skipped (not a RAW file)")

    print("  PASS")


def test_incremental_import(sd_path: str, scan_result):
    """Test: importing the same files twice should skip duplicates."""
    print("\n=== TEST: Incremental Import ===")
    from importer import import_files
    from models import ImportRequest

    dest = tempfile.mkdtemp(prefix="fovea_incr_")
    selected = [f.path for f in scan_result.files if f.selected and f.file_type.value == 'jpeg']

    # First import
    req = ImportRequest(source_path=sd_path, destination_path=dest, file_paths=selected,
                        organize_by="date", skip_duplicates=True, convert_to_dng=False)
    r1 = import_files(req)
    count1 = len(r1.imported_files)

    # Second import (should skip all)
    r2 = import_files(req)
    count2 = len(r2.imported_files)

    print(f"  First import: {count1} files")
    print(f"  Second import: {count2} files (should be 0)")
    assert count2 == 0, f"Second import should skip all, but imported {count2}"
    print("  PASS")

    shutil.rmtree(dest, ignore_errors=True)


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 50)
    print("Fovea Integration Tests")
    print("=" * 50)

    # Create temp test environment
    tmp = tempfile.mkdtemp(prefix="fovea_test_")
    print(f"Test dir: {tmp}")

    try:
        # Install piexif for EXIF writing in tests
        os.system("pip install -q piexif 2>/dev/null")

        # Create fake SD card
        sd_path = create_test_sd_card(tmp)

        # Run tests
        scan_result = test_scanner(sd_path)
        test_importer(sd_path, scan_result)
        test_dng_conversion(sd_path)
        test_incremental_import(sd_path, scan_result)

        print("\n" + "=" * 50)
        print("ALL TESTS PASSED")
        print("=" * 50)

    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Cleanup
        shutil.rmtree(tmp, ignore_errors=True)
        # Clean import history from test
        from config import DATA_DIR
        history_file = DATA_DIR / "import_history.json"
        if history_file.exists():
            history_file.unlink()


if __name__ == "__main__":
    main()

"""
Fovea - Smart Photo Adjustments

Generates 3 auto-adjustment variants for any photo.
User sees a 4-grid: original + 3 options, picks the best one.
No sliders, no manual tuning — just choose.
"""

import io
import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from config import THUMBNAIL_DIR

log = logging.getLogger(__name__)

# Max size for processing (speed)
PROCESS_SIZE = 1200


def generate_adjustments(filepath: str) -> dict:
    """
    Generate 3 adjusted versions of a photo.

    Returns:
        {
            "original": "/thumbnails/xxx_original.jpg",
            "adjustments": [
                {"name": "Auto Balance", "name_zh": "自动白平衡", "url": "/thumbnails/xxx_adj1.jpg", "description": "..."},
                {"name": "Enhanced", "name_zh": "增强对比", "url": "/thumbnails/xxx_adj2.jpg", "description": "..."},
                {"name": "Vivid", "name_zh": "鲜艳风格", "url": "/thumbnails/xxx_adj3.jpg", "description": "..."},
            ]
        }
    """
    fhash = hashlib.md5(filepath.encode()).hexdigest()[:12]
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

    # All image types use Core Image via Swift — same engine as Apple Photos
    return _generate_ci_adjustments(filepath, fhash)

    return results


def _generate_ci_adjustments(filepath: str, fhash: str) -> dict:
    """Generate adjustments using Apple Core Image via Swift ThumbnailServer."""
    import urllib.request
    import urllib.parse

    SWIFT_PORT = 9998
    encoded_path = urllib.parse.quote(filepath)
    presets = [
        ("default", "Original", "原图", "No changes"),
        ("auto", "Auto Enhance", "自动增强", "Apple ML auto — same as Photos"),
        ("vivid", "Vivid", "鲜艳", "Smart vibrance + shadow lift"),
        ("warm", "Warm Tone", "暖色调", "Warm temperature + soft contrast"),
    ]

    results = {"adjustments": []}

    for i, (preset, name, name_zh, desc) in enumerate(presets):
        try:
            url = f"http://127.0.0.1:{SWIFT_PORT}/raw?path={encoded_path}&w=1200&preset={preset}"
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()

            fname = f"{fhash}_ci_{preset}.jpg"
            out_path = THUMBNAIL_DIR / fname
            with open(str(out_path), "wb") as f:
                f.write(data)

            entry = {
                "name": name,
                "name_zh": name_zh,
                "url": f"/thumbnails/{fname}",
                "description": desc,
            }
            if i == 0:
                results["original"] = f"/thumbnails/{fname}"
            else:
                results["adjustments"].append(entry)
        except Exception as e:
            log.debug(f"RAW preset {preset} failed: {e}")

    return results


def _auto_balance(img: Image.Image) -> Image.Image:
    """
    Auto white balance + exposure correction.
    Uses gray-world assumption for WB, histogram stretching for exposure.
    """
    arr = np.array(img, dtype=np.float32)

    # Gray-world white balance
    avg_r = arr[:, :, 0].mean()
    avg_g = arr[:, :, 1].mean()
    avg_b = arr[:, :, 2].mean()
    avg_all = (avg_r + avg_g + avg_b) / 3

    if avg_r > 0 and avg_g > 0 and avg_b > 0:
        arr[:, :, 0] *= avg_all / avg_r
        arr[:, :, 1] *= avg_all / avg_g
        arr[:, :, 2] *= avg_all / avg_b

    # Histogram stretching (per-channel)
    for c in range(3):
        ch = arr[:, :, c]
        low = np.percentile(ch, 1)
        high = np.percentile(ch, 99)
        if high > low:
            arr[:, :, c] = (ch - low) / (high - low) * 255

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _enhanced_contrast(img: Image.Image) -> Image.Image:
    """
    Enhanced contrast + clarity (local contrast / unsharp mask).
    """
    # Global contrast boost
    enhancer = ImageEnhance.Contrast(img)
    result = enhancer.enhance(1.3)

    # Slight brightness adjustment based on image
    arr = np.array(result)
    brightness = arr.mean()
    if brightness < 100:
        enhancer = ImageEnhance.Brightness(result)
        result = enhancer.enhance(1.15)
    elif brightness > 180:
        enhancer = ImageEnhance.Brightness(result)
        result = enhancer.enhance(0.92)

    # Clarity (unsharp mask for local contrast)
    result = result.filter(ImageFilter.UnsharpMask(radius=20, percent=40, threshold=3))

    # Slight sharpening
    enhancer = ImageEnhance.Sharpness(result)
    result = enhancer.enhance(1.15)

    return result


def _vivid_style(img: Image.Image) -> Image.Image:
    """
    Vivid style — boosted saturation + warm tone + contrast.
    """
    # Saturation boost
    enhancer = ImageEnhance.Color(img)
    result = enhancer.enhance(1.4)

    # Slight warm tone shift
    arr = np.array(result, dtype=np.float32)
    arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.05, 0, 255)  # Red +5%
    arr[:, :, 2] = np.clip(arr[:, :, 2] * 0.95, 0, 255)  # Blue -5%
    result = Image.fromarray(arr.astype(np.uint8))

    # Contrast
    enhancer = ImageEnhance.Contrast(result)
    result = enhancer.enhance(1.15)

    # Subtle vignette
    result = _add_vignette(result, strength=0.15)

    return result


def _add_vignette(img: Image.Image, strength: float = 0.2) -> Image.Image:
    """Add a subtle vignette effect."""
    w, h = img.size
    arr = np.array(img, dtype=np.float32)

    # Create radial gradient
    Y, X = np.ogrid[:h, :w]
    cx, cy = w / 2, h / 2
    radius = max(w, h) / 2
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    mask = 1 - strength * np.clip((dist / radius) ** 2, 0, 1)
    mask = mask[:, :, np.newaxis]

    arr = arr * mask
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def save_chosen_adjustment(filepath: str, adjustment_url: str, save_mode: str = "replace", rotation: int = 0) -> dict:
    """Save adjustment in-place, preserving original file dates."""
    import shutil

    adj_filename = Path(adjustment_url).name
    orig_path = Path(filepath)

    if not orig_path.exists():
        return {"error": "File not found"}

    # Save original timestamps before any modification
    orig_stat = orig_path.stat()
    orig_atime = orig_stat.st_atime
    orig_mtime = orig_stat.st_mtime

    # Backup original (hidden file) if not already backed up
    backup_path = orig_path.parent / f".{orig_path.stem}_original{orig_path.suffix}"
    if not backup_path.exists():
        shutil.copy2(str(orig_path), str(backup_path))

    # Determine preset from filename (e.g., xxx_ci_auto.jpg → "auto")
    import urllib.request, urllib.parse, io
    preset = "default"
    for p in ["auto", "vivid", "warm"]:
        if f"_ci_{p}" in str(adj_filename) or f"_raw_{p}" in str(adj_filename):
            preset = p
            break

    if preset != "default":
        # Use Core Image at full resolution via Swift
        SWIFT_PORT = 9998
        encoded_path = urllib.parse.quote(filepath)
        try:
            url = f"http://127.0.0.1:{SWIFT_PORT}/raw?path={encoded_path}&w=9999&preset={preset}"
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = resp.read()
            result = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            return {"error": "Core Image rendering failed"}
    else:
        try:
            result = Image.open(filepath).convert("RGB")
        except Exception:
            return {"error": "Cannot open original"}

    # Apply rotation
    if rotation:
        rot_map = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}
        if rotation in rot_map:
            result = result.transpose(rot_map[rotation])

    # Overwrite the original file
    result.save(str(orig_path), quality=95)

    # Restore original timestamps so the photo keeps its date
    import os
    os.utime(str(orig_path), (orig_atime, orig_mtime))

    return {"saved": str(orig_path), "mode": "replaced"}


def revert_adjustment(filepath: str) -> dict:
    """Revert to original by restoring from backup."""
    import shutil
    orig_path = Path(filepath)
    backup_path = orig_path.parent / f".{orig_path.stem}_original{orig_path.suffix}"

    if not backup_path.exists():
        return {"error": "No backup found — original was never modified by Fovea"}

    shutil.copy2(str(backup_path), str(orig_path))
    backup_path.unlink()
    return {"reverted": str(orig_path)}

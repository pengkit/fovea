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
    try:
        img = Image.open(filepath).convert("RGB")
    except Exception as e:
        log.error(f"Cannot open {filepath}: {e}")
        return {"error": str(e)}

    # Resize for processing
    img.thumbnail((PROCESS_SIZE, PROCESS_SIZE), Image.LANCZOS)

    fhash = hashlib.md5(filepath.encode()).hexdigest()[:12]
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

    # Save original preview
    orig_path = THUMBNAIL_DIR / f"{fhash}_original.jpg"
    img.save(str(orig_path), "JPEG", quality=88)

    results = {
        "original": f"/thumbnails/{fhash}_original.jpg",
        "adjustments": [],
    }

    # --- Adjustment 1: Auto White Balance + Exposure ---
    try:
        adj1 = _auto_balance(img)
        p = THUMBNAIL_DIR / f"{fhash}_adj1.jpg"
        adj1.save(str(p), "JPEG", quality=88)
        results["adjustments"].append({
            "name": "Auto Balance",
            "name_zh": "自动平衡",
            "url": f"/thumbnails/{fhash}_adj1.jpg",
            "description": "Auto white balance and exposure correction",
        })
    except Exception as e:
        log.debug(f"Adj1 failed: {e}")

    # --- Adjustment 2: Contrast + Clarity Enhancement ---
    try:
        adj2 = _enhanced_contrast(img)
        p = THUMBNAIL_DIR / f"{fhash}_adj2.jpg"
        adj2.save(str(p), "JPEG", quality=88)
        results["adjustments"].append({
            "name": "Enhanced",
            "name_zh": "增强清晰",
            "url": f"/thumbnails/{fhash}_adj2.jpg",
            "description": "Enhanced contrast and clarity",
        })
    except Exception as e:
        log.debug(f"Adj2 failed: {e}")

    # --- Adjustment 3: Vivid / Color Pop ---
    try:
        adj3 = _vivid_style(img)
        p = THUMBNAIL_DIR / f"{fhash}_adj3.jpg"
        adj3.save(str(p), "JPEG", quality=88)
        results["adjustments"].append({
            "name": "Vivid",
            "name_zh": "鲜艳风格",
            "url": f"/thumbnails/{fhash}_adj3.jpg",
            "description": "Boosted colors and vibrance",
        })
    except Exception as e:
        log.debug(f"Adj3 failed: {e}")

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


def save_chosen_adjustment(filepath: str, adjustment_url: str, save_mode: str = "replace") -> dict:
    """
    Save user's chosen adjustment.

    Args:
        filepath: Original photo path
        adjustment_url: URL of chosen adjustment thumbnail
        save_mode: "replace" (overwrite original) or "both" (save as new file alongside)

    Returns: {"saved": path}
    """
    # Get the adjustment image from thumbnails
    adj_filename = Path(adjustment_url).name
    adj_path = THUMBNAIL_DIR / adj_filename

    if not adj_path.exists():
        return {"error": "Adjustment file not found"}

    # Load the adjustment at full resolution from original
    orig = Image.open(filepath).convert("RGB")
    adj_preview = Image.open(str(adj_path)).convert("RGB")

    # Determine which adjustment was chosen and re-apply at full resolution
    if "_adj1" in str(adj_filename):
        full_adj = _auto_balance(orig)
    elif "_adj2" in str(adj_filename):
        full_adj = _enhanced_contrast(orig)
    elif "_adj3" in str(adj_filename):
        full_adj = _vivid_style(orig)
    else:
        return {"error": "Unknown adjustment"}

    orig_path = Path(filepath)

    if save_mode == "replace":
        output_path = orig_path
        full_adj.save(str(output_path), quality=95)
        return {"saved": str(output_path), "mode": "replaced"}
    else:
        # Save alongside with suffix
        stem = orig_path.stem
        suffix = orig_path.suffix
        output_path = orig_path.parent / f"{stem}_adjusted{suffix}"
        full_adj.save(str(output_path), quality=95)
        return {"saved": str(output_path), "mode": "saved_copy"}

"""
Fovea - iCloud Photos Library Integration

Reads photo library data exported by the native Swift app via PhotoKit.
The Swift layer handles permission (shows native "Allow Photos Access" dialog)
and exports metadata to ~/.fovea/data/photos_library.json.

No osxphotos needed. No Full Disk Access needed.
"""

import json
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from config import DATA_DIR

log = logging.getLogger(__name__)

PHOTOS_CACHE = DATA_DIR / "photos_library.json"

_cache = None
_cache_mtime = 0


def _load_cache() -> Optional[dict]:
    """Load the photo library cache exported by the Swift app."""
    global _cache, _cache_mtime

    if not PHOTOS_CACHE.exists():
        return None

    mtime = PHOTOS_CACHE.stat().st_mtime
    if _cache is not None and mtime == _cache_mtime:
        return _cache

    try:
        with open(PHOTOS_CACHE) as f:
            _cache = json.load(f)
            _cache_mtime = mtime
            return _cache
    except Exception as e:
        log.error(f"Failed to load photos cache: {e}")
        return None


def get_library_status() -> dict:
    """Check if Photos library data is available."""
    data = _load_cache()
    if data:
        return {
            "available": True,
            "photo_count": data.get("photo_count", 0),
            "album_count": data.get("album_count", 0),
        }
    return {
        "available": False,
        "error": "Photos library not loaded",
        "hint": "Reopen Fovea — it will ask for Photos access permission on startup.",
    }


def get_albums() -> list:
    """List all albums."""
    data = _load_cache()
    if not data:
        return []

    albums = data.get("albums", [])
    # Sort by count descending
    albums.sort(key=lambda a: -a.get("count", 0))
    return albums


def get_photos(
    album: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    sort_by: str = "date_desc",
) -> dict:
    """Get photos from the library."""
    data = _load_cache()
    if not data:
        return {"photos": [], "total": 0}

    photos = data.get("photos", [])

    # Filter by album (basic - just by name match since we don't have per-album photo lists in the cache)
    # TODO: enhance Swift export to include per-album photo UUIDs

    # Sort
    if sort_by == "date_desc":
        photos = sorted(photos, key=lambda p: p.get("date", ""), reverse=True)
    elif sort_by == "date_asc":
        photos = sorted(photos, key=lambda p: p.get("date", ""))

    total = len(photos)
    photos = photos[offset:offset + limit]

    return {"photos": photos, "total": total}


def get_photo_path(uuid: str) -> Optional[str]:
    """
    Get the file path for a photo by UUID.
    Note: PhotoKit doesn't directly expose file paths.
    For serving images, we'd need to use PHImageManager in Swift.
    For now, return None and use the /api/library/photo endpoint
    which serves via PhotoKit in Swift.
    """
    return None


def get_cleanup_suggestions(limit: int = 500) -> dict:
    """
    Suggest photos for cleanup based on metadata.
    Uses data from PhotoKit export.
    """
    data = _load_cache()
    if not data:
        return {"suggestions": [], "total_reviewed": 0, "error": "Photos library not loaded"}

    photos = data.get("photos", [])
    suggestions = []

    for p in photos[:limit]:
        reasons = []
        confidence = 0

        # Screenshots
        if p.get("is_screenshot"):
            reasons.append("screenshot")
            confidence = max(confidence, 0.6)

        # Burst photos (not the representative)
        if p.get("burst_id") and not p.get("is_burst"):
            reasons.append("burst_not_selected")
            confidence = max(confidence, 0.7)

        # Hidden photos
        if p.get("is_hidden"):
            reasons.append("hidden")
            confidence = max(confidence, 0.5)

        if reasons:
            suggestions.append({
                "uuid": p.get("uuid", ""),
                "filename": p.get("filename", "unknown"),
                "date": p.get("date"),
                "reasons": reasons,
                "reason_text": _reason_text(reasons),
                "confidence": confidence,
                "width": p.get("width"),
                "height": p.get("height"),
            })

    suggestions.sort(key=lambda s: -s["confidence"])
    return {"suggestions": suggestions, "total_reviewed": min(limit, len(photos))}


def _reason_text(reasons: list) -> str:
    mapping = {
        "screenshot": "Screenshot",
        "burst_not_selected": "Burst (not selected)",
        "hidden": "Hidden",
        "blurry": "Blurry",
        "overexposed": "Overexposed",
        "duplicate": "Duplicate",
    }
    return " / ".join(mapping.get(r, r) for r in reasons)

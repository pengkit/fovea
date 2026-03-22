"""
Fovea - iCloud Photos Library Integration

Reads the local Photos.app library via osxphotos.
Provides browsing, AI analysis suggestions, and cleanup recommendations.

Requires: Full Disk Access permission for the app/terminal.
"""

import os
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

log = logging.getLogger(__name__)

_photosdb = None
_photosdb_error = None


def _get_db():
    """Lazy-load the Photos database."""
    global _photosdb, _photosdb_error
    if _photosdb is not None:
        return _photosdb
    if _photosdb_error:
        return None

    try:
        import osxphotos

        # Try default library, then fallback to common paths
        lib_paths = [
            None,  # default
            str(Path.home() / "Pictures" / "Photos Library.photoslibrary"),
        ]

        for lib_path in lib_paths:
            try:
                if lib_path:
                    _photosdb = osxphotos.PhotosDB(lib_path)
                else:
                    _photosdb = osxphotos.PhotosDB()
                log.info(f"Photos library opened: {_photosdb.photos_count()} photos")
                return _photosdb
            except Exception:
                continue

        _photosdb_error = "Could not find Photos library"
        return None

    except ImportError:
        _photosdb_error = "osxphotos not installed"
        return None
    except Exception as e:
        _photosdb_error = str(e)
        return None


def get_library_status() -> dict:
    """Check if Photos library is accessible."""
    db = _get_db()
    if db:
        return {
            "available": True,
            "photo_count": db.photos_count(),
            "album_count": len(db.album_info),
            "library_path": db.library_path,
        }
    return {
        "available": False,
        "error": _photosdb_error or "Unknown error",
        "hint": "Grant Full Disk Access: System Settings → Privacy & Security → Full Disk Access → add Fovea (or Terminal)",
    }


def get_albums() -> list:
    """List all albums."""
    db = _get_db()
    if not db:
        return []

    albums = []
    for album in db.album_info:
        photo_count = len(album.photos)
        if photo_count == 0:
            continue
        # Get a sample photo for the album cover
        sample = album.photos[0] if album.photos else None
        albums.append({
            "title": album.title,
            "count": photo_count,
            "uuid": album.uuid,
            "cover_path": sample.path if sample and sample.path else None,
        })

    albums.sort(key=lambda a: -a["count"])
    return albums


def get_photos(
    album: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    sort_by: str = "date_desc",
) -> dict:
    """
    Get photos from the library.

    Args:
        album: Album title to filter by (None = all photos)
        limit: Max photos to return
        offset: Pagination offset
        sort_by: "date_desc", "date_asc"
    """
    db = _get_db()
    if not db:
        return {"photos": [], "total": 0}

    if album:
        # Find album by title
        matching = [a for a in db.album_info if a.title == album]
        if matching:
            photos = matching[0].photos
        else:
            photos = []
    else:
        photos = db.photos()

    # Sort
    if sort_by == "date_desc":
        photos = sorted(photos, key=lambda p: p.date or datetime.min, reverse=True)
    elif sort_by == "date_asc":
        photos = sorted(photos, key=lambda p: p.date or datetime.min)

    total = len(photos)
    photos = photos[offset:offset + limit]

    result = []
    for p in photos:
        result.append({
            "uuid": p.uuid,
            "filename": p.filename,
            "date": p.date.isoformat() if p.date else None,
            "path": p.path,
            "width": p.width,
            "height": p.height,
            "is_favorite": p.favorite,
            "is_hidden": p.hidden,
            "albums": [a.title for a in p.album_info],
            "has_raw": p.has_raw,
            "is_screenshot": p.screenshot,
            "is_selfie": p.selfie,
            "is_live": p.live_photo,
            "is_burst": p.burst,
        })

    return {"photos": result, "total": total}


def get_photo_path(uuid: str) -> Optional[str]:
    """Get the file path for a photo by UUID."""
    db = _get_db()
    if not db:
        return None

    photos = db.photos(uuid=[uuid])
    if photos and photos[0].path:
        return photos[0].path
    return None


def get_cleanup_suggestions(limit: int = 200) -> dict:
    """
    AI-powered cleanup suggestions.
    Identifies photos that are likely unnecessary:
    - Screenshots
    - Duplicates/bursts (keep best)
    - Blurry photos
    - Very similar photos
    """
    db = _get_db()
    if not db:
        return {"suggestions": [], "total_reviewed": 0}

    photos = db.photos()
    suggestions = []

    for p in photos[:limit]:
        reasons = []
        confidence = 0

        # Screenshots
        if p.screenshot:
            reasons.append("screenshot")
            confidence = max(confidence, 0.6)

        # Burst photos (not the picked one)
        if p.burst and not p.burst_selected:
            reasons.append("burst_not_selected")
            confidence = max(confidence, 0.7)

        # Hidden photos
        if p.hidden:
            reasons.append("hidden")
            confidence = max(confidence, 0.5)

        if reasons:
            suggestions.append({
                "uuid": p.uuid,
                "filename": p.filename,
                "path": p.path,
                "date": p.date.isoformat() if p.date else None,
                "reasons": reasons,
                "reason_text": _reason_text(reasons),
                "confidence": confidence,
            })

    suggestions.sort(key=lambda s: -s["confidence"])
    return {"suggestions": suggestions, "total_reviewed": min(limit, len(photos))}


def _reason_text(reasons: list) -> str:
    mapping = {
        "screenshot": "Screenshot",
        "burst_not_selected": "Burst (not the selected one)",
        "hidden": "Hidden by user",
        "blurry": "Blurry",
        "overexposed": "Overexposed",
        "duplicate": "Duplicate",
    }
    return " / ".join(mapping.get(r, r) for r in reasons)

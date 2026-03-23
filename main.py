"""Fovea - FastAPI Application"""

import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
import os
from fastapi.responses import FileResponse, JSONResponse

from config import STATIC_DIR, THUMBNAIL_DIR, DEFAULT_DESTINATION
from models import ImportRequest
from scanner import list_volumes, list_destinations, scan_volume
from importer import import_files, get_progress, preview_import
from converter import get_dng_info
from library import get_library_status, get_albums, get_photos, get_photo_path, get_cleanup_suggestions
from adjustments import generate_adjustments, save_chosen_adjustment


@asynccontextmanager
async def lifespan(app: FastAPI):
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_DESTINATION.mkdir(parents=True, exist_ok=True)
    yield

app = FastAPI(title="Fovea", version="2.0.0", lifespan=lifespan)

# 静态文件
app.mount("/thumbnails", StaticFiles(directory=str(THUMBNAIL_DIR)), name="thumbnails")


# === 页面 ===

@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# === DNG Converter 状态 ===

@app.get("/api/dng/status")
async def api_dng_status():
    return get_dng_info()


# === 扫描 API ===

@app.get("/api/volumes")
async def api_list_volumes():
    volumes = list_volumes()
    return {"volumes": [v.model_dump() for v in volumes]}


@app.get("/api/destinations")
async def api_list_destinations():
    destinations = list_destinations()
    return {
        "destinations": [d.model_dump() for d in destinations],
        "default": str(DEFAULT_DESTINATION),
    }


@app.get("/api/scan")
async def api_scan(source: str, thumbs: bool = True):
    result = await asyncio.to_thread(scan_volume, source, thumbs)
    return result.model_dump()


# === 导入 API ===

@app.post("/api/import/preview")
async def api_import_preview(request: ImportRequest):
    preview = await asyncio.to_thread(preview_import, request)
    return {"preview": preview}


@app.post("/api/import")
async def api_import(request: ImportRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(import_files, request)
    return {"status": "started", "total": len(request.file_paths)}


@app.get("/api/import/progress")
async def api_import_progress():
    progress = get_progress()
    return progress.model_dump()


# === Photos Library API ===

@app.get("/api/library/status")
async def api_library_status():
    return await asyncio.to_thread(get_library_status)


@app.get("/api/library/albums")
async def api_library_albums():
    return {"albums": await asyncio.to_thread(get_albums)}


@app.get("/api/library/photos")
async def api_library_photos(album: str = None, limit: int = 100, offset: int = 0):
    return await asyncio.to_thread(get_photos, album, limit, offset)


@app.get("/api/library/photo")
async def api_library_photo(uuid: str):
    """Get raw image file for a photo (serve the actual file)."""
    path = await asyncio.to_thread(get_photo_path, uuid)
    if path and os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "Photo not found"}, status_code=404)


@app.get("/api/library/cleanup")
async def api_library_cleanup(limit: int = 200):
    return await asyncio.to_thread(get_cleanup_suggestions, limit)


# === Adjustments API ===

@app.get("/api/adjust")
async def api_adjust(path: str):
    """Generate 3 auto-adjustment variants for a photo."""
    return await asyncio.to_thread(generate_adjustments, path)


@app.post("/api/adjust/save")
async def api_adjust_save(filepath: str, adjustment_url: str, mode: str = "both", rotation: int = 0):
    return await asyncio.to_thread(save_chosen_adjustment, filepath, adjustment_url, mode, rotation)


@app.post("/api/adjust/revert")
async def api_adjust_revert(filepath: str):
    """Revert to original by restoring from backup."""
    from adjustments import revert_adjustment
    return await asyncio.to_thread(revert_adjustment, filepath)


# === 时间轴 API ===

@app.get("/api/timeline")
async def api_timeline(offset: int = 0, limit: int = 60):
    """Return all photos in Fovea library as a flat timeline, sorted newest first."""
    import datetime
    from urllib.parse import quote as urlquote

    root = DEFAULT_DESTINATION
    if not root.exists():
        return {"photos": [], "total": 0, "has_more": False}

    IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.tif', '.tiff',
                  '.dng', '.arw', '.cr2', '.cr3', '.nef', '.raf', '.rw2'}

    photos = []
    for f in root.rglob('*'):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS and not f.name.startswith('.'):
            st = f.stat()
            photos.append({
                "name": f.name,
                "path": str(f),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "date": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
                "folder": str(f.parent.relative_to(root)),
                "thumb_url": "/api/thumb?path=" + urlquote(str(f)),
            })

    # Sort newest first
    photos.sort(key=lambda x: x["mtime"], reverse=True)
    total = len(photos)
    page = photos[offset:offset + limit]

    return {"photos": page, "total": total, "has_more": offset + limit < total}


# === Trash API (soft delete with 30-day retention) ===

TRASH_DIR = THUMBNAIL_DIR.parent / "trash"
TRASH_MANIFEST = TRASH_DIR / "manifest.json"


def _load_trash_manifest():
    import json
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    if TRASH_MANIFEST.exists():
        try:
            return json.loads(TRASH_MANIFEST.read_text())
        except Exception:
            pass
    return []


def _save_trash_manifest(items):
    import json
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    TRASH_MANIFEST.write_text(json.dumps(items, ensure_ascii=False, indent=2))


def _purge_expired():
    """Auto-delete items older than 30 days."""
    import time
    items = _load_trash_manifest()
    now = time.time()
    keep, remove = [], []
    for item in items:
        age_days = (now - item["deleted_at_ts"]) / 86400
        if age_days > 30:
            remove.append(item)
        else:
            keep.append(item)
    for item in remove:
        trash_file = TRASH_DIR / item["trash_filename"]
        if trash_file.exists():
            trash_file.unlink()
    if remove:
        _save_trash_manifest(keep)
    return len(remove)


@app.post("/api/trash/delete")
async def api_trash_delete(path: str):
    """Soft delete: move file to Fovea trash with metadata."""
    import shutil, time
    p = Path(path)
    if not p.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)

    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    items = _load_trash_manifest()

    # Generate unique trash filename
    trash_name = p.name
    counter = 1
    while (TRASH_DIR / trash_name).exists():
        trash_name = f"{p.stem}_{counter}{p.suffix}"
        counter += 1

    # Move file to trash
    shutil.move(str(p), str(TRASH_DIR / trash_name))

    items.append({
        "original_path": str(p),
        "filename": p.name,
        "trash_filename": trash_name,
        "deleted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "deleted_at_ts": time.time(),
    })
    _save_trash_manifest(items)

    return {"deleted": str(p), "trash_filename": trash_name}


@app.get("/api/trash/list")
async def api_trash_list():
    """List items in trash with remaining days."""
    import time
    _purge_expired()
    items = _load_trash_manifest()
    now = time.time()
    result = []
    for item in items:
        age_days = (now - item["deleted_at_ts"]) / 86400
        remaining = max(0, 30 - age_days)
        thumb_path = TRASH_DIR / item["trash_filename"]
        result.append({
            **item,
            "remaining_days": round(remaining, 1),
            "thumb_url": f"/api/thumb?path={thumb_path}" if thumb_path.exists() else None,
        })
    return {"items": result, "total": len(result)}


@app.post("/api/trash/restore")
async def api_trash_restore(trash_filename: str, mode: str = "skip"):
    """Restore file from trash. mode: 'skip' or 'overwrite'."""
    import shutil
    items = _load_trash_manifest()
    item = next((i for i in items if i["trash_filename"] == trash_filename), None)
    if not item:
        return JSONResponse({"error": "Item not found in trash"}, status_code=404)

    trash_file = TRASH_DIR / item["trash_filename"]
    if not trash_file.exists():
        items.remove(item)
        _save_trash_manifest(items)
        return JSONResponse({"error": "File missing from trash"}, status_code=404)

    dest = Path(item["original_path"])
    if dest.exists():
        if mode == "skip":
            return {"skipped": True, "reason": "File already exists", "path": str(dest)}
        # overwrite: remove existing
        dest.unlink()

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(trash_file), str(dest))
    items.remove(item)
    _save_trash_manifest(items)

    return {"restored": str(dest)}


@app.post("/api/trash/empty")
async def api_trash_empty():
    """Permanently delete all items in trash."""
    items = _load_trash_manifest()
    deleted = 0
    for item in items:
        trash_file = TRASH_DIR / item["trash_filename"]
        if trash_file.exists():
            trash_file.unlink()
            deleted += 1
    _save_trash_manifest([])
    return {"deleted": deleted}


# === 文件浏览 API ===

@app.get("/api/browse")
async def api_browse(path: str):
    p = Path(path)
    if not p.exists() or not p.is_dir():
        return JSONResponse({"error": "目录不存在"}, status_code=404)

    IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.tif', '.tiff',
                  '.dng', '.arw', '.cr2', '.cr3', '.nef', '.raf', '.rw2', '.orf', '.pef'}
    items = []
    try:
        for item in sorted(p.iterdir()):
            if item.name.startswith("."):
                continue
            info = {
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else None,
            }
            if item.is_file() and item.suffix.lower() in IMAGE_EXTS:
                info["thumb_url"] = f"/api/thumb?path={item}"
            items.append(info)
    except PermissionError:
        return JSONResponse({"error": "权限不足"}, status_code=403)

    return {"path": str(p), "items": items}


@app.get("/api/thumb")
async def api_thumb(path: str):
    """Generate and serve a thumbnail for a local image file."""
    import hashlib
    from PIL import Image
    import io

    src = Path(path)
    if not src.exists() or not src.is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)

    # Cache key based on path + mtime
    cache_key = hashlib.md5(f"{src}:{src.stat().st_mtime}".encode()).hexdigest()
    cache_path = THUMBNAIL_DIR / f"{cache_key}.jpg"

    if cache_path.exists():
        return FileResponse(str(cache_path), media_type="image/jpeg",
                           headers={"Cache-Control": "no-store"})

    # Generate thumbnail — Core Image handles EXIF orientation natively
    try:
        img = await asyncio.to_thread(_make_thumbnail, src)
        img.save(str(cache_path), "JPEG", quality=80)
        return FileResponse(str(cache_path), media_type="image/jpeg",
                           headers={"Cache-Control": "no-store"})
    except Exception:
        return JSONResponse({"error": "Cannot generate thumbnail"}, status_code=500)


RAW_EXTENSIONS = {'.arw', '.cr2', '.cr3', '.nef', '.raf', '.rw2', '.orf', '.pef', '.dng'}
SWIFT_THUMB_PORT = 9998  # ThumbnailServer in Swift
_last_exif_bytes = None  # Temp storage for EXIF data between _make_thumbnail and save


def _make_thumbnail(src: Path):
    """Generate thumbnail with correct EXIF orientation.

    Key insight: CIImage does NOT auto-apply EXIF orientation for JPEG.
    PIL's ImageOps.exif_transpose() is the reliable way to handle orientation.
    We create a clean new image at the end to strip ALL metadata, preventing
    any browser double-rotation from residual EXIF data.
    """
    from PIL import Image, ImageOps
    THUMB_SIZE = (300, 300)
    ext = src.suffix.lower()

    if ext in RAW_EXTENSIONS:
        # Swift Core Image for RAW rendering
        img = _render_raw_via_swift(src, max_width=400)
        if img is None:
            try:
                import rawpy
                with rawpy.imread(str(src)) as raw:
                    rgb = raw.postprocess(use_camera_wb=True, half_size=True)
                img = Image.fromarray(rgb)
            except (ImportError, Exception):
                img = Image.open(src)
    else:
        img = Image.open(src)

    # Rotate pixels per EXIF orientation tag
    img = ImageOps.exif_transpose(img) or img

    img.thumbnail(THUMB_SIZE, Image.LANCZOS)

    # Create a CLEAN new image — zero metadata, zero EXIF, zero risk of
    # browser seeing a stale orientation tag and double-rotating
    clean = Image.new('RGB', img.size)
    clean.paste(img.convert('RGB'))
    return clean


def _render_raw_via_swift(src: Path, max_width: int = 2000, preset: str = "default"):
    """Call Swift ThumbnailServer to render RAW via Core Image."""
    from PIL import Image
    import urllib.request
    import urllib.parse
    import io
    try:
        encoded_path = urllib.parse.quote(str(src))
        url = f"http://127.0.0.1:{SWIFT_THUMB_PORT}/raw?path={encoded_path}&w={max_width}&preset={preset}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
        return Image.open(io.BytesIO(data))
    except Exception:
        return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

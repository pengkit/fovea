"""Fovea - FastAPI Application"""

import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from config import STATIC_DIR, THUMBNAIL_DIR, DEFAULT_DESTINATION
from models import ImportRequest, AnalysisRequest, DescribeRequest
from scanner import list_volumes, list_destinations, scan_volume
from importer import import_files, get_progress, preview_import
from analyzer import run_analysis, get_analysis_state, get_analysis_results, get_daemon, describe_single
from converter import get_dng_info


@asynccontextmanager
async def lifespan(app: FastAPI):
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
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


# === 分析 API (unified) ===

@app.post("/api/analyze")
async def api_analyze(request: AnalysisRequest):
    """手动触发：扫描目录并加入分析队列"""
    run_analysis(request.directory)
    return {"status": "enqueued"}


@app.get("/api/analyze/state")
async def api_analyze_state():
    """后台分析状态（进度、pending 等）"""
    return get_analysis_state()


@app.get("/api/analyze/results")
async def api_analyze_results():
    """获取聚合分析结果"""
    return await asyncio.to_thread(get_analysis_results)


@app.post("/api/analyze/pause")
async def api_analyze_pause():
    get_daemon().pause()
    return {"status": "paused"}


@app.post("/api/analyze/resume")
async def api_analyze_resume():
    get_daemon().resume()
    return {"status": "resumed"}


@app.post("/api/analyze/stop")
async def api_analyze_stop():
    get_daemon().stop()
    return {"status": "stopped"}


@app.post("/api/describe")
async def api_describe(request: DescribeRequest):
    """Tier 2: 对单张照片调用本地 VLM 生成详细描述"""
    result = await asyncio.to_thread(describe_single, request.filepath)
    return {"description": result}


# === 文件浏览 API ===

@app.get("/api/browse")
async def api_browse(path: str):
    p = Path(path)
    if not p.exists() or not p.is_dir():
        return JSONResponse({"error": "目录不存在"}, status_code=404)

    items = []
    try:
        for item in sorted(p.iterdir()):
            if item.name.startswith("."):
                continue
            items.append({
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else None,
            })
    except PermissionError:
        return JSONResponse({"error": "权限不足"}, status_code=403)

    return {"path": str(p), "items": items}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

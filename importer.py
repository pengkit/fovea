"""Fovea - Smart File Importer"""

import os
import json
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

from config import DATA_DIR, ORGANIZE_PATTERN, RAW_EXTENSIONS
from models import ImportRequest, ImportProgress
from scanner import file_hash, extract_exif
from converter import convert_to_dng


# 全局导入进度
_import_progress = ImportProgress()


def get_progress() -> ImportProgress:
    return _import_progress


def _load_history() -> dict:
    history_file = DATA_DIR / "import_history.json"
    if history_file.exists():
        with open(history_file) as f:
            return json.load(f)
    return {"imported_hashes": [], "imported_files": []}


def _save_history(history: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    history_file = DATA_DIR / "import_history.json"
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2, default=str)


def _get_file_date(filepath: str) -> Optional[datetime]:
    """获取文件的拍摄日期，优先从 EXIF，其次从文件修改时间"""
    ext = Path(filepath).suffix.lower()
    if ext in (".jpg", ".jpeg"):
        exif = extract_exif(filepath)
        if exif.get("date_taken"):
            return exif["date_taken"]

    # 尝试配对的 JPEG
    stem = Path(filepath).stem
    parent = Path(filepath).parent
    for jpg_ext in (".jpg", ".JPG", ".jpeg", ".JPEG"):
        jpg_path = parent / (stem + jpg_ext)
        if jpg_path.exists():
            exif = extract_exif(str(jpg_path))
            if exif.get("date_taken"):
                return exif["date_taken"]

    # 使用文件修改时间
    try:
        mtime = os.path.getmtime(filepath)
        return datetime.fromtimestamp(mtime)
    except OSError:
        return datetime.now()


def _build_dest_path(
    filepath: str,
    destination: str,
    organize_by: str,
    event_name: Optional[str],
    raw_subfolder: bool,
) -> Path:
    """构建目标文件路径"""
    date = _get_file_date(filepath)
    ext = Path(filepath).suffix.lower()
    filename = Path(filepath).name

    if organize_by == "date":
        if date:
            subdir = ORGANIZE_PATTERN.format(
                year=date.year, month=date.month, day=date.day
            )
        else:
            subdir = "未知日期"
    elif organize_by == "event" and event_name:
        if date:
            subdir = f"{date.year}/{date.month:02d}/{event_name}"
        else:
            subdir = event_name
    else:
        subdir = "未分类"

    dest = Path(destination) / subdir

    # RAW 文件单独放子目录
    if raw_subfolder and ext in RAW_EXTENSIONS:
        dest = dest / "RAW"

    return dest / filename


def _safe_copy(src: str, dst: Path) -> bool:
    """安全复制文件，避免覆盖，并验证完整性"""
    dst.parent.mkdir(parents=True, exist_ok=True)

    # 如果目标已存在，添加序号
    if dst.exists():
        stem = dst.stem
        suffix = dst.suffix
        counter = 1
        while dst.exists():
            dst = dst.parent / f"{stem}_{counter}{suffix}"
            counter += 1

    # 复制文件
    shutil.copy2(src, dst)

    # 验证: 比较大小
    src_size = os.path.getsize(src)
    dst_size = os.path.getsize(str(dst))
    if src_size != dst_size:
        os.remove(str(dst))
        return False

    return True


def import_files(request: ImportRequest) -> ImportProgress:
    """执行文件导入"""
    global _import_progress

    _import_progress = ImportProgress(
        total=len(request.file_paths),
        status="running",
    )

    history = _load_history()
    imported_hashes = set(history.get("imported_hashes", []))
    new_hashes = []
    new_files = []

    for i, filepath in enumerate(request.file_paths):
        _import_progress.current_file = Path(filepath).name
        _import_progress.completed = i

        try:
            # 跳过重复 — 只有目标文件确实存在时才跳过
            if request.skip_duplicates:
                fh = file_hash(filepath)
                if fh in imported_hashes:
                    # Verify the file actually exists at destination
                    dest_check = _build_dest_path(
                        filepath, request.destination_path,
                        request.organize_by, request.event_name,
                        request.raw_subfolder,
                    )
                    if dest_check.exists():
                        continue
                    # File hash recorded but destination missing — re-import

            # 构建目标路径
            dest_path = _build_dest_path(
                filepath,
                request.destination_path,
                request.organize_by,
                request.event_name,
                request.raw_subfolder,
            )

            ext = Path(filepath).suffix.lower()
            final_dest = None

            # DNG 转换: RAW 文件转为 DNG 格式
            if request.convert_to_dng and ext in RAW_EXTENSIONS and ext != ".dng":
                _import_progress.current_file = f"Converting {Path(filepath).name} → DNG"
                dng_output_dir = str(dest_path.parent)
                dng_path = convert_to_dng(
                    filepath, dng_output_dir,
                    compressed=request.dng_compressed,
                    embed_original=request.dng_embed_original,
                )
                if dng_path:
                    final_dest = dng_path
                else:
                    # DNG 转换失败，回退为直接复制原始 RAW
                    _import_progress.errors.append(
                        f"DNG conversion failed, copying original: {Path(filepath).name}"
                    )
                    if _safe_copy(filepath, dest_path):
                        final_dest = str(dest_path)
            else:
                # 非 RAW 或未开启 DNG 转换，直接复制
                if _safe_copy(filepath, dest_path):
                    final_dest = str(dest_path)

            if final_dest:
                fh = file_hash(filepath)
                new_hashes.append(fh)
                new_files.append({
                    "source": filepath,
                    "destination": final_dest,
                    "converted_to_dng": request.convert_to_dng and ext in RAW_EXTENSIONS and ext != ".dng",
                    "hash": fh,
                    "imported_at": datetime.now().isoformat(),
                })
                _import_progress.imported_files.append(final_dest)
            else:
                _import_progress.errors.append(f"导入失败: {filepath}")

        except Exception as e:
            _import_progress.errors.append(f"{filepath}: {str(e)}")

    # 更新导入历史
    history["imported_hashes"] = list(imported_hashes | set(new_hashes))
    history.setdefault("imported_files", []).extend(new_files)
    _save_history(history)

    _import_progress.completed = len(request.file_paths)
    _import_progress.status = "completed" if not _import_progress.errors else "completed_with_errors"
    _import_progress.current_file = ""

    return _import_progress


def preview_import(request: ImportRequest) -> list[dict]:
    """预览导入结果 - 显示每个文件将被放到哪里"""
    preview = []
    for filepath in request.file_paths:
        dest = _build_dest_path(
            filepath,
            request.destination_path,
            request.organize_by,
            request.event_name,
            request.raw_subfolder,
        )
        preview.append({
            "source": filepath,
            "destination": str(dest),
            "filename": Path(filepath).name,
            "size": os.path.getsize(filepath) if os.path.exists(filepath) else 0,
        })
    return preview

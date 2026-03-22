"""Fovea - Camera/SD Card Scanner"""

import os
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional
from PIL import Image
from PIL.ExifTags import TAGS
import json

from config import (
    VOLUME_PATHS, RAW_EXTENSIONS, JPEG_EXTENSIONS, VIDEO_EXTENSIONS,
    SIDECAR_EXTENSIONS, SYSTEM_FILES, SYSTEM_DIRS, CAMERA_BRANDS,
    THUMBNAIL_DIR, THUMBNAIL_SIZE, THUMBNAIL_QUALITY, DATA_DIR,
)
from models import (
    CameraBrand, FileType, CameraFile, ScanResult, VolumeInfo,
)


def get_import_history() -> set:
    """读取已导入文件的哈希记录"""
    history_file = DATA_DIR / "import_history.json"
    if history_file.exists():
        with open(history_file) as f:
            data = json.load(f)
            return set(data.get("imported_hashes", []))
    return set()


def file_hash(filepath: str, chunk_size: int = 8192) -> str:
    """计算文件的 MD5 哈希 (前 64KB 快速哈希)"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        # 只读前 64KB 做快速指纹，足够判断重复
        data = f.read(65536)
        h.update(data)
    # 追加文件大小作为额外指纹
    h.update(str(os.path.getsize(filepath)).encode())
    return h.hexdigest()


def detect_file_type(ext: str) -> FileType:
    """根据扩展名判断文件类型"""
    ext = ext.lower()
    if ext in RAW_EXTENSIONS:
        return FileType.RAW
    elif ext in JPEG_EXTENSIONS:
        return FileType.JPEG
    elif ext in VIDEO_EXTENSIONS:
        return FileType.VIDEO
    elif ext in SIDECAR_EXTENSIONS:
        return FileType.SIDECAR
    else:
        return FileType.SYSTEM


def detect_camera_brand(dcim_path: Path) -> CameraBrand:
    """通过 DCIM 子目录名识别相机品牌"""
    if not dcim_path.exists():
        return CameraBrand.UNKNOWN

    for subfolder in dcim_path.iterdir():
        if not subfolder.is_dir():
            continue
        name = subfolder.name.upper()
        for brand, info in CAMERA_BRANDS.items():
            for pattern in info["folder_patterns"]:
                if pattern.upper() in name:
                    return CameraBrand(brand)

    return CameraBrand.UNKNOWN


def is_system_file(filepath: Path) -> bool:
    """判断是否是相机系统文件"""
    if filepath.name.lower() in SYSTEM_FILES:
        return True
    # 检查是否在系统目录下
    for part in filepath.parts:
        if part.lower() in SYSTEM_DIRS:
            return True
    return False


def extract_exif(filepath: str) -> dict:
    """提取 JPEG 文件的 EXIF 信息"""
    info = {}
    try:
        with Image.open(filepath) as img:
            exif_data = img._getexif()
            if not exif_data:
                return info

            # 建立 tag name -> value 映射
            exif = {}
            for tag_id, value in exif_data.items():
                tag_name = TAGS.get(tag_id, tag_id)
                exif[tag_name] = value

            # 拍摄时间
            date_str = exif.get("DateTimeOriginal") or exif.get("DateTime")
            if date_str and isinstance(date_str, str):
                try:
                    info["date_taken"] = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass

            # 相机信息
            info["camera_model"] = exif.get("Model")
            info["lens"] = exif.get("LensModel")
            info["iso"] = exif.get("ISOSpeedRatings")

            # 快门速度
            exposure = exif.get("ExposureTime")
            if exposure:
                if hasattr(exposure, 'numerator'):
                    if exposure.numerator and exposure.denominator:
                        info["shutter_speed"] = f"{exposure.numerator}/{exposure.denominator}"
                else:
                    info["shutter_speed"] = str(exposure)

            # 光圈
            fnumber = exif.get("FNumber")
            if fnumber:
                if hasattr(fnumber, 'numerator') and fnumber.denominator:
                    info["aperture"] = float(fnumber.numerator) / float(fnumber.denominator)
                else:
                    try:
                        info["aperture"] = float(fnumber)
                    except (TypeError, ValueError):
                        pass

            # 焦距
            focal = exif.get("FocalLength")
            if focal:
                if hasattr(focal, 'numerator') and focal.denominator:
                    info["focal_length"] = f"{float(focal.numerator) / float(focal.denominator):.0f}mm"
                else:
                    info["focal_length"] = f"{focal}mm"

            # 尺寸
            width = exif.get("ExifImageWidth") or (img.width if img.width else None)
            height = exif.get("ExifImageHeight") or (img.height if img.height else None)
            if width and height:
                info["dimensions"] = f"{width}x{height}"

    except Exception:
        pass
    return info


def generate_thumbnail(filepath: str, file_type: FileType) -> Optional[str]:
    """生成缩略图，返回缩略图的相对URL路径"""
    try:
        THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        # 用文件哈希作为缩略图文件名
        fhash = hashlib.md5(filepath.encode()).hexdigest()
        thumb_path = THUMBNAIL_DIR / f"{fhash}.jpg"

        if thumb_path.exists():
            return f"/thumbnails/{fhash}.jpg"

        if file_type == FileType.JPEG:
            with Image.open(filepath) as img:
                img.thumbnail(THUMBNAIL_SIZE)
                img = img.convert("RGB")
                img.save(thumb_path, "JPEG", quality=THUMBNAIL_QUALITY)
                return f"/thumbnails/{fhash}.jpg"

        elif file_type == FileType.RAW:
            # 尝试用 rawpy 提取 RAW 内嵌的预览图
            try:
                import rawpy
                with rawpy.imread(filepath) as raw:
                    try:
                        thumb = raw.extract_thumb()
                        if thumb.format == rawpy.ThumbFormat.JPEG:
                            with open(thumb_path, "wb") as f:
                                f.write(thumb.data)
                            # 缩小到缩略图尺寸
                            with Image.open(thumb_path) as img:
                                img.thumbnail(THUMBNAIL_SIZE)
                                img.save(thumb_path, "JPEG", quality=THUMBNAIL_QUALITY)
                            return f"/thumbnails/{fhash}.jpg"
                        elif thumb.format == rawpy.ThumbFormat.BITMAP:
                            img = Image.fromarray(thumb.data)
                            img.thumbnail(THUMBNAIL_SIZE)
                            img = img.convert("RGB")
                            img.save(thumb_path, "JPEG", quality=THUMBNAIL_QUALITY)
                            return f"/thumbnails/{fhash}.jpg"
                    except rawpy.LibRawNoThumbnailError:
                        # 没有内嵌缩略图，做全尺寸处理
                        rgb = raw.postprocess(
                            half_size=True,
                            use_camera_wb=True,
                            no_auto_bright=False,
                        )
                        img = Image.fromarray(rgb)
                        img.thumbnail(THUMBNAIL_SIZE)
                        img.save(thumb_path, "JPEG", quality=THUMBNAIL_QUALITY)
                        return f"/thumbnails/{fhash}.jpg"
            except ImportError:
                pass  # rawpy 未安装

        elif file_type == FileType.VIDEO:
            # 视频缩略图 - 尝试用 ffmpeg
            try:
                import subprocess
                subprocess.run(
                    [
                        "ffmpeg", "-i", filepath, "-ss", "00:00:01",
                        "-vframes", "1", "-vf", f"scale={THUMBNAIL_SIZE[0]}:-1",
                        "-y", str(thumb_path),
                    ],
                    capture_output=True, timeout=10,
                )
                if thumb_path.exists():
                    return f"/thumbnails/{fhash}.jpg"
            except (ImportError, FileNotFoundError, subprocess.TimeoutExpired):
                pass

    except Exception:
        pass
    return None


def scan_volume(volume_path: str, generate_thumbs: bool = True) -> ScanResult:
    """扫描一个卷/SD卡，返回所有文件信息"""
    vol = Path(volume_path)
    dcim_path = vol / "DCIM"

    brand = detect_camera_brand(dcim_path) if dcim_path.exists() else CameraBrand.UNKNOWN

    result = ScanResult(
        source_path=str(vol),
        source_name=vol.name,
        camera_brand=brand,
    )

    import_history = get_import_history()
    files: list[CameraFile] = []

    # 遍历整个卷，但智能分类
    scan_root = dcim_path if dcim_path.exists() else vol

    for root, dirs, filenames in os.walk(scan_root):
        root_path = Path(root)

        # 跳过系统目录
        dirs[:] = [d for d in dirs if d.lower() not in SYSTEM_DIRS]

        for fname in filenames:
            filepath = root_path / fname
            ext = filepath.suffix.lower()

            # 跳过隐藏文件
            if fname.startswith("."):
                continue

            file_type = detect_file_type(ext)

            # 标记系统文件
            if is_system_file(filepath):
                file_type = FileType.SYSTEM

            try:
                size = filepath.stat().st_size
            except OSError:
                continue

            # 检查是否已导入
            fh = file_hash(str(filepath))
            already_imported = fh in import_history

            cf = CameraFile(
                path=str(filepath),
                filename=fname,
                file_type=file_type,
                size=size,
                camera_brand=brand,
                selected=file_type not in (FileType.SYSTEM, FileType.SIDECAR),
                already_imported=already_imported,
            )

            # 提取 EXIF (仅 JPEG)
            if file_type == FileType.JPEG:
                exif = extract_exif(str(filepath))
                cf.date_taken = exif.get("date_taken")
                cf.camera_model = exif.get("camera_model")
                cf.lens = exif.get("lens")
                cf.iso = exif.get("iso")
                cf.shutter_speed = exif.get("shutter_speed")
                cf.aperture = exif.get("aperture")
                cf.focal_length = exif.get("focal_length")
                cf.dimensions = exif.get("dimensions")

                if not result.camera_model and cf.camera_model:
                    result.camera_model = cf.camera_model

            # 生成缩略图
            if generate_thumbs and file_type in (FileType.RAW, FileType.JPEG, FileType.VIDEO):
                cf.thumbnail_url = generate_thumbnail(str(filepath), file_type)

            files.append(cf)

    # RAW-JPG 配对
    _pair_raw_jpeg(files)

    # 统计
    result.files = files
    result.total_files = len(files)
    result.raw_count = sum(1 for f in files if f.file_type == FileType.RAW)
    result.jpeg_count = sum(1 for f in files if f.file_type == FileType.JPEG)
    result.video_count = sum(1 for f in files if f.file_type == FileType.VIDEO)
    result.sidecar_count = sum(1 for f in files if f.file_type == FileType.SIDECAR)
    result.system_count = sum(1 for f in files if f.file_type == FileType.SYSTEM)
    result.total_size = sum(f.size for f in files)

    # 将 RAW 文件的 EXIF 信息从配对的 JPEG 文件继承
    _inherit_exif_for_raw(files)

    return result


def _pair_raw_jpeg(files: list[CameraFile]):
    """RAW/JPEG/Sidecar 配对 - 根据文件名（去掉扩展名）匹配"""
    by_stem: dict[str, list[CameraFile]] = {}
    for f in files:
        stem = Path(f.filename).stem.upper()
        by_stem.setdefault(stem, []).append(f)

    for stem, group in by_stem.items():
        raws = [f for f in group if f.file_type == FileType.RAW]
        jpgs = [f for f in group if f.file_type == FileType.JPEG]
        sidecars = [f for f in group if f.file_type == FileType.SIDECAR]

        # RAW <-> JPEG 配对
        if raws and jpgs:
            for r in raws:
                r.pair_file = jpgs[0].path
            for j in jpgs:
                j.pair_file = raws[0].path

        # Sidecar 跟随主文件: XMP 等元数据文件自动跟着 RAW 或 JPEG 走
        # 默认选中它们（如果有配对的照片）
        if sidecars and (raws or jpgs):
            for s in sidecars:
                s.pair_file = (raws[0] if raws else jpgs[0]).path
                s.selected = True  # 有配对照片时，sidecar 跟着走


def _inherit_exif_for_raw(files: list[CameraFile]):
    """RAW 文件从配对的 JPEG 继承 EXIF 信息"""
    jpeg_map = {f.path: f for f in files if f.file_type == FileType.JPEG}
    for f in files:
        if f.file_type == FileType.RAW and f.pair_file and f.pair_file in jpeg_map:
            jpg = jpeg_map[f.pair_file]
            if not f.date_taken:
                f.date_taken = jpg.date_taken
            if not f.camera_model:
                f.camera_model = jpg.camera_model
            if not f.lens:
                f.lens = jpg.lens
            if not f.iso:
                f.iso = jpg.iso
            if not f.shutter_speed:
                f.shutter_speed = jpg.shutter_speed
            if not f.aperture:
                f.aperture = jpg.aperture
            if not f.focal_length:
                f.focal_length = jpg.focal_length


def list_volumes() -> list[VolumeInfo]:
    """列出所有可能是相机/SD卡的挂载卷"""
    volumes = []
    for vol_root in VOLUME_PATHS:
        vol_root = Path(vol_root)
        if not vol_root.exists():
            continue
        for item in vol_root.iterdir():
            if not item.is_dir():
                continue
            # 跳过 macOS 系统卷
            if item.name in ("Macintosh HD", "Macintosh HD - Data", "com.apple.TimeMachine.localsnapshots"):
                continue

            dcim = item / "DCIM"
            is_camera = dcim.exists() and dcim.is_dir()
            brand = detect_camera_brand(dcim) if is_camera else CameraBrand.UNKNOWN

            # 获取磁盘空间
            try:
                st = os.statvfs(str(item))
                total = st.f_blocks * st.f_frsize
                free = st.f_bavail * st.f_frsize
            except OSError:
                total = free = None

            volumes.append(VolumeInfo(
                path=str(item),
                name=item.name,
                is_camera=is_camera,
                camera_brand=brand,
                total_space=total,
                free_space=free,
            ))

    return volumes


def list_destinations() -> list[VolumeInfo]:
    """列出所有可用的导入目标（外置硬盘 + 本地目录）"""
    destinations = []

    # 本地 Pictures 目录
    pictures = Path.home() / "Pictures"
    if pictures.exists():
        try:
            st = os.statvfs(str(pictures))
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
        except OSError:
            total = free = None
        destinations.append(VolumeInfo(
            path=str(pictures),
            name="Pictures (本地)",
            total_space=total,
            free_space=free,
        ))

    # 外置硬盘
    for vol_root in VOLUME_PATHS:
        vol_root = Path(vol_root)
        if not vol_root.exists():
            continue
        for item in vol_root.iterdir():
            if not item.is_dir():
                continue
            if item.name in ("Macintosh HD", "Macintosh HD - Data", "com.apple.TimeMachine.localsnapshots"):
                continue
            # 排除相机 SD 卡 (有 DCIM)
            if (item / "DCIM").exists():
                continue
            try:
                st = os.statvfs(str(item))
                total = st.f_blocks * st.f_frsize
                free = st.f_bavail * st.f_frsize
            except OSError:
                total = free = None
            destinations.append(VolumeInfo(
                path=str(item),
                name=item.name,
                total_space=total,
                free_space=free,
            ))

    return destinations

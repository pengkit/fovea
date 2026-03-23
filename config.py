"""Fovea - Configuration"""

import os
from pathlib import Path

# === 路径配置 ===
BASE_DIR = Path(__file__).parent
FOVEA_HOME = Path(os.environ.get("FOVEA_HOME", Path.home() / "Library" / "Application Support" / "Fovea"))
DATA_DIR = Path(os.environ.get("FOVEA_DATA_DIR", FOVEA_HOME / "data"))
THUMBNAIL_DIR = Path(os.environ.get("FOVEA_THUMBNAIL_DIR", FOVEA_HOME / "thumbnails"))
STATIC_DIR = BASE_DIR / "static"

# macOS 外置卷挂载点
VOLUME_PATHS = [Path("/Volumes")]

# 默认导入目标
DEFAULT_DESTINATION = Path.home() / "Pictures" / "Fovea"

# === 文件扩展名分类 ===
RAW_EXTENSIONS = {
    ".arw", ".sr2", ".srf",       # Sony
    ".cr2", ".cr3",                # Canon
    ".nef", ".nrw",                # Nikon
    ".raf",                        # Fujifilm
    ".orf",                        # Olympus
    ".rw2",                        # Panasonic
    ".dng",                        # Adobe DNG / Leica / others
    ".pef",                        # Pentax
}

JPEG_EXTENSIONS = {".jpg", ".jpeg"}

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mts", ".m2ts", ".avi", ".avchd"}

SIDECAR_EXTENSIONS = {".xmp", ".thm"}

# 相机系统文件/目录 (不需要导出)
SYSTEM_FILES = {
    "autprint.mrk", "autprint.inf",
    "avindex.bdm", "avindex.bak",
    "movieobj.bdm", "movieobj.bak",
    "index.bdm", "index.bak",
    "avchdtn",
    ".ds_store", "thumbs.db",
    "wisdom",
}

SYSTEM_DIRS = {
    "avchd", "private", "misc", "canonmsc", "sonycard",
    "mp_root", "avf_info", "sony",
}

# === 相机品牌识别 ===
CAMERA_BRANDS = {
    "sony": {
        "folder_patterns": ["MSDCF", "SONYDSC", "SONY"],
        "file_prefixes": ["DSC", "_DSC"],
        "raw_ext": ".arw",
    },
    "canon": {
        "folder_patterns": ["CANON", "EOS", "100CANON"],
        "file_prefixes": ["IMG_", "_MG_", "MVI_"],
        "raw_ext": ".cr3",
    },
    "nikon": {
        "folder_patterns": ["NCD", "NIKON", "ND"],
        "file_prefixes": ["DSC_", "_DSC", "NKD_"],
        "raw_ext": ".nef",
    },
    "fujifilm": {
        "folder_patterns": ["FUJI", "100_FUJI"],
        "file_prefixes": ["DSCF", "DSCI"],
        "raw_ext": ".raf",
    },
    "olympus": {
        "folder_patterns": ["OLYMP", "100OLYMP"],
        "file_prefixes": ["P", "E"],
        "raw_ext": ".orf",
    },
    "panasonic": {
        "folder_patterns": ["PANA", "100PANA", "LUMIX"],
        "file_prefixes": ["P", "L"],
        "raw_ext": ".rw2",
    },
}

# === 导入目录模板 ===
# 支持变量: {year}, {month}, {day}, {camera}, {event}
ORGANIZE_PATTERN = "{year}/{month:02d}/{day:02d}"

# === 缩略图 ===
THUMBNAIL_SIZE = (300, 300)
THUMBNAIL_QUALITY = 80

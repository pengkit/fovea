"""Fovea - Data Models"""

from pydantic import BaseModel
from enum import Enum
from typing import Optional
from datetime import datetime


class CameraBrand(str, Enum):
    SONY = "sony"
    CANON = "canon"
    NIKON = "nikon"
    FUJIFILM = "fujifilm"
    OLYMPUS = "olympus"
    PANASONIC = "panasonic"
    UNKNOWN = "unknown"


class FileType(str, Enum):
    RAW = "raw"
    JPEG = "jpeg"
    VIDEO = "video"
    SIDECAR = "sidecar"
    SYSTEM = "system"


class CameraFile(BaseModel):
    path: str
    filename: str
    file_type: FileType
    size: int  # bytes
    date_taken: Optional[datetime] = None
    camera_brand: CameraBrand = CameraBrand.UNKNOWN
    camera_model: Optional[str] = None
    lens: Optional[str] = None
    iso: Optional[int] = None
    shutter_speed: Optional[str] = None
    aperture: Optional[float] = None
    focal_length: Optional[str] = None
    dimensions: Optional[str] = None  # "6000x4000"
    pair_file: Optional[str] = None  # RAW-JPG pairing
    thumbnail_url: Optional[str] = None
    selected: bool = True
    already_imported: bool = False


class ScanResult(BaseModel):
    source_path: str
    source_name: str
    camera_brand: CameraBrand
    camera_model: Optional[str] = None
    total_files: int = 0
    raw_count: int = 0
    jpeg_count: int = 0
    video_count: int = 0
    sidecar_count: int = 0
    system_count: int = 0
    total_size: int = 0  # bytes
    files: list[CameraFile] = []


class ImportRequest(BaseModel):
    source_path: str
    destination_path: str
    file_paths: list[str]  # 选中的文件路径
    organize_by: str = "date"  # date / camera / event
    event_name: Optional[str] = None
    raw_subfolder: bool = False  # RAW 单独放子目录
    skip_duplicates: bool = True
    convert_to_dng: bool = False  # RAW 转 DNG 格式
    dng_compressed: bool = True   # DNG 无损压缩
    dng_embed_original: bool = False  # DNG 内嵌原始 RAW


class ImportProgress(BaseModel):
    total: int = 0
    completed: int = 0
    current_file: str = ""
    status: str = "idle"  # idle / running / completed / error
    errors: list[str] = []
    imported_files: list[str] = []


class VolumeInfo(BaseModel):
    path: str
    name: str
    is_camera: bool = False
    camera_brand: CameraBrand = CameraBrand.UNKNOWN
    total_space: Optional[int] = None
    free_space: Optional[int] = None

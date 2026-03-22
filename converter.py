"""
Fovea - RAW to DNG Converter

Conversion backends (in priority order):
  1. dnglab     — Open-source Rust CLI, best quality & speed. Install: brew install dnglab
  2. Adobe DNG  — Free proprietary tool, excellent compatibility. Optional install.
  3. Native     — Pure Python (rawpy + our TIFF/DNG writer). No external dependency.

All produce standards-compliant DNG files readable by Apple Photos, Lightroom, etc.

Credits:
  - dnglab: https://github.com/dnglab/dnglab (LGPL-2.1)
  - rawpy/LibRaw: https://github.com/letmaik/rawpy (MIT / LGPL-2.1)
  - DNG spec: Adobe, royalty-free public specification
"""

import subprocess
import shutil
import logging
from pathlib import Path
from typing import Optional

from config import RAW_EXTENSIONS

log = logging.getLogger(__name__)

# Adobe DNG Converter paths (macOS)
ADOBE_PATHS = [
    "/Applications/Adobe DNG Converter.app/Contents/MacOS/Adobe DNG Converter",
    Path.home() / "Applications/Adobe DNG Converter.app/Contents/MacOS/Adobe DNG Converter",
]


# ============================================================
# Backend detection
# ============================================================

def _find_dnglab() -> Optional[str]:
    return shutil.which("dnglab")


def _find_adobe() -> Optional[str]:
    for p in ADOBE_PATHS:
        if Path(p).exists():
            return str(p)
    return shutil.which("Adobe DNG Converter")


def _has_rawpy() -> bool:
    try:
        import rawpy
        return True
    except ImportError:
        return False


def is_dng_available() -> bool:
    return bool(_find_dnglab() or _find_adobe() or _has_rawpy())


# ============================================================
# Unified convert API
# ============================================================

def convert_to_dng(
    input_path: str,
    output_dir: str,
    compressed: bool = True,
    embed_original: bool = False,
    **kwargs,
) -> Optional[str]:
    """
    Convert a RAW file to DNG using the best available backend.

    Priority: dnglab → Adobe DNG Converter → Native Python

    Returns: path to the output DNG file, or None on failure.
    """
    input_file = Path(input_path)
    ext = input_file.suffix.lower()

    if ext not in RAW_EXTENSIONS:
        return None
    if ext == ".dng":
        return input_path

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 1. dnglab (best)
    dnglab = _find_dnglab()
    if dnglab:
        result = _convert_dnglab(dnglab, input_path, output_dir, compressed, embed_original)
        if result:
            return result
        log.warning("dnglab failed for %s, trying next backend", input_file.name)

    # 2. Adobe DNG Converter
    adobe = _find_adobe()
    if adobe:
        result = _convert_adobe(adobe, input_path, output_dir, compressed, embed_original)
        if result:
            return result
        log.warning("Adobe DNG Converter failed for %s, trying native", input_file.name)

    # 3. Native Python
    if _has_rawpy():
        result = _convert_native(input_path, output_dir)
        if result:
            return result
        log.warning("Native conversion failed for %s", input_file.name)

    return None


# ============================================================
# Backend implementations
# ============================================================

def _convert_dnglab(
    binary: str, input_path: str, output_dir: str,
    compressed: bool, embed_original: bool,
) -> Optional[str]:
    """
    dnglab convert — open-source Rust DNG converter.
    https://github.com/dnglab/dnglab

    Supports: ARW, CR2, CR3, NEF, RAF, ORF, RW2, PEF, DNG, and more.
    """
    input_file = Path(input_path)
    output_file = Path(output_dir) / (input_file.stem + ".dng")

    cmd = [binary, "convert"]

    # Compression
    if compressed:
        cmd.extend(["--compression", "lossless"])
    else:
        cmd.extend(["--compression", "uncompressed"])

    # Embed original RAW
    if embed_original:
        cmd.append("--embed")

    # Crop mode: preserve active area
    cmd.extend(["--crop", "activearea"])

    # Input → Output
    cmd.extend([str(input_file), str(output_file)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if output_file.exists():
            log.info("dnglab: %s → %s", input_file.name, output_file.name)
            return str(output_file)
        log.debug("dnglab stderr: %s", result.stderr)
    except subprocess.TimeoutExpired:
        log.warning("dnglab timeout: %s", input_file.name)
    except Exception as e:
        log.debug("dnglab error: %s", e)

    return None


def _convert_adobe(
    binary: str, input_path: str, output_dir: str,
    compressed: bool, embed_original: bool,
) -> Optional[str]:
    """Adobe DNG Converter (free, proprietary)."""
    input_file = Path(input_path)
    output_dir_path = Path(output_dir)

    cmd = [binary]
    if compressed:
        cmd.append("-c")
    if embed_original:
        cmd.append("-e")
    cmd.extend(["-fl", "-dng1.6", "-cr16.0"])
    cmd.extend(["-d", str(output_dir_path)])
    cmd.append(str(input_file))

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        expected = output_dir_path / (input_file.stem + ".dng")
        if expected.exists():
            return str(expected)
        for f in output_dir_path.iterdir():
            if f.stem.upper() == input_file.stem.upper() and f.suffix.lower() == ".dng":
                return str(f)
    except Exception as e:
        log.debug("Adobe DNG Converter error: %s", e)

    return None


def _convert_native(input_path: str, output_dir: str) -> Optional[str]:
    """Pure Python fallback via rawpy + our DNG writer."""
    try:
        from dng_writer import native_convert
        return native_convert(input_path, output_dir)
    except Exception as e:
        log.debug("Native DNG error: %s", e)
        return None


# ============================================================
# Status info for API / UI
# ============================================================

def get_dng_info() -> dict:
    dnglab = _find_dnglab()
    adobe = _find_adobe()
    native = _has_rawpy()

    if dnglab:
        backend = "dnglab"
        status = f"dnglab (open-source Rust converter)"
    elif adobe:
        backend = "adobe"
        status = "Adobe DNG Converter"
    elif native:
        backend = "native"
        status = "Native Python (rawpy)"
    else:
        backend = None
        status = None

    return {
        "available": bool(dnglab or adobe or native),
        "backend": backend,
        "dnglab_available": bool(dnglab),
        "adobe_available": bool(adobe),
        "native_available": native,
        "status": status,
        "install_hint": (
            "brew install dnglab  # recommended, open-source\n"
            "pip install rawpy     # Python fallback"
        ) if not (dnglab or adobe or native) else None,
    }

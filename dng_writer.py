"""
Pure Python DNG Writer
No Adobe dependency — writes DNG files per the open TIFF/DNG specification.

Uses rawpy (LibRaw, open source) to read any camera RAW format,
then writes a standards-compliant DNG container.
"""

import struct
import io
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image

# ============================================================
# TIFF / DNG Constants
# ============================================================

# Tag data types
BYTE, ASCII, SHORT, LONG, RATIONAL = 1, 2, 3, 4, 5
SBYTE, UNDEFINED, SSHORT, SLONG, SRATIONAL = 6, 7, 8, 9, 10

TYPE_SIZE = {
    BYTE: 1, ASCII: 1, SHORT: 2, LONG: 4, RATIONAL: 8,
    SBYTE: 1, UNDEFINED: 1, SSHORT: 2, SLONG: 4, SRATIONAL: 8,
}

# rawpy color index -> DNG CFA color (0=Red, 1=Green, 2=Blue)
RAWPY_TO_CFA = {0: 0, 1: 1, 2: 2, 3: 1}


# ============================================================
# Tag Helper
# ============================================================

class Tag:
    """Represents one TIFF IFD tag entry."""

    def __init__(self, tag_id, dtype, values):
        self.tag_id = tag_id
        self.dtype = dtype
        if isinstance(values, (list, tuple)):
            self.values = values
        else:
            self.values = [values]
        self.count = len(self.values)
        self._data_offset = 0  # set during layout

    def value_bytes(self):
        """Serialize the tag values to bytes."""
        buf = io.BytesIO()
        for v in self.values:
            if self.dtype == BYTE or self.dtype == UNDEFINED:
                buf.write(struct.pack('<B', v & 0xFF))
            elif self.dtype == ASCII:
                buf.write(v.encode('ascii') if isinstance(v, str) else v)
            elif self.dtype == SHORT:
                buf.write(struct.pack('<H', v))
            elif self.dtype == LONG:
                buf.write(struct.pack('<I', v))
            elif self.dtype == RATIONAL:
                num, den = v if isinstance(v, (list, tuple)) else (v, 1)
                buf.write(struct.pack('<II', int(num), int(den)))
            elif self.dtype == SRATIONAL:
                num, den = v if isinstance(v, (list, tuple)) else (v, 1)
                buf.write(struct.pack('<iI', int(num), int(den)))
            elif self.dtype == SSHORT:
                buf.write(struct.pack('<h', v))
            elif self.dtype == SLONG:
                buf.write(struct.pack('<i', v))
        return buf.getvalue()

    def byte_size(self):
        return TYPE_SIZE[self.dtype] * self.count

    def fits_inline(self):
        return self.byte_size() <= 4

    def write_entry(self, f):
        """Write the 12-byte IFD entry."""
        f.write(struct.pack('<HHI', self.tag_id, self.dtype, self.count))
        data = self.value_bytes()
        if self.fits_inline():
            f.write(data.ljust(4, b'\x00')[:4])
        else:
            f.write(struct.pack('<I', self._data_offset))

    def write_data(self, f):
        """Write the out-of-line data (if needed)."""
        if not self.fits_inline():
            f.write(self.value_bytes())


# ============================================================
# IFD Writer
# ============================================================

def _write_ifd(f, tags, next_ifd=0):
    """
    Write a complete IFD (entries + overflow data).
    Returns (ifd_offset, next_ifd_field_offset).
    """
    tags = sorted(tags, key=lambda t: t.tag_id)
    ifd_start = f.tell()

    # Layout: count(2) + entries(N*12) + next_ifd(4) + overflow data
    f.write(struct.pack('<H', len(tags)))

    entries_end = f.tell() + len(tags) * 12 + 4
    data_cursor = entries_end

    # Pre-calculate data offsets
    for tag in tags:
        if not tag.fits_inline():
            tag._data_offset = data_cursor
            data_cursor += tag.byte_size()
            # Align to 2-byte boundary
            if data_cursor % 2:
                data_cursor += 1

    # Write entries
    for tag in tags:
        tag.write_entry(f)

    # Next IFD pointer
    next_ifd_pos = f.tell()
    f.write(struct.pack('<I', next_ifd))

    # Write overflow data
    for tag in tags:
        if not tag.fits_inline():
            assert f.tell() == tag._data_offset
            tag.write_data(f)
            if f.tell() % 2:
                f.write(b'\x00')

    return ifd_start, next_ifd_pos


# ============================================================
# Main Conversion
# ============================================================

def convert_raw_to_dng(input_path: str, output_path: str) -> bool:
    """
    Convert a camera RAW file to DNG format.

    Args:
        input_path: Path to source RAW file (.arw, .cr2, .nef, etc.)
        output_path: Path for output DNG file

    Returns:
        True on success, False on failure.
    """
    try:
        with rawpy.imread(input_path) as raw:
            return _write_dng(raw, input_path, output_path)
    except Exception as e:
        print(f"DNG conversion error: {e}")
        return False


def _write_dng(raw, input_path: str, output_path: str) -> bool:
    """Build and write the DNG file from rawpy data."""

    # --- Extract metadata from RAW ---
    bayer = raw.raw_image_visible.copy()  # Visible-area Bayer data (uint16)
    raw_h, raw_w = bayer.shape

    # CFA pattern (2x2 Bayer or 6x6 X-Trans)
    pattern = raw.raw_pattern.tolist()
    pat_h, pat_w = len(pattern), len(pattern[0])
    cfa_flat = []
    for row in pattern:
        for val in row:
            cfa_flat.append(RAWPY_TO_CFA.get(val, val))

    # Black & white levels
    black_levels = list(raw.black_level_per_channel)
    white_level = int(raw.white_level)

    # Color matrix (for D65 illuminant)
    color_desc = raw.color_desc.decode() if isinstance(raw.color_desc, bytes) else raw.color_desc
    color_matrix = raw.color_matrix  # shape: (n, 4) typically
    # We need the 3x3 portion for RGB
    cm = color_matrix[:3, :3]

    # White balance (as-shot neutral)
    wb = raw.camera_whitebalance  # [R, G, B, G2] multipliers
    if wb[0] > 0 and wb[1] > 0 and wb[2] > 0:
        # Convert multipliers to neutral: neutral = 1/multiplier, normalized so G=1
        neutral = [wb[1] / wb[0], 1.0, wb[1] / wb[2]]
    else:
        neutral = [1.0, 1.0, 1.0]

    # Camera model
    camera_make = ""
    camera_model = "Unknown Camera"
    try:
        # Try extracting from EXIF via PIL on the embedded JPEG
        thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            from PIL.ExifTags import TAGS
            thumb_img = Image.open(io.BytesIO(thumb.data))
            exif = thumb_img._getexif() or {}
            exif_named = {TAGS.get(k, k): v for k, v in exif.items()}
            camera_make = exif_named.get("Make", "")
            camera_model = exif_named.get("Model", camera_model)
    except Exception:
        pass

    # Bits per sample — detect from white level
    if white_level <= 4095:
        bits = 12
    elif white_level <= 16383:
        bits = 14
    else:
        bits = 16

    # Normalize bayer data to declared bit depth (store as 16-bit in file)
    raw_data = bayer.astype(np.uint16)

    # --- Generate preview (small JPEG-quality RGB thumbnail) ---
    try:
        rgb = raw.postprocess(
            half_size=True,
            use_camera_wb=True,
            no_auto_bright=False,
            output_bps=8,
        )
        preview_img = Image.fromarray(rgb)
        # Cap preview size
        preview_img.thumbnail((1024, 1024))
    except Exception:
        # Fallback: tiny placeholder
        preview_img = Image.new('RGB', (160, 120), (128, 128, 128))

    prev_w, prev_h = preview_img.size
    preview_rgb = np.array(preview_img)
    preview_bytes = preview_rgb.tobytes()  # raw RGB data

    # --- Build the DNG file ---
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'wb') as f:
        # ---- TIFF Header ----
        f.write(b'II')                          # Little-endian
        f.write(struct.pack('<H', 42))           # TIFF magic
        f.write(struct.pack('<I', 8))            # IFD0 starts right after header

        # ---- Plan the file layout ----
        # We'll write:
        #   1. IFD0 (preview image + DNG metadata)
        #   2. Raw SubIFD (Bayer image metadata)
        #   3. Preview pixel data
        #   4. Raw pixel data
        #
        # But we need offsets before writing IFDs.
        # Strategy: build tags, then calculate layout, then write.

        # -- IFD0 tags (preview + DNG metadata) --
        model_str = camera_model + '\x00'
        make_str = (camera_make + '\x00') if camera_make else ("Unknown\x00")
        software_str = 'Fovea (open-source DNG writer)\x00'

        # Color matrix as SRATIONALs: each entry = (numerator * 10000, 10000)
        cm_rational = []
        for r in range(3):
            for c in range(3):
                val = float(cm[r, c])
                # Express as rational with denominator 10000
                num = int(round(val * 10000))
                cm_rational.append((num, 10000))

        # As-shot neutral as RATIONALs
        neutral_rational = []
        for n in neutral:
            num = int(round(n * 1000000))
            neutral_rational.append((num, 1000000))

        # Black level as RATIONALs (per CFA pattern element)
        # Expand to match CFA pattern
        bl_rational = []
        for i in range(pat_h * pat_w):
            color_idx = cfa_flat[i]
            if color_idx == 0:
                bl = black_levels[0]
            elif color_idx == 2:
                bl = black_levels[2]
            else:
                bl = black_levels[1]
            bl_rational.append((int(bl), 1))

        # We need to know the SubIFD offset before writing IFD0.
        # And we need to know data offsets before writing SubIFD.
        # Solution: calculate sizes first, then write.

        # Calculate IFD0 size
        ifd0_tags_list = []

        # -- Collect IFD0 tags --
        ifd0_tags_list.append(Tag(254, LONG, 1))            # NewSubfileType = thumbnail
        ifd0_tags_list.append(Tag(256, LONG, prev_w))       # ImageWidth
        ifd0_tags_list.append(Tag(257, LONG, prev_h))       # ImageLength
        ifd0_tags_list.append(Tag(258, SHORT, [8, 8, 8]))   # BitsPerSample
        ifd0_tags_list.append(Tag(259, SHORT, 1))            # Compression = none
        ifd0_tags_list.append(Tag(262, SHORT, 2))            # PhotometricInterpretation = RGB
        ifd0_tags_list.append(Tag(271, ASCII, make_str))     # Make
        ifd0_tags_list.append(Tag(272, ASCII, model_str))    # Model
        ifd0_tags_list.append(Tag(273, LONG, 0))             # StripOffsets (placeholder)
        ifd0_tags_list.append(Tag(274, SHORT, 1))            # Orientation = normal
        ifd0_tags_list.append(Tag(277, SHORT, 3))            # SamplesPerPixel
        ifd0_tags_list.append(Tag(278, LONG, prev_h))        # RowsPerStrip
        ifd0_tags_list.append(Tag(279, LONG, len(preview_bytes)))  # StripByteCounts
        ifd0_tags_list.append(Tag(284, SHORT, 1))            # PlanarConfiguration = chunky
        ifd0_tags_list.append(Tag(305, ASCII, software_str)) # Software
        ifd0_tags_list.append(Tag(330, LONG, 0))             # SubIFDs (placeholder)

        # DNG-specific tags
        ifd0_tags_list.append(Tag(50706, BYTE, [1, 6, 0, 0]))      # DNGVersion 1.6
        ifd0_tags_list.append(Tag(50707, BYTE, [1, 4, 0, 0]))      # DNGBackwardVersion 1.4
        ifd0_tags_list.append(Tag(50708, ASCII, model_str))          # UniqueCameraModel
        ifd0_tags_list.append(Tag(50721, SRATIONAL, cm_rational))    # ColorMatrix1
        ifd0_tags_list.append(Tag(50728, RATIONAL, neutral_rational))# AsShotNeutral
        ifd0_tags_list.append(Tag(50778, SHORT, 21))                 # CalibrationIlluminant1 = D65

        # ---- Calculate IFD0 size ----
        ifd0_tags_sorted = sorted(ifd0_tags_list, key=lambda t: t.tag_id)
        ifd0_entry_size = 2 + len(ifd0_tags_sorted) * 12 + 4
        ifd0_overflow = sum(
            t.byte_size() + (1 if t.byte_size() % 2 else 0)
            for t in ifd0_tags_sorted if not t.fits_inline()
        )
        ifd0_total = ifd0_entry_size + ifd0_overflow

        # SubIFD starts right after IFD0
        sub_ifd_offset = 8 + ifd0_total  # 8 = TIFF header

        # -- Collect SubIFD tags (raw Bayer data) --
        sub_tags_list = []
        sub_tags_list.append(Tag(254, LONG, 0))                      # NewSubfileType = full res
        sub_tags_list.append(Tag(256, LONG, raw_w))                  # ImageWidth
        sub_tags_list.append(Tag(257, LONG, raw_h))                  # ImageLength
        sub_tags_list.append(Tag(258, SHORT, bits))                  # BitsPerSample
        sub_tags_list.append(Tag(259, SHORT, 1))                     # Compression = none
        sub_tags_list.append(Tag(262, SHORT, 32803))                 # PhotometricInterpretation = CFA
        sub_tags_list.append(Tag(273, LONG, 0))                      # StripOffsets (placeholder)
        sub_tags_list.append(Tag(277, SHORT, 1))                     # SamplesPerPixel
        sub_tags_list.append(Tag(278, LONG, raw_h))                  # RowsPerStrip
        sub_tags_list.append(Tag(279, LONG, raw_w * raw_h * 2))     # StripByteCounts (16-bit)
        sub_tags_list.append(Tag(284, SHORT, 1))                     # PlanarConfiguration

        # CFA tags
        sub_tags_list.append(Tag(33421, SHORT, [pat_h, pat_w]))      # CFARepeatPatternDim
        sub_tags_list.append(Tag(33422, BYTE, cfa_flat))              # CFAPattern
        sub_tags_list.append(Tag(50710, BYTE, [0, 1, 2]))            # CFAPlaneColor = R,G,B
        sub_tags_list.append(Tag(50711, SHORT, 1))                   # CFALayout = rectangular

        # Levels
        sub_tags_list.append(Tag(50714, RATIONAL, bl_rational))       # BlackLevel
        sub_tags_list.append(Tag(50717, LONG, white_level))           # WhiteLevel

        # Active area (full sensor)
        sub_tags_list.append(Tag(50829, LONG, [0, 0, raw_h, raw_w])) # ActiveArea

        # Default crop (full image)
        sub_tags_list.append(Tag(50719, RATIONAL, [(0, 1), (0, 1)]))  # DefaultCropOrigin
        sub_tags_list.append(Tag(50720, RATIONAL, [(raw_w, 1), (raw_h, 1)]))  # DefaultCropSize

        # ---- Calculate SubIFD size ----
        sub_tags_sorted = sorted(sub_tags_list, key=lambda t: t.tag_id)
        sub_entry_size = 2 + len(sub_tags_sorted) * 12 + 4
        sub_overflow = sum(
            t.byte_size() + (1 if t.byte_size() % 2 else 0)
            for t in sub_tags_sorted if not t.fits_inline()
        )
        sub_total = sub_entry_size + sub_overflow

        # Data starts after SubIFD
        preview_data_offset = sub_ifd_offset + sub_total
        raw_data_offset = preview_data_offset + len(preview_bytes)
        # Align raw data to 2-byte boundary
        if raw_data_offset % 2:
            raw_data_offset += 1

        # ---- Fix placeholder offsets ----
        for tag in ifd0_tags_list:
            if tag.tag_id == 273:  # StripOffsets -> preview data
                tag.values = [preview_data_offset]
            elif tag.tag_id == 330:  # SubIFDs -> raw SubIFD
                tag.values = [sub_ifd_offset]

        for tag in sub_tags_list:
            if tag.tag_id == 273:  # StripOffsets -> raw data
                tag.values = [raw_data_offset]

        # ---- Write everything ----
        # IFD0
        f.seek(8)
        _write_ifd(f, ifd0_tags_list)

        # SubIFD
        assert f.tell() == sub_ifd_offset, f"SubIFD offset mismatch: {f.tell()} vs {sub_ifd_offset}"
        _write_ifd(f, sub_tags_list)

        # Preview data
        assert f.tell() == preview_data_offset, f"Preview offset mismatch: {f.tell()} vs {preview_data_offset}"
        f.write(preview_bytes)

        # Align
        if f.tell() % 2:
            f.write(b'\x00')

        # Raw Bayer data (16-bit little-endian)
        assert f.tell() == raw_data_offset, f"Raw offset mismatch: {f.tell()} vs {raw_data_offset}"
        raw_data.tofile(f)

    return True


# ============================================================
# Public API
# ============================================================

def native_convert(input_path: str, output_dir: str) -> str | None:
    """
    Convert RAW to DNG using pure Python (no Adobe dependency).

    Returns the output DNG path on success, None on failure.
    """
    inp = Path(input_path)
    out = Path(output_dir) / (inp.stem + ".dng")

    if convert_raw_to_dng(str(inp), str(out)):
        return str(out)
    return None

# Fovea

Smart camera photo import, open-format conversion, and AI-powered organization.

**Fovea** automates everything after you press the shutter — import from SD card, convert to open DNG format, organize by date, and let local AI quietly analyze your photos in the background.

## Why

Importing photos from a camera is still painful:
- SD cards have messy folder structures mixed with system files
- RAW formats are proprietary and vendor-locked
- Organizing hundreds of photos by hand is tedious
- Finding duplicates, blurry shots, and similar photos takes time

Fovea solves all of this in one self-hosted web app.

## Features

### Smart Import
- Auto-detect cameras and SD cards (Sony, Canon, Nikon, Fujifilm, Olympus, Panasonic)
- Classify files by type — RAW, JPEG, Video, Sidecar, System files
- RAW + JPEG pairing with Smart Select (pick the best, skip the rest)
- XMP sidecar files automatically follow their paired photos
- Incremental import — never duplicate what's already been imported
- EXIF extraction — date, camera model, lens, ISO, aperture, shutter speed

### Open Format (DNG)
- Convert proprietary RAW (ARW, CR2, CR3, NEF, RAF...) to open-standard DNG
- Three conversion backends:
  - [**dnglab**](https://github.com/dnglab/dnglab) — open-source Rust converter (recommended)
  - **Adobe DNG Converter** — optional proprietary fallback
  - **Native Python** — rawpy-based, zero external dependency
- DNG is readable by Apple Photos, Lightroom, Capture One, darktable, and every major photo editor
- No more vendor lock-in. No more sidecar files.

### Smart Organization
- Auto-organize by date: `YYYY/MM/YYYYMMDD/`
- Or by event name: `2026/03/Tokyo Trip/`
- Optional RAW subfolder separation
- Target any drive — local SSD, external HDD, NAS

### Background AI Analysis
- **Runs automatically** after import — no manual trigger needed
- Processes photos one by one in idle time (3s throttle, gentle on CPU)
- **Pauses during import**, resumes after — never competes for resources
- Pause / Resume / Stop controls in UI
- Results persist across restarts

#### AI Capabilities (all local, no cloud)
| Engine | What it does |
|--------|-------------|
| [OpenCLIP](https://github.com/mlfoundations/open_clip) ViT-B/32 | Scene classification, semantic tagging, similarity/duplicate detection |
| [InsightFace](https://github.com/deepinsight/insightface) ArcFace | Face detection, recognition, clustering by person |
| OpenCV | Blur detection, over/under-exposure analysis |
| Moondream 2 *(optional, on-demand)* | Detailed natural language photo descriptions |

### Web UI
- Clean, responsive interface with light/dark theme
- Works on any browser — manage your photos from phone, tablet, or desktop
- File preview with thumbnails, EXIF info, and type filtering
- Real-time import progress and analysis status

## Quick Start

```bash
# Clone
git clone https://github.com/peng/fovea.git
cd fovea

# Install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional: DNG conversion (recommended)
brew install dnglab

# Optional: AI analysis
pip install torch open-clip-torch insightface onnxruntime opencv-python

# Run
python3 main.py
# Open http://localhost:8080
```

Or use the quick start script:
```bash
./run.sh
```

## Dependencies

**Core** (required):
- Python 3.9+
- FastAPI, uvicorn, Pillow, httpx

**DNG Conversion** (pick one):
- `dnglab` — `brew install dnglab` *(recommended)*
- `rawpy` — `pip install rawpy` *(Python fallback)*
- Adobe DNG Converter *(optional)*

**AI Analysis** (optional):
- PyTorch, OpenCLIP, InsightFace, ONNX Runtime, OpenCV
- ~1GB disk for models (auto-downloaded on first run)
- ~1GB RAM during analysis
- Apple Silicon MPS acceleration supported

## Architecture

```
SD Card ──→ Scanner ──→ Web UI (preview & select)
                              │
                              ▼
                        Smart Import
                        ├── DNG Conversion (dnglab / Adobe / native)
                        ├── Date-based organization
                        └── Copy with verification
                              │
                              ▼
                     Background AI Daemon
                     ├── CLIP: scene tags + similarity
                     ├── InsightFace: face clustering
                     └── OpenCV: quality checks
```

## Credits

See [CREDITS.md](CREDITS.md) for full attribution.

Built on the shoulders of [dnglab](https://github.com/dnglab/dnglab), [OpenCLIP](https://github.com/mlfoundations/open_clip), [InsightFace](https://github.com/deepinsight/insightface), [rawpy/LibRaw](https://github.com/letmaik/rawpy), and many other open-source projects.

Inspired by [Immich](https://github.com/immich-app/immich), [PhotoPrism](https://github.com/photoprism/photoprism), [Rapid Photo Downloader](https://github.com/damonlynch/rapid-photo-downloader), and [fastdup](https://github.com/visual-layer/fastdup).

## License

[MIT](LICENSE)

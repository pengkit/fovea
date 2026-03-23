# Fovea

A native macOS app for camera photo import, RAW processing, and library management.

## The Problem

Getting photos off a camera and into a usable state is still surprisingly painful in 2026:

- **RAW formats are a mess.** Sony shoots ARW, Canon uses CR2/CR3, Nikon has NEF, Fujifilm does RAF — each a proprietary format that only the vendor's own software handles well. You're locked into their ecosystem the moment you press the shutter.
- **SD card structures are chaotic.** Nested DCIM folders, system files (AVCHD, THM, BDM), sidecar XMPs — you have to know what to keep and what to skip.
- **Apple Photos can't read most RAW files natively.** It supports some (like CR3 and DNG), but many formats require third-party codecs. And once imported, your RAW files are buried inside the opaque Photos Library package.
- **Adobe's DNG format is the closest thing to a universal standard.** It's open, readable by every major editor (Lightroom, Capture One, darktable, Apple Photos), and preserves full RAW quality. But converting to DNG is manual and tedious.

Fovea automates the entire pipeline: detect camera → scan files → preview → convert RAW to DNG → organize by date → manage your library.

## Features

### Smart Import
- Auto-detect cameras and SD cards (Sony, Canon, Nikon, Fujifilm, Olympus, Panasonic)
- Classify files by type — RAW, JPEG, Video, Sidecar, System
- RAW + JPEG pairing with Smart Select
- XMP sidecar files follow their paired photos automatically
- Incremental import — never duplicate what's already been imported
- EXIF extraction — date, camera model, lens, ISO, aperture, shutter speed

### RAW Processing
- Convert proprietary RAW to open-standard DNG on import
- Three conversion backends:
  - [**dnglab**](https://github.com/dnglab/dnglab) — open-source Rust converter (recommended)
  - **Adobe DNG Converter** — proprietary fallback
  - **rawpy/LibRaw** — Python fallback, zero external dependency
- Apple Core Image rendering for RAW preview and adjustments (auto/vivid/warm presets)
- DNG is readable everywhere: Apple Photos, Lightroom, Capture One, darktable

### Photo Library
- Timeline view with date headers, sorted newest-first
- iCloud Photos integration — browse and view your full Apple Photos library
- Photo adjustments powered by Apple Core Image (same engine as Photos.app)
- Rotation support with adjustment saving
- Soft delete with 30-day trash and restore
- Send photos to iCloud Photos directly from the app
- Batch operations — select multiple photos for delete or iCloud upload

### Native macOS App
- Swift shell with WKWebView — feels native, runs local
- Python FastAPI backend (port 8080) for all server-side logic
- Swift ThumbnailServer (port 9998) for Core Image RAW rendering
- Builds to a standard `.app` bundle distributed as DMG
- Light and dark theme

## Install

Download the latest DMG from [Releases](https://github.com/pengkit/fovea/releases), open it, and drag Fovea to Applications.

First launch takes ~1 minute to set up the Python environment.

### Optional: DNG Conversion

```bash
brew install dnglab
```

## Build from Source

```bash
git clone https://github.com/pengkit/fovea.git
cd fovea
bash build_macos.sh
# DMG is in build/Fovea-0.1.0-macOS.dmg
```

Requires: macOS, Xcode command line tools, Python 3.9+.

## Architecture

```
SD Card ──→ Scanner ──→ Preview & Select (Web UI)
                              │
                              ▼
                        Smart Import
                        ├── DNG Conversion (dnglab / Adobe / rawpy)
                        ├── Date-based organization (YYYY/MM/DD/)
                        └── Copy with verification
                              │
                              ▼
                     Fovea Library (~/Pictures/Fovea/)
                     ├── Timeline view
                     ├── Core Image adjustments
                     ├── Soft delete / restore
                     └── Send to iCloud Photos
```

### Tech Stack
- **Swift**: App shell (WKWebView), PhotoKit integration, Core Image RAW rendering
- **Python**: FastAPI server, scanner, importer, DNG converter, thumbnail generator
- **Frontend**: Single-page HTML/CSS/JS in `static/index.html`

## Why DNG?

| | Proprietary RAW (ARW, CR3, NEF...) | Adobe DNG |
|---|---|---|
| Readable by | Vendor software + some editors | Everything |
| Open standard | No | Yes (public spec) |
| Apple Photos | Partial support | Full support |
| Lightroom | Yes | Yes |
| darktable | Yes | Yes |
| File size | Varies | Similar (lossless compressed) |
| Metadata | EXIF + vendor-specific | EXIF + XMP embedded |
| Future-proof | Depends on vendor | Open spec, widely adopted |

## License

[MIT](LICENSE)

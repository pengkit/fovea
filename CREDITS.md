# Credits & Attribution

Fovea builds on the work of many excellent open-source projects.

## Core Dependencies

| Project | License | Usage |
|---------|---------|-------|
| [FastAPI](https://github.com/tiangolo/fastapi) | MIT | Web framework |
| [Pillow](https://github.com/python-pillow/Pillow) | HPND | Image processing, EXIF extraction |
| [rawpy / LibRaw](https://github.com/letmaik/rawpy) | MIT / LGPL-2.1 | RAW file reading |
| [OpenCV](https://github.com/opencv/opencv-python) | Apache 2.0 | Blur detection, exposure analysis |

## AI / ML

| Project | License | Usage |
|---------|---------|-------|
| [OpenCLIP](https://github.com/mlfoundations/open_clip) | MIT | Scene classification, semantic tagging, similarity detection |
| [InsightFace](https://github.com/deepinsight/insightface) | MIT | Face detection, recognition, clustering |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | MIT | InsightFace inference engine |
| [PyTorch](https://github.com/pytorch/pytorch) | BSD-3-Clause | CLIP model inference, MPS acceleration |

## DNG Conversion

| Project | License | Usage |
|---------|---------|-------|
| [dnglab](https://github.com/dnglab/dnglab) | LGPL-2.1 | Primary RAW-to-DNG converter (recommended) |
| [Adobe DNG Converter](https://helpx.adobe.com/camera-raw/using/adobe-dng-converter.html) | Freeware | Optional fallback DNG converter |
| DNG Specification | Adobe, royalty-free | Open format standard for our native Python writer |

## Inspiration & Reference

These projects informed the design of Fovea:

| Project | Stars | What we learned |
|---------|-------|-----------------|
| [Immich](https://github.com/immich-app/immich) | ~90k | CLIP-based smart search, face recognition UX |
| [PhotoPrism](https://github.com/photoprism/photoprism) | ~39k | AI auto-tagging architecture, folder organization |
| [Rapid Photo Downloader](https://github.com/damonlynch/rapid-photo-downloader) | ~166 | SD card detection, RAW+JPEG pairing, camera folder patterns |
| [fastdup](https://github.com/visual-layer/fastdup) | ~1.8k | Scalable duplicate/quality detection approach |
| [imagededup](https://github.com/idealo/imagededup) | ~5.5k | Perceptual hashing algorithms |
| [STAG](https://github.com/DIVISIO-AI/stag) | - | Local AI tagging to XMP workflow |
| [LibrePhotos](https://github.com/LibrePhotos/librephotos) | ~8k | Self-hosted photo management with ML |

## Fonts

- [Inter](https://github.com/rsms/inter) — SIL Open Font License 1.1

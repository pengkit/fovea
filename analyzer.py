"""
Fovea - Unified Photo Analyzer

Architecture:
  Tier 1 (auto, lightweight ~1GB):
    CLIP ViT-B/32     → semantic tags, scene classification, similarity/duplicate detection
    InsightFace ArcFace → face detection + embedding + clustering
    OpenCV             → blur / exposure quality checks

  Tier 2 (on-demand, optional):
    Moondream 2 (~1.8B) → detailed description for individual photos
"""

import os
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import numpy as np

from config import (
    BLUR_THRESHOLD, OVEREXPOSURE_THRESHOLD, UNDEREXPOSURE_THRESHOLD,
    THUMBNAIL_DIR, JPEG_EXTENSIONS, RAW_EXTENSIONS,
)

# ============================================================
# Scene categories: English prompt → Chinese label
# ============================================================
SCENE_CATEGORIES = {
    "landscape scenery": "风景",
    "portrait of a person": "人像",
    "street photography": "街拍",
    "architecture building": "建筑",
    "food photography": "美食",
    "animal pet wildlife": "动物",
    "sunset or sunrise sky": "日出日落",
    "night photography city lights": "夜景",
    "macro close-up detail": "微距",
    "sports action movement": "运动",
    "travel tourism": "旅行",
    "indoor room interior": "室内",
    "beach ocean sea": "海滩",
    "mountain hiking": "山景",
    "cityscape urban skyline": "城市",
    "forest trees nature": "森林",
    "flower plant garden": "花卉",
    "group photo gathering": "合影",
    "product still life": "产品",
    "aerial drone view": "航拍",
    "black and white monochrome": "黑白",
    "water lake river waterfall": "水景",
    "snow winter cold": "雪景",
    "car vehicle transportation": "车辆",
}

CATEGORY_PROMPTS = list(SCENE_CATEGORIES.keys())
CATEGORY_LABELS = list(SCENE_CATEGORIES.values())


# ============================================================
# Lazy-loaded singleton analyzer
# ============================================================

class PhotoAnalyzer:
    """Unified photo analyzer. Models are loaded on first use."""

    def __init__(self):
        self._clip_model = None
        self._clip_preprocess = None
        self._clip_tokenizer = None
        self._category_features = None
        self._face_app = None
        self._device = None
        self._moondream_model = None
        self._moondream_tokenizer = None

    @property
    def device(self):
        if self._device is None:
            import torch
            if torch.backends.mps.is_available():
                self._device = "mps"
            elif torch.cuda.is_available():
                self._device = "cuda"
            else:
                self._device = "cpu"
        return self._device

    # ---- Model Loading (lazy) ----

    def _load_clip(self):
        if self._clip_model is not None:
            return
        import torch
        import open_clip

        model, _, preprocess = open_clip.create_model_and_transforms(
            'ViT-B-32', pretrained='laion2b_s34b_b79k'
        )
        model = model.to(self.device).eval()
        tokenizer = open_clip.get_tokenizer('ViT-B-32')

        # Pre-compute category text embeddings
        text_tokens = tokenizer(CATEGORY_PROMPTS).to(self.device)
        with torch.no_grad():
            cat_features = model.encode_text(text_tokens)
            cat_features = cat_features / cat_features.norm(dim=-1, keepdim=True)

        self._clip_model = model
        self._clip_preprocess = preprocess
        self._clip_tokenizer = tokenizer
        self._category_features = cat_features

    def _load_insightface(self):
        if self._face_app is not None:
            return
        from insightface.app import FaceAnalysis

        app = FaceAnalysis(
            name='buffalo_l',
            providers=['CoreMLExecutionProvider', 'CPUExecutionProvider'],
        )
        app.prepare(ctx_id=0, det_size=(640, 640))
        self._face_app = app

    # ---- Per-photo analysis ----

    def analyze_photo(self, filepath: str) -> dict:
        """
        Analyze a single photo. Returns unified result dict:
        {
            path, filename, thumbnail_url,
            tags: [(label_zh, label_en, score), ...],
            scene: str,
            clip_embedding: np.array (512-d),
            faces: [{bbox, score, embedding, age, gender}, ...],
            quality: {blur_score, is_blurry, overexposed_ratio, ...},
        }
        """
        from PIL import Image

        result = {
            'path': filepath,
            'filename': Path(filepath).name,
            'thumbnail_url': self._get_thumbnail_url(filepath),
            'tags': [],
            'scene': None,
            'scene_en': None,
            'clip_embedding': None,
            'faces': [],
            'quality': {},
        }

        # Load image
        try:
            img_pil = Image.open(filepath).convert('RGB')
        except Exception:
            # Try RAW via rawpy
            try:
                import rawpy
                with rawpy.imread(filepath) as raw:
                    rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
                    img_pil = Image.fromarray(rgb)
            except Exception:
                return result

        # ---- CLIP: tags + embedding ----
        try:
            self._load_clip()
            result.update(self._clip_analyze(img_pil))
        except Exception as e:
            result['_clip_error'] = str(e)

        # ---- InsightFace: faces ----
        try:
            self._load_insightface()
            result['faces'] = self._face_analyze(img_pil)
        except Exception as e:
            result['_face_error'] = str(e)

        # ---- OpenCV: quality ----
        try:
            result['quality'] = self._quality_analyze(img_pil)
        except Exception as e:
            result['_quality_error'] = str(e)

        return result

    def _clip_analyze(self, img_pil) -> dict:
        """CLIP: scene classification + embedding."""
        import torch

        clip_input = self._clip_preprocess(img_pil).unsqueeze(0).to(self.device)
        with torch.no_grad():
            img_features = self._clip_model.encode_image(clip_input)
            img_features = img_features / img_features.norm(dim=-1, keepdim=True)

        embedding = img_features.cpu().numpy().flatten()

        # Zero-shot classification
        similarity = (img_features @ self._category_features.T).squeeze().cpu().numpy()
        top_k = similarity.argsort()[::-1][:5]

        tags = []
        for i in top_k:
            tags.append((CATEGORY_LABELS[i], CATEGORY_PROMPTS[i], float(similarity[i])))

        return {
            'tags': tags,
            'scene': CATEGORY_LABELS[top_k[0]],
            'scene_en': CATEGORY_PROMPTS[top_k[0]],
            'clip_embedding': embedding,
        }

    def _face_analyze(self, img_pil) -> list:
        """InsightFace: detect faces + embeddings."""
        img_np = np.array(img_pil)
        # InsightFace expects BGR
        img_bgr = img_np[:, :, ::-1].copy()

        # Limit size for speed
        h, w = img_bgr.shape[:2]
        if max(h, w) > 1280:
            scale = 1280 / max(h, w)
            img_bgr = _resize(img_bgr, scale)

        faces = self._face_app.get(img_bgr)
        results = []
        for face in faces:
            fd = {
                'bbox': face.bbox.tolist(),
                'score': float(face.det_score),
                'embedding': face.embedding.tolist(),
            }
            if hasattr(face, 'age') and face.age is not None:
                fd['age'] = int(face.age)
            if hasattr(face, 'gender') and face.gender is not None:
                fd['gender'] = 'M' if face.gender == 1 else 'F'
            results.append(fd)
        return results

    def _quality_analyze(self, img_pil) -> dict:
        """OpenCV: blur + exposure analysis."""
        import cv2

        img_np = np.array(img_pil)
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

        # Resize for speed
        if gray.shape[0] > 1000:
            scale = 1000 / gray.shape[0]
            gray = cv2.resize(gray, None, fx=scale, fy=scale)

        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        total = gray.size
        over_ratio = float(np.sum(gray > 240)) / total
        under_ratio = float(np.sum(gray < 15)) / total

        return {
            'blur_score': round(blur_score, 2),
            'is_blurry': blur_score < BLUR_THRESHOLD,
            'overexposed_ratio': round(over_ratio, 4),
            'underexposed_ratio': round(under_ratio, 4),
            'is_overexposed': over_ratio > OVEREXPOSURE_THRESHOLD,
            'is_underexposed': under_ratio > UNDEREXPOSURE_THRESHOLD,
        }

    # ---- Batch analysis ----

    def analyze_batch(self, file_paths: list, progress_cb=None) -> dict:
        """
        Analyze a batch of photos. Returns aggregated results:
        {
            status, total,
            scene_groups: [{category, label, count, sample_paths, sample_thumbs}],
            face_groups: [{person_id, count, sample_paths, sample_thumbs, age, gender}],
            quality_issues: [{path, thumbnail_url, issue, detail}],
            similar_groups: [[{path, thumbnail_url, similarity}]],
            photos: [per-photo result],
        }
        """
        all_results = []
        embeddings = []  # (idx, embedding) for similarity

        for i, fp in enumerate(file_paths):
            if progress_cb:
                progress_cb(i, len(file_paths), Path(fp).name)

            r = self.analyze_photo(fp)
            all_results.append(r)

            if r.get('clip_embedding') is not None:
                embeddings.append((i, r['clip_embedding']))

        # ---- Aggregate: scene groups ----
        scene_counts = {}
        for r in all_results:
            scene = r.get('scene')
            if scene:
                scene_counts.setdefault(scene, []).append(r)

        scene_groups = []
        for cat, photos in sorted(scene_counts.items(), key=lambda x: -len(x[1])):
            scene_groups.append({
                'category': cat,
                'count': len(photos),
                'sample_paths': [p['path'] for p in photos[:6]],
                'sample_thumbs': [p['thumbnail_url'] for p in photos[:6]],
            })

        # ---- Aggregate: face clustering ----
        face_groups = self._cluster_faces(all_results)

        # ---- Aggregate: quality issues ----
        quality_issues = []
        for r in all_results:
            q = r.get('quality', {})
            if q.get('is_blurry'):
                quality_issues.append({
                    'path': r['path'], 'filename': r['filename'],
                    'thumbnail_url': r['thumbnail_url'],
                    'issue': 'blurry', 'issue_zh': '模糊',
                    'detail': f"Score: {q['blur_score']}",
                })
            if q.get('is_overexposed'):
                quality_issues.append({
                    'path': r['path'], 'filename': r['filename'],
                    'thumbnail_url': r['thumbnail_url'],
                    'issue': 'overexposed', 'issue_zh': '过曝',
                    'detail': f"{q['overexposed_ratio']:.1%}",
                })
            if q.get('is_underexposed'):
                quality_issues.append({
                    'path': r['path'], 'filename': r['filename'],
                    'thumbnail_url': r['thumbnail_url'],
                    'issue': 'underexposed', 'issue_zh': '欠曝',
                    'detail': f"{q['underexposed_ratio']:.1%}",
                })

        # ---- Aggregate: similar photos (CLIP cosine similarity) ----
        similar_groups = self._find_similar(embeddings, all_results)

        return {
            'status': 'completed',
            'total': len(all_results),
            'scene_groups': scene_groups,
            'face_groups': face_groups,
            'quality_issues': quality_issues,
            'similar_groups': similar_groups,
            'photos': [
                {
                    'path': r['path'],
                    'filename': r['filename'],
                    'thumbnail_url': r['thumbnail_url'],
                    'scene': r.get('scene'),
                    'tags': [(t[0], round(t[2], 3)) for t in r.get('tags', [])],
                    'faces_count': len(r.get('faces', [])),
                    'quality': r.get('quality', {}),
                }
                for r in all_results
            ],
        }

    def _cluster_faces(self, all_results: list) -> list:
        """Cluster faces across all photos using InsightFace embeddings."""
        # Collect all face embeddings with their photo path
        all_faces = []  # (photo_path, thumb_url, embedding, age, gender)
        for r in all_results:
            for face in r.get('faces', []):
                emb = face.get('embedding')
                if emb is not None:
                    all_faces.append((
                        r['path'], r['thumbnail_url'],
                        np.array(emb),
                        face.get('age'), face.get('gender'),
                    ))

        if not all_faces:
            return []

        # Greedy clustering: cosine similarity > 0.5
        clusters = []  # [[face_idx, ...], ...]
        used = set()

        for i in range(len(all_faces)):
            if i in used:
                continue
            cluster = [i]
            used.add(i)
            emb_i = all_faces[i][2]
            norm_i = np.linalg.norm(emb_i)
            if norm_i == 0:
                continue

            for j in range(i + 1, len(all_faces)):
                if j in used:
                    continue
                emb_j = all_faces[j][2]
                norm_j = np.linalg.norm(emb_j)
                if norm_j == 0:
                    continue
                sim = float(np.dot(emb_i, emb_j) / (norm_i * norm_j))
                if sim > 0.5:
                    cluster.append(j)
                    used.add(j)

            clusters.append(cluster)

        # Build output
        groups = []
        for pid, cluster in enumerate(clusters):
            paths = list(dict.fromkeys(all_faces[i][0] for i in cluster))  # unique, ordered
            thumbs = list(dict.fromkeys(all_faces[i][1] for i in cluster if all_faces[i][1]))
            ages = [all_faces[i][3] for i in cluster if all_faces[i][3] is not None]
            genders = [all_faces[i][4] for i in cluster if all_faces[i][4] is not None]

            groups.append({
                'person_id': pid,
                'count': len(paths),
                'sample_paths': paths[:8],
                'sample_thumbs': thumbs[:8],
                'avg_age': round(np.mean(ages)) if ages else None,
                'gender': max(set(genders), key=genders.count) if genders else None,
            })

        groups.sort(key=lambda g: -g['count'])
        return groups

    def _find_similar(self, embeddings: list, all_results: list, threshold=0.93) -> list:
        """Find groups of similar/duplicate photos using CLIP embeddings."""
        if len(embeddings) < 2:
            return []

        indices = [e[0] for e in embeddings]
        vecs = np.stack([e[1] for e in embeddings])

        # Normalize
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vecs = vecs / norms

        # Cosine similarity matrix
        sim_matrix = vecs @ vecs.T

        groups = []
        used = set()

        for i in range(len(indices)):
            if i in used:
                continue
            group_idx = [i]
            used.add(i)

            for j in range(i + 1, len(indices)):
                if j in used:
                    continue
                if sim_matrix[i, j] > threshold:
                    group_idx.append(j)
                    used.add(j)

            if len(group_idx) > 1:
                group = []
                for gi in group_idx:
                    orig_idx = indices[gi]
                    r = all_results[orig_idx]
                    group.append({
                        'path': r['path'],
                        'filename': r['filename'],
                        'thumbnail_url': r['thumbnail_url'],
                    })
                groups.append(group)

        return groups

    # ---- Tier 2: On-demand VLM description ----

    def describe_photo(self, filepath: str) -> Optional[str]:
        """
        Use a local VLM (Moondream 2) to generate a detailed description.
        Only called on-demand for individual photos.
        """
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from PIL import Image

            if self._moondream_model is None:
                self._moondream_model = AutoModelForCausalLM.from_pretrained(
                    "vikhyatk/moondream2",
                    trust_remote_code=True,
                    torch_dtype="auto",
                ).to(self.device).eval()
                self._moondream_tokenizer = AutoTokenizer.from_pretrained(
                    "vikhyatk/moondream2",
                )

            img = Image.open(filepath).convert('RGB')
            img.thumbnail((768, 768))

            enc_img = self._moondream_model.encode_image(img)
            description = self._moondream_model.answer_question(
                enc_img,
                "Describe this photo in detail: the scene, subjects, composition, "
                "lighting, mood, and any notable elements. Be concise but thorough.",
                self._moondream_tokenizer,
            )
            return description
        except ImportError:
            return None
        except Exception as e:
            return f"Error: {e}"

    # ---- Helpers ----

    def _get_thumbnail_url(self, filepath: str) -> Optional[str]:
        fhash = hashlib.md5(filepath.encode()).hexdigest()
        thumb_path = THUMBNAIL_DIR / f"{fhash}.jpg"
        if thumb_path.exists():
            return f"/thumbnails/{fhash}.jpg"
        return None


def _resize(img, scale):
    import cv2
    h, w = img.shape[:2]
    return cv2.resize(img, (int(w * scale), int(h * scale)))


# ============================================================
# Background Analysis Daemon
#
# Runs automatically. Processes photos one by one with throttle.
# Pauses during import. Persists results to disk.
# ============================================================

import json
import time
import threading
from config import DATA_DIR

ANALYSIS_DB = DATA_DIR / "analysis_results.json"
THROTTLE_SECONDS = 3  # seconds between photos — gentle on CPU


class AnalysisDaemon:
    """Background analysis worker. Processes photos gradually using idle time."""

    def __init__(self):
        self.analyzer = PhotoAnalyzer()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # State
        self._status = "idle"       # idle / running / paused / importing
        self._paused = False
        self._stop_flag = False
        self._queue: list[str] = []  # file paths waiting to be analyzed
        self._total_queued = 0
        self._processed = 0
        self._current_file = ""

        # Persisted results: {filepath: per-photo analysis result}
        self._results: dict[str, dict] = {}
        self._load_db()

    # ---- Persistence ----

    def _load_db(self):
        try:
            if ANALYSIS_DB.exists():
                with open(ANALYSIS_DB) as f:
                    self._results = json.load(f)
        except Exception:
            self._results = {}

    def _save_db(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(ANALYSIS_DB, 'w') as f:
                # Don't save embeddings (too large for JSON)
                slim = {}
                for path, r in self._results.items():
                    entry = {k: v for k, v in r.items() if k != 'clip_embedding'}
                    # Also strip face embeddings
                    if 'faces' in entry:
                        entry['faces'] = [
                            {k: v for k, v in face.items() if k != 'embedding'}
                            for face in entry['faces']
                        ]
                    slim[path] = entry
                json.dump(slim, f, ensure_ascii=False, default=str)
        except Exception:
            pass

    # ---- Queue management ----

    def enqueue(self, file_paths: list[str]):
        """Add files to the analysis queue. Skips already-analyzed files."""
        with self._lock:
            new = [fp for fp in file_paths if fp not in self._results and fp not in self._queue]
            self._queue.extend(new)
            self._total_queued += len(new)

        # Auto-start if not running
        if new and self._status in ("idle", "paused"):
            self.start()

    def enqueue_directory(self, directory: str):
        """Scan a directory and enqueue all image files."""
        file_paths = []
        for root, _, files in os.walk(directory):
            for fname in files:
                ext = Path(fname).suffix.lower()
                if ext in JPEG_EXTENSIONS or ext in RAW_EXTENSIONS:
                    file_paths.append(str(Path(root) / fname))
        self.enqueue(file_paths)

    # ---- Controls ----

    def start(self):
        """Start or resume background processing."""
        self._paused = False
        self._stop_flag = False
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def pause(self):
        """Pause processing (can resume later)."""
        self._paused = True
        self._status = "paused"

    def resume(self):
        """Resume from pause."""
        self._paused = False
        self.start()

    def stop(self):
        """Stop processing and clear queue."""
        self._stop_flag = True
        self._paused = False
        with self._lock:
            self._queue.clear()
        self._status = "idle"

    def notify_import_start(self):
        """Called when import begins — pause analysis to save resources."""
        if self._status == "running":
            self._paused = True
            self._status = "importing"

    def notify_import_done(self, imported_files: list[str]):
        """Called when import finishes — enqueue new files and resume."""
        self._status = "idle"
        self._paused = False
        # Enqueue the newly imported files
        image_files = [
            fp for fp in imported_files
            if Path(fp).suffix.lower() in JPEG_EXTENSIONS | RAW_EXTENSIONS
        ]
        if image_files:
            self.enqueue(image_files)

    # ---- Background worker ----

    def _worker(self):
        """Main background loop. Processes one photo at a time with throttling."""
        self._status = "running"

        while True:
            # Check stop
            if self._stop_flag:
                self._status = "idle"
                return

            # Check pause
            if self._paused:
                self._status = "paused" if self._status != "importing" else "importing"
                time.sleep(1)
                continue

            # Get next file
            with self._lock:
                if not self._queue:
                    # Nothing left — done
                    self._status = "idle"
                    self._current_file = ""
                    self._save_db()
                    return
                filepath = self._queue.pop(0)

            # Skip if already analyzed or file gone
            if filepath in self._results or not os.path.exists(filepath):
                self._processed += 1
                continue

            # Analyze
            self._status = "running"
            self._current_file = Path(filepath).name

            try:
                result = self.analyzer.analyze_photo(filepath)
                # Store result (without large embeddings for persistence)
                self._results[filepath] = result
                self._processed += 1

                # Save periodically (every 10 photos)
                if self._processed % 10 == 0:
                    self._save_db()
            except Exception:
                self._processed += 1

            # Throttle — be gentle on CPU
            time.sleep(THROTTLE_SECONDS)

        self._status = "idle"
        self._save_db()

    # ---- State for API ----

    def get_state(self) -> dict:
        with self._lock:
            pending = len(self._queue)

        analyzed_count = len(self._results)

        return {
            'status': self._status,
            'analyzed': analyzed_count,
            'pending': pending,
            'processed_this_session': self._processed,
            'current_file': self._current_file,
            'throttle_seconds': THROTTLE_SECONDS,
        }

    def get_results(self) -> dict:
        """Build aggregated results from all analyzed photos."""
        all_results = list(self._results.values())
        if not all_results:
            return {
                'status': self._status,
                'total': 0,
                'scene_groups': [],
                'face_groups': [],
                'quality_issues': [],
                'similar_groups': [],
            }

        return self.analyzer.analyze_batch_from_results(all_results)

    def get_analyzed_count(self) -> int:
        return len(self._results)


# Add a method to PhotoAnalyzer that works from pre-computed results
# (no re-processing, just aggregation)

def _aggregate_results(self, all_results: list) -> dict:
    """Aggregate pre-computed per-photo results into summary."""
    # Scene groups
    scene_counts = {}
    for r in all_results:
        scene = r.get('scene')
        if scene:
            scene_counts.setdefault(scene, []).append(r)

    scene_groups = []
    for cat, photos in sorted(scene_counts.items(), key=lambda x: -len(x[1])):
        scene_groups.append({
            'category': cat,
            'count': len(photos),
            'sample_paths': [p['path'] for p in photos[:6]],
            'sample_thumbs': [p.get('thumbnail_url') for p in photos[:6]],
        })

    # Face clustering
    face_groups = self._cluster_faces(all_results)

    # Quality issues
    quality_issues = []
    for r in all_results:
        q = r.get('quality', {})
        if q.get('is_blurry'):
            quality_issues.append({
                'path': r['path'], 'filename': r.get('filename', ''),
                'thumbnail_url': r.get('thumbnail_url'),
                'issue': 'blurry', 'issue_zh': '模糊',
                'detail': f"Score: {q.get('blur_score', '?')}",
            })
        if q.get('is_overexposed'):
            quality_issues.append({
                'path': r['path'], 'filename': r.get('filename', ''),
                'thumbnail_url': r.get('thumbnail_url'),
                'issue': 'overexposed', 'issue_zh': '过曝',
                'detail': f"{q.get('overexposed_ratio', 0):.1%}",
            })
        if q.get('is_underexposed'):
            quality_issues.append({
                'path': r['path'], 'filename': r.get('filename', ''),
                'thumbnail_url': r.get('thumbnail_url'),
                'issue': 'underexposed', 'issue_zh': '欠曝',
                'detail': f"{q.get('underexposed_ratio', 0):.1%}",
            })

    return {
        'status': 'completed',
        'total': len(all_results),
        'scene_groups': scene_groups,
        'face_groups': face_groups,
        'quality_issues': quality_issues,
        'similar_groups': [],  # skip similarity for aggregation (needs embeddings)
    }

PhotoAnalyzer.analyze_batch_from_results = _aggregate_results


# ============================================================
# Global daemon instance
# ============================================================

_daemon: Optional[AnalysisDaemon] = None


def get_daemon() -> AnalysisDaemon:
    global _daemon
    if _daemon is None:
        _daemon = AnalysisDaemon()
    return _daemon


def get_analysis_state() -> dict:
    return get_daemon().get_state()


def get_analysis_results() -> dict:
    return get_daemon().get_results()


def run_analysis(directory: str):
    """Enqueue a directory for background analysis."""
    get_daemon().enqueue_directory(directory)


def describe_single(filepath: str) -> Optional[str]:
    """On-demand VLM description for a single photo."""
    return get_daemon().analyzer.describe_photo(filepath)

import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

import numpy as np

from app.config import Config

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import mediapipe as mp
except ImportError:
    mp = None

try:
    from insightface.app import FaceAnalysis
except ImportError:
    FaceAnalysis = None


_PROJECTION_CACHE: Dict[int, np.ndarray] = {}

_arcface = None
_arcface_lock = threading.Lock()

# One MediaPipe detector per worker thread (see landmarks._face_mesh).
_local = threading.local()


def _face_detector():
    detector = getattr(_local, "detector", None)
    if detector is None:
        detector = mp.solutions.face_detection.FaceDetection(
            min_detection_confidence=Config.FACE_DETECTION_MIN_CONFIDENCE
        )
        _local.detector = detector
    return detector


def _arcface_model():
    """Load the ArcFace pipeline once; None when insightface is unavailable."""
    global _arcface
    if _arcface is None and FaceAnalysis is not None:
        with _arcface_lock:
            if _arcface is None:
                model = FaceAnalysis(
                    name=Config.ARCFACE_MODEL_PACK,
                    root=os.path.expanduser(Config.ARCFACE_MODEL_ROOT),
                    allowed_modules=["detection", "recognition"],
                    providers=["CPUExecutionProvider"],
                )
                model.prepare(ctx_id=-1, det_size=Config.ARCFACE_DET_SIZE)
                _arcface = model
    return _arcface


def _projection_matrix(dim: int) -> np.ndarray:
    cached = _PROJECTION_CACHE.get(dim)
    if cached is None:
        rng = np.random.default_rng(Config.SIMHASH_SEED + dim)
        cached = rng.standard_normal((Config.SIMHASH_BITS, dim))
        _PROJECTION_CACHE[dim] = cached
    return cached


class FaceRecognizer:

    @staticmethod
    def locate_face(image: np.ndarray) -> Dict[str, Any]:
        if mp is None:
            return {"detected": True, "confidence": 0.5, "bbox": (0.0, 0.0, 1.0, 1.0)}

        results = _face_detector().process(image)

        if not results.detections:
            return {"detected": False, "confidence": 0.0, "bbox": None}

        best = max(results.detections, key=lambda d: d.score[0])
        box = best.location_data.relative_bounding_box
        return {
            "detected": True,
            "confidence": float(best.score[0]),
            "bbox": (box.xmin, box.ymin, box.width, box.height),
        }

    @staticmethod
    def warm_up() -> None:
        """Load ArcFace and run it once so the first real request is fast."""
        try:
            model = _arcface_model()
            if model is not None:
                model.get(np.zeros((112, 112, 3), dtype=np.uint8))
        except Exception:
            logger.exception("ArcFace warm-up failed; face matching will fail")

    @staticmethod
    def encode_face(
        image: np.ndarray,
        bbox: Optional[Tuple[float, float, float, float]],
    ) -> Optional[np.ndarray]:
        """
        512-d ArcFace embedding of the face MediaPipe found, or None.

        There is deliberately no weaker fallback encoder: at the ArcFace match
        threshold, a cruder embedding would score different people as the
        same, so callers must treat None as "could not verify".
        """
        try:
            model = _arcface_model()
        except Exception:
            logger.exception("ArcFace model failed to load")
            return None
        if model is None or cv2 is None:
            return None

        bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        faces = model.get(bgr)
        if not faces:
            # The detector misses faces that fill the whole frame, as in a
            # tight crop; give it some margin and try once more.
            height, width = bgr.shape[:2]
            pad_y, pad_x = height // 2, width // 2
            padded = cv2.copyMakeBorder(
                bgr, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT
            )
            faces = model.get(padded)
            if faces:
                for face in faces:
                    face.bbox = face.bbox - np.array([pad_x, pad_y, pad_x, pad_y])
        if not faces:
            return None

        return FaceRecognizer._pick_face(faces, bbox, image.shape).normed_embedding

    @staticmethod
    def _pick_face(faces, bbox, shape):
        """The face closest to MediaPipe's detection, else the largest."""
        if bbox is None:
            return max(
                faces,
                key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
            )
        height, width = shape[:2]
        x, y, w, h = bbox
        target = np.array([(x + w / 2) * width, (y + h / 2) * height])
        return min(
            faces,
            key=lambda f: np.linalg.norm(
                np.array([(f.bbox[0] + f.bbox[2]) / 2, (f.bbox[1] + f.bbox[3]) / 2])
                - target
            ),
        )

    @staticmethod
    def to_simhash(embedding: np.ndarray) -> str:
        flat = embedding.flatten().astype(np.float64)
        norm = np.linalg.norm(flat)
        if norm > 0:
            flat /= norm

        planes = _projection_matrix(flat.size)
        signs = (planes @ flat) > 0
        packed = np.packbits(signs.astype(np.uint8))
        return packed.tobytes().hex()

    @staticmethod
    def hamming_similarity(template_a: str, template_b: str) -> float:
        try:
            a = np.unpackbits(np.frombuffer(bytes.fromhex(template_a), dtype=np.uint8))
            b = np.unpackbits(np.frombuffer(bytes.fromhex(template_b), dtype=np.uint8))
        except (ValueError, TypeError):
            return 0.0

        if a.size != b.size or a.size == 0:
            return 0.0

        distance = int(np.count_nonzero(a != b))
        return 1.0 - distance / a.size
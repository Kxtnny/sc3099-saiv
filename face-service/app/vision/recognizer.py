import logging
from typing import Any, Dict, Optional, Tuple

import numpy as np

from app.config import Config
from app.vision.imaging import crop_relative, resize_square

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
    import face_recognition
except ImportError:
    face_recognition = None


_PROJECTION_CACHE: Dict[int, np.ndarray] = {}


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

        detector = mp.solutions.face_detection.FaceDetection(
            min_detection_confidence=Config.FACE_DETECTION_MIN_CONFIDENCE
        )
        with detector:
            results = detector.process(image)

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
    def encode_face(
        image: np.ndarray,
        bbox: Optional[Tuple[float, float, float, float]],
    ) -> np.ndarray:
        if face_recognition is not None and bbox is not None:
            encoding = FaceRecognizer._dlib_encode(image, bbox)
            if encoding is not None:
                return encoding
        return FaceRecognizer._gradient_encode(image, bbox)

    @staticmethod
    def _dlib_encode(
        image: np.ndarray,
        bbox: Tuple[float, float, float, float],
    ) -> Optional[np.ndarray]:
        height, width = image.shape[:2]
        x, y, w, h = bbox
        location = (
            max(0, int(y * height)),
            min(width, int((x + w) * width)),
            min(height, int((y + h) * height)),
            max(0, int(x * width)),
        )

        try:
            encodings = face_recognition.face_encodings(
                image, known_face_locations=[location]
            )
        except Exception:
            logger.debug("dlib encoding failed with location hint", exc_info=True)
            encodings = []

        if not encodings:
            try:
                encodings = face_recognition.face_encodings(image)
            except Exception:
                logger.debug("dlib full-image search failed", exc_info=True)
                encodings = []

        return encodings[0] if encodings else None

    @staticmethod
    def _gradient_encode(
        image: np.ndarray,
        bbox: Optional[Tuple[float, float, float, float]],
    ) -> np.ndarray:
        region = crop_relative(image, bbox) if bbox else image
        try:
            region = resize_square(region, Config.FALLBACK_EMBEDDING_SIZE)
        except Exception:
            region = image

        if cv2 is not None:
            gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY).astype(np.float64)
            gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
            return np.sqrt(gx * gx + gy * gy)

        pixels = region.astype(np.float64)
        return pixels - pixels.mean()

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
from typing import Any, Dict

import numpy as np

from app.config import Config

try:
    import mediapipe as mp
except ImportError:
    mp = None


_NOSE_TIP = 1
_LEFT_EYE = (33, 160, 158, 133, 153, 144)
_RIGHT_EYE = (362, 385, 387, 263, 373, 380)
_LEFT_EYE_OUTER = 33
_RIGHT_EYE_OUTER = 263
_MOUTH_UPPER_INNER = 13
_MOUTH_LOWER_INNER = 14
_MOUTH_LEFT_CORNER = 78
_MOUTH_RIGHT_CORNER = 308

_MIN_LANDMARKS_FOR_COMPLETE_MESH = 400


def _landmark_list(image: np.ndarray):
    if mp is None:
        return None

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        min_detection_confidence=Config.FACE_DETECTION_MIN_CONFIDENCE,
    ) as mesh:
        result = mesh.process(image)
        if not result.multi_face_landmarks:
            return None
        return list(result.multi_face_landmarks[0].landmark)


def _distance(a, b) -> float:
    return float(np.hypot(a.x - b.x, a.y - b.y))


def _eye_aspect_ratio(lms, indices) -> float:
    p1, p2, p3, p4, p5, p6 = (lms[i] for i in indices)
    vertical = _distance(p2, p6) + _distance(p3, p5)
    horizontal = _distance(p1, p4)
    return vertical / (2.0 * horizontal) if horizontal > 1e-6 else 0.0


def _mouth_aspect_ratio(lms) -> float:
    vertical = _distance(lms[_MOUTH_UPPER_INNER], lms[_MOUTH_LOWER_INNER])
    horizontal = _distance(lms[_MOUTH_LEFT_CORNER], lms[_MOUTH_RIGHT_CORNER])
    return vertical / horizontal if horizontal > 1e-6 else 0.0


def _head_turn_ratio(lms) -> float:
    face_width = abs(lms[_RIGHT_EYE_OUTER].x - lms[_LEFT_EYE_OUTER].x)
    if face_width < 1e-6:
        return 0.0
    midpoint = (lms[_LEFT_EYE_OUTER].x + lms[_RIGHT_EYE_OUTER].x) / 2.0
    return abs(lms[_NOSE_TIP].x - midpoint) / face_width


def measure(image: np.ndarray) -> Dict[str, Any]:
    lms = _landmark_list(image)
    if lms is None:
        return {
            "face_present": False,
            "landmark_count": 0,
            "nose_tip_z": 0.0,
            "ear": 0.0,
            "mar": 0.0,
            "head_turn_ratio": 0.0,
        }

    left_ear = _eye_aspect_ratio(lms, _LEFT_EYE)
    right_ear = _eye_aspect_ratio(lms, _RIGHT_EYE)

    return {
        "face_present": len(lms) >= _MIN_LANDMARKS_FOR_COMPLETE_MESH,
        "landmark_count": len(lms),
        "nose_tip_z": float(lms[_NOSE_TIP].z),
        "ear": round((left_ear + right_ear) / 2.0, 4),
        "mar": round(_mouth_aspect_ratio(lms), 4),
        "head_turn_ratio": round(_head_turn_ratio(lms), 4),
    }


def depth_quality(nose_tip_z: float) -> str:
    magnitude = abs(nose_tip_z)
    if magnitude > Config.DEPTH_GOOD_THRESHOLD:
        return "good"
    if magnitude > Config.DEPTH_MODERATE_THRESHOLD:
        return "moderate"
    return "poor"
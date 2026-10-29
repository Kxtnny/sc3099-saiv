import logging
from typing import Any, Dict, List, Tuple
import numpy as np
from app.config import Config
from app.vision import landmarks

logger = logging.getLogger(__name__)
try:
    import cv2
except ImportError:
    cv2 = None

class LivenessDetector:

    @staticmethod
    def _texture_score(image: np.ndarray) -> float:
        if cv2 is None: return min(1.0, float(image.std()) / Config.TEXTURE_VARIANCE_SCALE)
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        return min(1.0, float(cv2.Laplacian(gray, cv2.CV_64F).var()) / Config.TEXTURE_VARIANCE_SCALE)

    @staticmethod
    def _color_score(image: np.ndarray) -> float:
        channels = image.reshape(-1, 3).std(axis=0)
        return min(1.0, float(channels.mean()) / Config.COLOR_STDDEV_SCALE)

    @staticmethod
    def _depth_component(quality: str) -> float:
        if quality == "good": return Config.LIVENESS_DEPTH_WEIGHT
        if quality == "moderate": return Config.LIVENESS_DEPTH_WEIGHT * 0.5
        return 0.0

    @staticmethod
    def _specular_score(image: np.ndarray) -> float:
        try: ratio = float((image.max(axis=2) > 220).mean())
        except Exception: return 0.5
        if 0.002 <= ratio <= 0.03: return 1.0
        if ratio < 0.0005: return 0.1
        if ratio > 0.06: return 0.2
        return 0.5

    @staticmethod
    def _texture_frequency_score(image: np.ndarray) -> float:
        if cv2 is None: return 0.5
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).astype(np.float64)
            high = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            low = float((gray - cv2.GaussianBlur(gray, (31, 31), 0)).var())
            ratio = high / (low + 1e-6)
        except Exception: return 0.5
        if 50 < high < 500 and 0.5 < ratio < 4.0: return 1.0
        if high < 30: return 0.2
        if high > 1000: return 0.3
        return 0.5

    @staticmethod
    def _colour_gamut_score(image: np.ndarray) -> float:
        if cv2 is None: return 0.5
        try: sat_mean = float(cv2.cvtColor(image, cv2.COLOR_RGB2HSV)[:, :, 1].mean())
        except Exception: return 0.5
        if 40 <= sat_mean <= 180: return 1.0
        if sat_mean < 30: return 0.3
        if sat_mean > 200: return 0.4
        return 0.7

    @staticmethod
    def _base_score(image: np.ndarray, metrics: Dict[str, Any]) -> float:
        return (
            LivenessDetector._depth_component(landmarks.depth_quality(metrics["nose_tip_z"])) +
            (Config.LIVENESS_MESH_WEIGHT if metrics["face_present"] else 0.0) +
            (LivenessDetector._texture_score(image) * Config.LIVENESS_TEXTURE_WEIGHT) +
            (LivenessDetector._color_score(image) * Config.LIVENESS_COLOR_WEIGHT) +
            (LivenessDetector._specular_score(image) * Config.LIVENESS_SPECULAR_WEIGHT) +
            (LivenessDetector._texture_frequency_score(image) * Config.LIVENESS_FREQUENCY_WEIGHT) +
            (LivenessDetector._colour_gamut_score(image) * Config.LIVENESS_GAMUT_WEIGHT)
        )

    @staticmethod
    def score_single_frame(image: np.ndarray, challenge: str) -> Dict[str, Any]:
        metrics = landmarks.measure(image)
        if not metrics["face_present"]: return LivenessDetector._failed(challenge, reason="no_face")
        base = LivenessDetector._base_score(image, metrics)
        bonus, action_ok = LivenessDetector._single_frame_bonus(metrics, challenge)
        score = min(1.0, base + bonus)
        return {
            "liveness_score": round(score, 4),
            "liveness_passed": LivenessDetector._passes(score, challenge, action_ok),
            "challenge_type": challenge,
            "details": LivenessDetector._details(image, metrics, challenge, action_ok),
        }

    @staticmethod
    def _single_frame_bonus(metrics: Dict[str, Any], challenge: str) -> Tuple[float, bool]:
        if challenge == "blink" and metrics["ear"] < Config.BLINK_EAR_THRESHOLD: return Config.ACTIVE_CHALLENGE_BONUS, True
        if challenge == "head_turn" and metrics["head_turn_ratio"] > Config.HEAD_TURN_RATIO_THRESHOLD: return Config.ACTIVE_CHALLENGE_BONUS, True
        if challenge == "mouth_open" and metrics["mar"] > Config.MOUTH_OPEN_MAR_THRESHOLD: return Config.ACTIVE_CHALLENGE_BONUS, True
        if challenge == "passive" and metrics["ear"] < Config.BLINK_EAR_THRESHOLD: return Config.PASSIVE_BLINK_BONUS, True
        return 0.0, False

    @staticmethod
    def score_sequence(frames: List[np.ndarray], challenge: str) -> Dict[str, Any]:
        if not frames: return LivenessDetector._failed(challenge, reason="no_frames")
        per_frame = [landmarks.measure(f) for f in frames]
        face_indices = [i for i, m in enumerate(per_frame) if m["face_present"]]
        if not face_indices: return LivenessDetector._failed(challenge, reason="no_face")

        base = float(np.mean([LivenessDetector._base_score(frames[i], per_frame[i]) for i in face_indices]))
        ears = [per_frame[i]["ear"] for i in face_indices]
        ratios = [per_frame[i]["head_turn_ratio"] for i in face_indices]
        mars = [per_frame[i]["mar"] for i in face_indices]

        if challenge == "blink": detected, extra = LivenessDetector._blink_transition(ears)
        elif challenge == "head_turn": detected, extra = LivenessDetector._head_turn_sustained(ratios)
        elif challenge == "mouth_open": detected, extra = LivenessDetector._mouth_open_sustained(mars)
        else: detected, extra = LivenessDetector._passive_blink(ears)

        bonus = (Config.PASSIVE_BLINK_BONUS if challenge == "passive" else Config.ACTIVE_CHALLENGE_BONUS) if detected else 0.0
        score = min(1.0, base + bonus)
        rep_index = face_indices[0]
        
        details = LivenessDetector._details(frames[rep_index], per_frame[rep_index], challenge, detected)
        details.update({"frame_count": len(frames), "face_frame_count": len(face_indices), **extra})

        return {
            "liveness_score": round(score, 4),
            "liveness_passed": LivenessDetector._passes(score, challenge, detected),
            "challenge_type": challenge,
            "details": details,
        }

    @staticmethod
    def _blink_transition(ears: List[float]) -> Tuple[bool, Dict[str, Any]]:
        if not ears: return False, {"min_ear": 1.0, "closed_frames": 0}
        baseline = float(np.mean(ears[:max(3, len(ears) // 4)]))
        threshold = max(Config.BLINK_EAR_THRESHOLD, baseline * Config.BLINK_EAR_BASELINE_RATIO)
        closed_run = max_closed = 0
        saw_open_first = False

        def accept() -> bool: return saw_open_first and closed_run >= Config.BLINK_MIN_CLOSED_FRAMES

        for ear in ears:
            if ear >= threshold:
                if accept(): return True, {"min_ear": round(min(ears), 4), "closed_frames": closed_run, "baseline_ear": round(baseline, 4), "threshold_used": round(threshold, 4)}
                closed_run = 0; saw_open_first = True
            else:
                closed_run += 1; max_closed = max(max_closed, closed_run)
        if accept(): return True, {"min_ear": round(min(ears), 4), "closed_frames": closed_run, "baseline_ear": round(baseline, 4), "threshold_used": round(threshold, 4)}
        return False, {"min_ear": round(min(ears), 4), "closed_frames": max_closed, "baseline_ear": round(baseline, 4), "threshold_used": round(threshold, 4)}

    @staticmethod
    def _head_turn_sustained(ratios: List[float]) -> Tuple[bool, Dict[str, Any]]:
        triggered = sum(1 for r in ratios if r > Config.HEAD_TURN_RATIO_THRESHOLD)
        return triggered >= Config.HEAD_TURN_MIN_FRAMES, {"max_ratio": round(max(ratios), 4) if ratios else 0.0, "turned_frames": triggered}

    @staticmethod
    def _mouth_open_sustained(mars: List[float]) -> Tuple[bool, Dict[str, Any]]:
        longest = current = 0
        for mar in mars:
            if mar > Config.MOUTH_OPEN_MAR_THRESHOLD: current += 1; longest = max(longest, current)
            else: current = 0
        return longest >= Config.MOUTH_OPEN_MIN_FRAMES, {"max_mar": round(max(mars), 4) if mars else 0.0, "open_frames": longest}

    @staticmethod
    def _passive_blink(ears: List[float]) -> Tuple[bool, Dict[str, Any]]:
        min_ear = min(ears) if ears else 1.0
        return min_ear < Config.BLINK_EAR_THRESHOLD, {"min_ear": round(min_ear, 4)}

    @staticmethod
    def _passes(score: float, challenge: str, action_detected: bool) -> bool:
        if challenge != "passive" and not action_detected: return False
        return score >= Config.LIVENESS_THRESHOLD

    @staticmethod
    def _details(image: np.ndarray, metrics: Dict[str, Any], challenge: str, action_detected: bool) -> Dict[str, Any]:
        ear = float(metrics.get("ear", 0.0)); mar = float(metrics.get("mar", 0.0))
        ratio = float(metrics.get("head_turn_ratio", 0.0)); nose_z = float(metrics.get("nose_tip_z", 0.0))
        return {
            "face_mesh_complete": metrics.get("face_present", False), "landmark_count": metrics.get("landmark_count", 0),
            "nose_tip_z": nose_z, "depth_quality": landmarks.depth_quality(nose_z),
            "texture_analysis_score": round(LivenessDetector._texture_score(image), 4),
            "color_distribution_score": round(LivenessDetector._color_score(image), 4),
            "specular_score": round(LivenessDetector._specular_score(image), 4),
            "frequency_score": round(LivenessDetector._texture_frequency_score(image), 4),
            "gamut_score": round(LivenessDetector._colour_gamut_score(image), 4),
            "challenge_type": challenge, "action_detected": action_detected,
            "blink_detected": ear < Config.BLINK_EAR_THRESHOLD, "head_turned": ratio > Config.HEAD_TURN_RATIO_THRESHOLD,
            "mouth_open": mar > Config.MOUTH_OPEN_MAR_THRESHOLD, "ear": round(ear, 4), "head_turn_ratio": round(ratio, 4), "mar": round(mar, 4),
        }

    @staticmethod
    def _failed(challenge: str, reason: str) -> Dict[str, Any]:
        return {"liveness_score": 0.0, "liveness_passed": False, "challenge_type": challenge, "details": {
                "reason": reason, "face_mesh_complete": False, "landmark_count": 0, "nose_tip_z": 0.0, "depth_quality": "poor",
                "texture_analysis_score": 0.0, "color_distribution_score": 0.0, "specular_score": 0.0, "frequency_score": 0.0,
                "gamut_score": 0.0, "challenge_type": challenge, "action_detected": False, "blink_detected": False, "head_turned": False,
                "mouth_open": False, "ear": 0.0, "head_turn_ratio": 0.0, "mar": 0.0}}
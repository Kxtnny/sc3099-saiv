from typing import Any, Dict, List, Optional

from app.config import Config
from app.support.netcheck import detect_vpn_or_proxy


class RiskEngine:

    _RECOMMENDATIONS = {
        "liveness": "Improve lighting and keep your face fully in frame",
        "face_match": "Re-enrol or present a clearer, front-facing photo",
        "device": "Use a trusted device with valid attestation",
        "network": "Disable any VPN or proxy before checking in",
        "geolocation": "Enable precise location services",
    }

    _TRIGGER_THRESHOLDS = {
        "liveness": 0.15,
        "face_match": 0.15,
        "device": 0.10,
        "network": 0.10,
        "geolocation": 0.10,
    }

    @staticmethod
    def evaluate(payload: Dict[str, Any]) -> Dict[str, Any]:
        components = {
            "liveness": RiskEngine._liveness_risk(payload.get("liveness_score")),
            "face_match": RiskEngine._face_match_risk(payload.get("face_match_score")),
            "device": RiskEngine._device_risk(payload),
            "network": RiskEngine._network_risk(payload),
            "geolocation": RiskEngine._geolocation_risk(payload.get("geolocation")),
        }

        weighted = {
            name: round(value * Config.RISK_WEIGHTS[name], 4)
            for name, value in components.items()
        }
        total = round(sum(weighted.values()), 4)

        return {
            "risk_score": total,
            "risk_level": RiskEngine._level(total),
            "pass_threshold": total < Config.RISK_THRESHOLD,
            "risk_threshold": Config.RISK_THRESHOLD,
            "signal_breakdown": weighted,
            "recommendations": RiskEngine._recommendations(weighted),
        }

    @staticmethod
    def _liveness_risk(score: Optional[float]) -> float:
        return 1.0 - score if score is not None else 0.0

    @staticmethod
    def _face_match_risk(score: Optional[float]) -> float:
        return 1.0 - score if score is not None else 0.0

    @staticmethod
    def _device_risk(payload: Dict[str, Any]) -> float:
        risk = 0.0
        signature = payload.get("device_signature")
        public_key = payload.get("device_public_key")

        if not signature:
            risk = max(risk, 0.5)
        elif len(signature) < 16:
            risk = max(risk, 0.4)

        if public_key and not public_key.startswith("-----BEGIN"):
            risk = max(risk, 0.3)
        return risk

    @staticmethod
    def _network_risk(payload: Dict[str, Any]) -> float:
        ip_address = payload.get("ip_address")
        user_agent = payload.get("user_agent")
        if not ip_address and not user_agent:
            return 0.0
        flagged, confidence = detect_vpn_or_proxy(ip_address, user_agent)
        return confidence if flagged else 0.0

    @staticmethod
    def _geolocation_risk(geo: Optional[Dict[str, Any]]) -> float:
        if geo is None or geo.get("accuracy") is None:
            return 0.0
        accuracy = geo["accuracy"]
        if accuracy > Config.GEO_VERY_LOW_ACCURACY_METERS:
            return 0.8
        if accuracy < Config.GEO_SPOOF_ACCURACY_METERS:
            return 0.2
        if accuracy > Config.GEO_MODERATE_ACCURACY_METERS:
            return 0.3
        return 0.0

    @staticmethod
    def _level(total: float) -> str:
        if total < 0.30:
            return "LOW"
        if total < 0.50:
            return "MEDIUM"
        if total < 0.70:
            return "HIGH"
        return "CRITICAL"

    @staticmethod
    def _recommendations(weighted: Dict[str, float]) -> List[str]:
        return [
            RiskEngine._RECOMMENDATIONS[name]
            for name, value in weighted.items()
            if value >= RiskEngine._TRIGGER_THRESHOLDS[name]
        ]
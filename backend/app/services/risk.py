"""
Risk scoring: fuse multiple signals into a single 0-1 score and a decision.

Weights follow docs/SECURITY-REQUIREMENTS.md. Each contributing signal is
recorded so an instructor reviewing a flagged check-in can see exactly why it
was flagged.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.enums import CheckInStatus, RiskLevel, SignalSeverity, SignalType

# How much each signal adds to the risk score when it fires.
SIGNAL_WEIGHTS: Dict[SignalType, float] = {
    SignalType.GEO_OUT_OF_BOUNDS: 0.40,
    SignalType.IMPOSSIBLE_TRAVEL: 0.40,
    SignalType.GEO_ACCURACY_LOW: 0.10,
    SignalType.VPN_DETECTED: 0.15,
    SignalType.PROXY_DETECTED: 0.15,
    SignalType.SUSPICIOUS_IP: 0.10,
    SignalType.DEVICE_UNKNOWN: 0.15,
    SignalType.DEVICE_EMULATOR: 0.30,
    SignalType.DEVICE_ROOTED: 0.25,
    SignalType.ATTESTATION_FAILED: 0.20,
    SignalType.RAPID_SUCCESSION: 0.20,
    SignalType.UNUSUAL_TIME: 0.05,
    SignalType.PATTERN_ANOMALY: 0.15,
    SignalType.LIVENESS_FAILED: 0.35,
    SignalType.LIVENESS_LOW_CONFIDENCE: 0.15,
    SignalType.DEEPFAKE_SUSPECTED: 0.40,
    SignalType.REPLAY_SUSPECTED: 0.40,
    SignalType.FACE_MATCH_FAILED: 0.30,
    SignalType.FACE_MATCH_LOW_CONFIDENCE: 0.15,
}

SIGNAL_SEVERITY: Dict[SignalType, SignalSeverity] = {
    SignalType.GEO_OUT_OF_BOUNDS: SignalSeverity.HIGH,
    SignalType.IMPOSSIBLE_TRAVEL: SignalSeverity.HIGH,
    SignalType.GEO_ACCURACY_LOW: SignalSeverity.LOW,
    SignalType.VPN_DETECTED: SignalSeverity.MEDIUM,
    SignalType.PROXY_DETECTED: SignalSeverity.MEDIUM,
    SignalType.SUSPICIOUS_IP: SignalSeverity.LOW,
    SignalType.DEVICE_UNKNOWN: SignalSeverity.MEDIUM,
    SignalType.DEVICE_EMULATOR: SignalSeverity.HIGH,
    SignalType.DEVICE_ROOTED: SignalSeverity.HIGH,
    SignalType.ATTESTATION_FAILED: SignalSeverity.MEDIUM,
    SignalType.RAPID_SUCCESSION: SignalSeverity.MEDIUM,
    SignalType.UNUSUAL_TIME: SignalSeverity.LOW,
    SignalType.PATTERN_ANOMALY: SignalSeverity.MEDIUM,
    SignalType.LIVENESS_FAILED: SignalSeverity.CRITICAL,
    SignalType.LIVENESS_LOW_CONFIDENCE: SignalSeverity.MEDIUM,
    SignalType.DEEPFAKE_SUSPECTED: SignalSeverity.CRITICAL,
    SignalType.REPLAY_SUSPECTED: SignalSeverity.CRITICAL,
    SignalType.FACE_MATCH_FAILED: SignalSeverity.HIGH,
    SignalType.FACE_MATCH_LOW_CONFIDENCE: SignalSeverity.MEDIUM,
}


@dataclass
class RiskAssessment:
    """Outcome of scoring one check-in."""

    score: float = 0.0
    signals: List[Dict[str, Any]] = field(default_factory=list)
    critical: bool = False

    def add(
        self,
        signal_type: SignalType,
        *,
        confidence: float = 1.0,
        details: Optional[Dict[str, Any]] = None,
        critical: bool = False,
    ) -> None:
        """Record a fired signal and add its weighted contribution."""
        weight = SIGNAL_WEIGHTS.get(signal_type, 0.1)
        severity = SIGNAL_SEVERITY.get(signal_type, SignalSeverity.MEDIUM)
        self.signals.append(
            {
                "type": signal_type.value,
                "severity": severity.value,
                "weight": round(weight, 4),
                "confidence": round(confidence, 4),
                "details": details or {},
            }
        )
        self.score = min(1.0, self.score + weight * confidence)
        if critical:
            self.critical = True

    @property
    def level(self) -> RiskLevel:
        """Bucket the score per SECURITY-REQUIREMENTS.md."""
        if self.score < 0.3:
            return RiskLevel.LOW
        if self.score < 0.5:
            return RiskLevel.MEDIUM
        if self.score < 0.7:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    def decide(self, threshold: float) -> CheckInStatus:
        """
        Map the score to a check-in outcome.

        Two things reject outright: a critical signal (failed liveness, or a
        location far outside the geofence), or a combined score in the
        CRITICAL band (>= 0.7 per SECURITY-REQUIREMENTS.md). Anything at or
        above the session threshold is flagged for instructor review.
        """
        if self.critical or self.score >= settings.RISK_REJECT_THRESHOLD:
            return CheckInStatus.REJECTED
        if self.score >= threshold:
            return CheckInStatus.FLAGGED
        return CheckInStatus.APPROVED

"""
Business metrics recorded where check-in decisions are made.

HTTP-level series (request counts, latency) live in main.py's middleware.
These answer the questions the dashboard's Grafana panels and the
flagged-rate alert ask, which an HTTP status code cannot: was a check-in
approved, flagged or rejected, and how risky did it look.

    checkin_decisions_total{decision="approved|flagged|rejected"}
    checkin_risk_score_bucket{decision=..., le=...}  (+ _sum, _count)
"""

from typing import Optional

from prometheus_client import Counter, Histogram

from app.enums import CheckInStatus

DECISIONS = (
    CheckInStatus.APPROVED.value,
    CheckInStatus.FLAGGED.value,
    CheckInStatus.REJECTED.value,
)

CHECKIN_DECISIONS = Counter(
    "checkin_decisions_total",
    "Check-in outcomes as decided by the risk engine or location rules",
    ["decision"],
)
CHECKIN_RISK_SCORE = Histogram(
    "checkin_risk_score",
    "Risk score of scored check-ins",
    ["decision"],
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

# Export every series at zero from startup so rate() and ratio queries work
# before the first flagged or rejected check-in.
for _decision in DECISIONS:
    CHECKIN_DECISIONS.labels(decision=_decision)
    CHECKIN_RISK_SCORE.labels(decision=_decision)


def record_checkin_decision(decision: str, risk_score: Optional[float] = None) -> None:
    """Count one decision; risk_score is None when rejected before scoring."""
    CHECKIN_DECISIONS.labels(decision=decision).inc()
    if risk_score is not None:
        CHECKIN_RISK_SCORE.labels(decision=decision).observe(risk_score)

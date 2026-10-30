"""
Device trust: a device earns trust from its owner's clean check-ins.

A clean check-in is one approved with a LOW risk score. Only the server promotes
a device automatically; admins can still grant or remove trust by hand.

Removing trust or revoking a device restarts the count from revoked_at, so the
device has to earn trust again from new check-ins rather than from its history.
"""

from typing import Dict, List

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from app.core.utils import utcnow
from app.enums import CheckInStatus, TrustScore
from app.models import CheckIn, Device
from app.services.risk import MEDIUM_RISK_FLOOR

CHECKINS_TO_EARN_TRUST = 3


def _clean_checkins(db: Session) -> Query:
    """Clean check-ins by each device's owner since its count last restarted."""
    return (
        db.query(CheckIn)
        .join(Device, Device.id == CheckIn.device_id)
        .filter(
            CheckIn.student_id == Device.user_id,
            CheckIn.status == CheckInStatus.APPROVED.value,
            CheckIn.risk_score < MEDIUM_RISK_FLOOR,
            or_(
                Device.revoked_at.is_(None),
                CheckIn.checked_in_at > Device.revoked_at,
            ),
        )
    )


def clean_checkin_count(db: Session, device: Device) -> int:
    """Count for one device. The check-in path calls this, so it must stay fast."""
    # student_id is indexed and device_id is not.
    return (
        _clean_checkins(db)
        .filter(
            CheckIn.student_id == device.user_id,
            CheckIn.device_id == device.id,
        )
        .count()
    )


def clean_checkin_counts(db: Session, devices: List[Device]) -> Dict[str, int]:
    """Counts for a page of devices, in one grouped query."""
    return dict(
        _clean_checkins(db)
        .with_entities(CheckIn.device_id, func.count(CheckIn.id))
        .filter(CheckIn.device_id.in_([d.id for d in devices]))
        .group_by(CheckIn.device_id)
        .all()
    )


def grant_trust(device: Device) -> None:
    device.is_trusted = True
    device.trust_score = TrustScore.HIGH.value


def reset_trust(device: Device) -> None:
    """Remove trust and restart the clean count from now."""
    device.is_trusted = False
    device.trust_score = TrustScore.LOW.value
    device.revoked_at = utcnow()

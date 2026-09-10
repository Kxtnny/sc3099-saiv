"""
Data retention: the 30-day auto-deletion policy.

Records carry a `scheduled_deletion_at` timestamp. Once it passes, this sweep
strips the personal data while keeping the rows themselves, because:

* check-ins are referenced by grading and appeals, so the attendance *fact*
  must survive even after the location and biometric hash are gone;
* users are referenced by check-ins and by the immutable audit log, so the
  row is anonymised rather than deleted, which satisfies the right to
  erasure without breaking referential integrity.

Audit logs are never touched - they are exempt from retention by design.
"""

import logging
from typing import Dict

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.core.utils import new_uuid, utcnow
from app.enums import AuditAction
from app.models import CheckIn, Device, User
from app.services.audit import log_action

logger = logging.getLogger(__name__)

ANONYMISED_DOMAIN = "anonymized.invalid"
ANONYMISED_NAME = "Deleted User"


def anonymise_user(user: User, db: Session) -> None:
    """Remove everything that identifies a person from a user row."""
    user.email = f"deleted-{user.id}@{ANONYMISED_DOMAIN}"
    user.full_name = ANONYMISED_NAME
    # An unguessable random password: the account can never be logged into.
    user.hashed_password = get_password_hash(new_uuid())
    user.face_embedding_hash = None
    user.face_enrolled = False
    user.camera_consent = False
    user.geolocation_consent = False
    user.is_active = False
    user.last_login_at = None
    user.scheduled_deletion_at = None  # marks the purge as done

    for device in db.query(Device).filter(Device.user_id == user.id):
        device.is_active = False
        device.is_trusted = False
        device.device_name = None
        device.public_key = None
        device.attestation_token = None
        device.revoked_at = utcnow()
        device.revocation_reason = "Owner account purged"


def scrub_checkin(checkin: CheckIn) -> None:
    """Drop location and biometric data; keep the attendance outcome."""
    checkin.latitude = None
    checkin.longitude = None
    checkin.location_accuracy_meters = None
    checkin.face_embedding_hash = None
    checkin.scheduled_deletion_at = None  # marks the scrub as done


def purge_expired(db: Session, *, actor_id: str = None) -> Dict[str, int]:
    """
    Scrub every record whose retention window has passed.

    Returns counts so the caller (the scheduler or an admin) can report on it.
    """
    now = utcnow()

    users = (
        db.query(User)
        .filter(User.scheduled_deletion_at.isnot(None), User.scheduled_deletion_at <= now)
        .all()
    )
    for user in users:
        anonymise_user(user, db)

    checkins = (
        db.query(CheckIn)
        .filter(
            CheckIn.scheduled_deletion_at.isnot(None),
            CheckIn.scheduled_deletion_at <= now,
        )
        .all()
    )
    for checkin in checkins:
        scrub_checkin(checkin)

    counts = {"users_anonymised": len(users), "checkins_scrubbed": len(checkins)}

    if users or checkins:
        log_action(
            db,
            AuditAction.DATA_PURGED,
            user_id=actor_id,
            resource_type="retention",
            details=counts,
        )
        logger.info("Retention sweep: %s", counts)

    db.commit()
    return counts


def pending_counts(db: Session) -> Dict[str, int]:
    """How much is queued for the next sweep, for the admin status view."""
    now = utcnow()
    return {
        "users_due": db.query(User)
        .filter(User.scheduled_deletion_at.isnot(None), User.scheduled_deletion_at <= now)
        .count(),
        "users_scheduled": db.query(User)
        .filter(User.scheduled_deletion_at.isnot(None))
        .count(),
        "checkins_due": db.query(CheckIn)
        .filter(
            CheckIn.scheduled_deletion_at.isnot(None),
            CheckIn.scheduled_deletion_at <= now,
        )
        .count(),
        "checkins_scheduled": db.query(CheckIn)
        .filter(CheckIn.scheduled_deletion_at.isnot(None))
        .count(),
    }


def run_sweep() -> Dict[str, int]:
    """Entry point for the background scheduler: opens its own session."""
    db = SessionLocal()
    try:
        return purge_expired(db)
    except Exception:  # noqa: BLE001 - the loop must survive a bad sweep
        logger.exception("Retention sweep failed")
        db.rollback()
        return {"users_anonymised": 0, "checkins_scrubbed": 0}
    finally:
        db.close()

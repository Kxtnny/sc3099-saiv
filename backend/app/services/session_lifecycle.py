"""
Session lifecycle: move sessions through their status on schedule.

A scheduled session goes active at scheduled_start, and an open session closes
once both scheduled_end and checkin_closes_at have passed. Instructors can
still act first: starting early or closing early is respected, because this
only ever moves a session forward and never touches a closed or cancelled one.
"""

import logging
from typing import Dict

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.utils import utcnow
from app.enums import AuditAction, SessionStatus
from app.models import AttendanceSession
from app.services.audit import log_action

logger = logging.getLogger(__name__)


def _record(db: Session, session: AttendanceSession) -> None:
    """Audit an automatic change; there is no acting user."""
    log_action(
        db,
        AuditAction.SESSION_UPDATED,
        resource_type="session",
        resource_id=session.id,
        details={"fields": ["status"], "status": session.status, "automatic": True},
    )


def advance_sessions(db: Session) -> Dict[str, int]:
    """Close finished sessions and start due ones, returning how many of each."""
    now = utcnow()

    finished = (
        db.query(AttendanceSession)
        .filter(
            AttendanceSession.status.in_(
                [SessionStatus.SCHEDULED.value, SessionStatus.ACTIVE.value]
            ),
            AttendanceSession.scheduled_end <= now,
            AttendanceSession.checkin_closes_at <= now,
        )
        .all()
    )
    for session in finished:
        session.status = SessionStatus.CLOSED.value
        session.actual_end = now
        _record(db, session)

    # Closed sessions are flushed above, so they no longer match as scheduled.
    db.flush()
    due = (
        db.query(AttendanceSession)
        .filter(
            AttendanceSession.status == SessionStatus.SCHEDULED.value,
            AttendanceSession.scheduled_start <= now,
        )
        .all()
    )
    for session in due:
        session.status = SessionStatus.ACTIVE.value
        session.actual_start = now
        _record(db, session)

    counts = {"started": len(due), "closed": len(finished)}
    if due or finished:
        logger.info("Session lifecycle: %s", counts)

    db.commit()
    return counts


def run_sweep() -> None:
    """Entry point for the background task, which must outlive any one failure."""
    db = SessionLocal()
    try:
        advance_sessions(db)
    except Exception:
        db.rollback()
        logger.exception("Session lifecycle sweep failed")
    finally:
        db.close()

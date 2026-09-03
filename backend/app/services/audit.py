"""
Audit logging.

Entries are append-only: written once and never updated or deleted, per
docs/SECURITY-REQUIREMENTS.md. Logging must never break the request it is
recording, so every failure here is swallowed and reported to the app log.
"""

import json
import logging
from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.enums import AuditAction
from app.models import AuditLog

logger = logging.getLogger(__name__)


def get_client_ip(request: Optional[Request]) -> Optional[str]:
    """Client IP, honouring X-Forwarded-For when behind a proxy."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_user_agent(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    agent = request.headers.get("user-agent")
    return agent[:500] if agent else None


def log_action(
    db: Session,
    action: AuditAction,
    *,
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    request: Optional[Request] = None,
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
    device_id: Optional[str] = None,
    commit: bool = False,
) -> Optional[AuditLog]:
    """
    Append an audit entry.

    By default the entry joins the caller's transaction (commit=False) so it is
    written atomically with the change it describes. Pass commit=True when
    recording an event that has no other database write, such as a failed
    login.
    """
    try:
        entry = AuditLog(
            user_id=user_id,
            action=action.value if isinstance(action, AuditAction) else str(action),
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            device_id=device_id,
            details=json.dumps(details, default=str) if details else None,
            success=success,
        )
        db.add(entry)
        if commit:
            db.commit()
        else:
            db.flush()
        return entry
    except Exception as exc:  # noqa: BLE001 - auditing must not break requests
        logger.error("Failed to write audit log for %s: %s", action, exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None

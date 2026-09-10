"""
Audit log access.

Admin-only, and read-only by design: there is no update or delete endpoint,
because the trail is append-only. The one write path records an event, it never
alters an existing one.
"""

import csv
import io
import json
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.utils import utcnow
from app.dependencies import paginate, require_admin
from app.enums import AuditAction
from app.models import AuditLog, User
from app.schemas.audit import AuditLogCreate, AuditLogResponse, AuditSummary
from app.schemas.common import PaginatedResponse
from app.services.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])


def _details(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {"raw": raw}


def _serialize(entry: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=entry.id,
        user_id=entry.user_id,
        user_email=entry.user.email if entry.user else None,
        action=entry.action,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        ip_address=entry.ip_address,
        user_agent=entry.user_agent,
        device_id=entry.device_id,
        details=_details(entry.details),
        success=entry.success,
        timestamp=entry.timestamp,
    )


@router.get("/summary", response_model=AuditSummary)
def audit_summary(
    days: int = Query(default=7, ge=1, le=365),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Aggregate view of recent activity, for the compliance dashboard."""
    since = utcnow() - timedelta(days=days)

    by_action = dict(
        db.query(AuditLog.action, func.count(AuditLog.id))
        .filter(AuditLog.timestamp >= since)
        .group_by(AuditLog.action)
        .all()
    )
    by_success = dict(
        db.query(AuditLog.success, func.count(AuditLog.id))
        .filter(AuditLog.timestamp >= since)
        .group_by(AuditLog.success)
        .all()
    )
    unique_users = (
        db.query(func.count(func.distinct(AuditLog.user_id)))
        .filter(AuditLog.timestamp >= since)
        .scalar()
        or 0
    )

    return AuditSummary(
        period_days=days,
        total_logs=sum(by_action.values()),
        by_action=by_action,
        by_success={
            "success": by_success.get(True, 0),
            "failure": by_success.get(False, 0),
        },
        unique_users=int(unique_users),
    )


@router.get("/export")
def export_audit_logs(
    request: Request,
    export_format: str = Query(default="json", alias="format", pattern="^(csv|json)$"),
    action: Optional[str] = Query(default=None, max_length=50),
    user_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(default=10000, ge=1, le=100000),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Export the audit trail for a compliance review.

    The export is itself audited, so a reviewer can see who pulled the trail
    and when.
    """
    query = db.query(AuditLog).options(joinedload(AuditLog.user))
    if action:
        query = query.filter(AuditLog.action == action)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)

    entries = query.order_by(AuditLog.timestamp).limit(limit).all()
    rows = [_serialize(e).model_dump(mode="json") for e in entries]

    log_action(
        db,
        AuditAction.DATA_EXPORTED,
        user_id=admin.id,
        resource_type="audit_logs",
        request=request,
        details={"format": export_format, "records": len(rows)},
        commit=True,
    )

    if export_format == "json":
        return {"exported_at": utcnow().isoformat() + "Z", "count": len(rows), "records": rows}

    columns = [
        "id", "timestamp", "action", "user_id", "user_email", "resource_type",
        "resource_id", "ip_address", "success", "details",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        row["details"] = json.dumps(row["details"]) if row.get("details") else ""
        writer.writerow(row)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit_logs.csv"'},
    )


@router.get("/", response_model=PaginatedResponse[AuditLogResponse])
def list_audit_logs(
    user_id: Optional[str] = None,
    action: Optional[str] = Query(default=None, max_length=50),
    resource_type: Optional[str] = Query(default=None, max_length=50),
    resource_id: Optional[str] = Query(default=None, max_length=36),
    success: Optional[bool] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Query the audit trail. Admin only."""
    query = db.query(AuditLog).options(joinedload(AuditLog.user))

    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)
    if success is not None:
        query = query.filter(AuditLog.success.is_(success))
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)

    total = query.count()
    entries = (
        query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    )
    return paginate([_serialize(e) for e in entries], total, limit, offset)


@router.post(
    "/logs", response_model=AuditLogResponse, status_code=status.HTTP_201_CREATED
)
def create_audit_entry(
    payload: AuditLogCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Append an audit entry manually.

    Useful for recording events detected outside the API. Existing entries
    remain untouchable.
    """
    entry = log_action(
        db,
        payload.action,
        user_id=admin.id,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        request=request,
        details=payload.details,
        success=payload.success,
        commit=True,
    )
    db.refresh(entry)
    return _serialize(entry)

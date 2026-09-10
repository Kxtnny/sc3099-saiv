"""
Device registration and trust management.

Device binding is a fraud control: a check-in from a device the student has
never used before is a risk signal, and a fingerprint seen on two different
accounts suggests a proxy sign-in.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.sanitize import sanitize_text
from app.core.utils import utcnow
from app.dependencies import get_current_user, paginate, require_admin
from app.enums import AuditAction, TrustScore, UserRole
from app.models import Device, User
from app.schemas.common import PaginatedResponse
from app.schemas.device import DeviceCreate, DeviceResponse, DeviceUpdate
from app.services.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["devices"])


def register_device(
    db: Session, user: User, payload: DeviceCreate
) -> Device:
    """
    Register or refresh a device for a user.

    Fingerprints are globally unique. If one is already bound to a different
    account it is not silently reassigned - that would erase the evidence of a
    shared device, which is exactly the signal the risk engine needs.
    """
    existing = (
        db.query(Device)
        .filter(Device.device_fingerprint == payload.device_fingerprint)
        .first()
    )

    if existing is not None:
        if existing.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Device fingerprint already registered to another user",
            )
        existing.last_seen_at = utcnow()
        existing.is_active = True
        if payload.device_name:
            existing.device_name = sanitize_text(payload.device_name)
        if payload.platform:
            existing.platform = payload.platform
        if payload.browser:
            existing.browser = payload.browser
        if payload.public_key:
            existing.public_key = payload.public_key
        db.flush()
        return existing

    device = Device(
        user_id=user.id,
        device_fingerprint=payload.device_fingerprint,
        device_name=(
            sanitize_text(payload.device_name) if payload.device_name else None
        ),
        platform=payload.platform,
        browser=payload.browser,
        os_version=payload.os_version,
        app_version=payload.app_version,
        public_key=payload.public_key,
        trust_score=TrustScore.LOW.value,
    )
    db.add(device)
    db.flush()
    return device


@router.get("/my-devices", response_model=List[DeviceResponse])
def my_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Devices registered to the current user."""
    return (
        db.query(Device)
        .filter(Device.user_id == current_user.id)
        .order_by(Device.first_seen_at.desc())
        .all()
    )


@router.get("/", response_model=PaginatedResponse[DeviceResponse])
def list_devices(
    user_id: Optional[str] = None,
    is_trusted: Optional[bool] = None,
    is_active: Optional[bool] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all devices. Admin only."""
    query = db.query(Device)

    if user_id:
        query = query.filter(Device.user_id == user_id)
    if is_trusted is not None:
        query = query.filter(Device.is_trusted.is_(is_trusted))
    if is_active is not None:
        query = query.filter(Device.is_active.is_(is_active))

    total = query.count()
    devices = (
        query.order_by(Device.first_seen_at.desc()).offset(offset).limit(limit).all()
    )
    return paginate(
        [DeviceResponse.model_validate(d) for d in devices], total, limit, offset
    )


@router.post("/", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
@router.post(
    "/register", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED
)
def create_device(
    payload: DeviceCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Register a device.

    Exposed at both /devices/ and /devices/register: the API specification
    documents the latter, while REST convention expects the former.
    """
    device = register_device(db, current_user, payload)
    log_action(
        db,
        AuditAction.DEVICE_REGISTERED,
        user_id=current_user.id,
        resource_type="device",
        resource_id=device.id,
        request=request,
        device_id=device.id,
        details={"platform": device.platform},
    )
    db.commit()
    db.refresh(device)
    return device


@router.patch("/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: str,
    payload: DeviceUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update a device.

    Owners may rename or deactivate their own device; only an admin can mark
    one trusted, since trust lowers the risk score of every future check-in.
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Device not found"
        )

    is_admin = current_user.role == UserRole.ADMIN.value
    if not is_admin and device.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    changes = payload.model_dump(exclude_unset=True)
    if "is_trusted" in changes and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an administrator can change device trust",
        )

    if changes.get("device_name"):
        changes["device_name"] = sanitize_text(changes["device_name"])
    if changes.get("is_trusted") is True:
        device.trust_score = TrustScore.HIGH.value
    if changes.get("is_active") is False:
        device.revoked_at = utcnow()

    for field, value in changes.items():
        setattr(device, field, value)

    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(
    device_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Revoke a device.

    Deactivated rather than deleted: check-ins reference the device, and the
    binding history is part of the fraud trail.
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Device not found"
        )

    if (
        current_user.role != UserRole.ADMIN.value
        and device.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    device.is_active = False
    device.is_trusted = False
    device.revoked_at = utcnow()
    device.revocation_reason = "Revoked by user"

    log_action(
        db,
        AuditAction.DEVICE_REVOKED,
        user_id=current_user.id,
        resource_type="device",
        resource_id=device.id,
        request=request,
        details={"reason": device.revocation_reason},
    )
    db.commit()
    return None

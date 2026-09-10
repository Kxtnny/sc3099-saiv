"""
Check-in processing.

The heart of the system: validate the session window, verify the student is
enrolled, score the attempt against multiple risk signals, and record an
immutable audit entry.

PRIVACY: a submitted camera frame lives in memory for the duration of the
request. It is passed to the face service, its scores are kept, and the frame
itself is never written to the database, the logs, or the response.
"""

import json
import logging
import secrets
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.database import get_db
from app.core.sanitize import sanitize_text
from app.core.utils import utcnow
from app.dependencies import (
    get_current_user,
    is_staff,
    paginate,
    require_staff,
)
from app.enums import (
    AuditAction,
    CheckInStatus,
    SessionStatus,
    SignalType,
    UserRole,
)
from app.models import (
    AttendanceSession,
    CheckIn,
    Course,
    Device,
    Enrollment,
    RiskSignal,
    User,
)
from app.schemas.checkin import (
    CheckInAppeal,
    CheckInCreate,
    CheckInListItem,
    CheckInResponse,
    CheckInReview,
    MyCheckInItem,
)
from app.schemas.common import PaginatedResponse
from app.schemas.device import DeviceCreate
from app.services import face_client, rate_limit
from app.services.audit import log_action
from app.routers.devices import register_device
from app.services.audit import get_client_ip, get_user_agent
from app.services.geo import (
    coordinates_valid,
    haversine_distance,
    round_coordinates,
    travel_speed_kmh,
)
from app.services.risk import RiskAssessment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checkins", tags=["checkins"])

# Above this implied speed between two check-ins, the student cannot physically
# have travelled the distance.
IMPOSSIBLE_TRAVEL_KMH = 900.0
# Two check-ins closer together than this look automated.
RAPID_SUCCESSION_SECONDS = 30
# A GPS fix vaguer than this tells us little about where the student is.
POOR_ACCURACY_METERS = 200.0


def _venue(session: AttendanceSession) -> tuple:
    """Effective venue and geofence, falling back to the course defaults."""
    course = session.course
    lat = session.venue_latitude
    lon = session.venue_longitude
    radius = session.geofence_radius_meters

    if lat is None and course is not None:
        lat = course.venue_latitude
    if lon is None and course is not None:
        lon = course.venue_longitude
    if radius is None and course is not None:
        radius = course.geofence_radius_meters
    if radius is None:
        radius = settings.DEFAULT_GEOFENCE_RADIUS_METERS
    return lat, lon, radius


def _threshold(session: AttendanceSession) -> float:
    """Risk cut-off: session override, else course, else the global default."""
    if session.risk_threshold is not None:
        return session.risk_threshold
    if session.course is not None and session.course.risk_threshold is not None:
        return session.course.risk_threshold
    return settings.RISK_SCORE_THRESHOLD


def _parse_factors(raw: Optional[str]) -> List[Dict[str, Any]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _to_response(checkin: CheckIn) -> CheckInResponse:
    payload = CheckInResponse.model_validate(checkin)
    payload.risk_factors = _parse_factors(checkin.risk_factors)
    if checkin.device is not None:
        payload.device_trusted = checkin.device.is_trusted
    return payload


def _to_list_item(checkin: CheckIn) -> CheckInListItem:
    return CheckInListItem(
        id=checkin.id,
        session_id=checkin.session_id,
        session_name=checkin.session.name if checkin.session else None,
        course_code=(
            checkin.session.course.code
            if checkin.session and checkin.session.course
            else None
        ),
        student_id=checkin.student_id,
        student_name=checkin.student.full_name if checkin.student else None,
        student_email=checkin.student.email if checkin.student else None,
        status=checkin.status,
        checked_in_at=checkin.checked_in_at,
        distance_from_venue_meters=checkin.distance_from_venue_meters,
        risk_score=checkin.risk_score,
        risk_factors=_parse_factors(checkin.risk_factors),
        liveness_passed=checkin.liveness_passed,
        device_trusted=checkin.device.is_trusted if checkin.device else None,
        appeal_reason=checkin.appeal_reason,
        appealed_at=checkin.appealed_at,
    )


def _audit_rejected_attempt(
    db: Session, user: User, request: Request, session_id: str, reason: str
) -> None:
    """Record a check-in attempt that failed validation before scoring."""
    log_action(
        db,
        AuditAction.CHECKIN_ATTEMPTED,
        user_id=user.id,
        resource_type="session",
        resource_id=session_id,
        request=request,
        details={"reason": reason},
        success=False,
        commit=True,
    )


def _can_review(user: User, checkin: CheckIn) -> bool:
    """Course staff may review; students never can."""
    if user.role == UserRole.ADMIN.value:
        return True
    return is_staff(user)


# =============================================================================
# Submission
# =============================================================================

@router.post("/", response_model=CheckInResponse, status_code=status.HTTP_201_CREATED)
def create_checkin(
    payload: CheckInCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submit a check-in.

    Rejected outright for a critical signal (failed liveness, or a location far
    outside the geofence), flagged for review when the combined risk reaches
    the session threshold, otherwise approved.
    """
    if current_user.role != UserRole.STUDENT.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can check in",
        )

    rate_limit.check_checkin(current_user.id)

    session = (
        db.query(AttendanceSession)
        .options(joinedload(AttendanceSession.course))
        .filter(AttendanceSession.id == payload.session_id)
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    now = utcnow()

    if session.status != SessionStatus.ACTIVE.value:
        _audit_rejected_attempt(db, current_user, request, session.id, "session_not_active")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is not open for check-in (status: {session.status})",
        )
    if now < session.checkin_opens_at:
        _audit_rejected_attempt(db, current_user, request, session.id, "window_not_open")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Check-in window has not opened yet",
        )
    if now > session.checkin_closes_at:
        _audit_rejected_attempt(db, current_user, request, session.id, "window_closed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Check-in window has closed",
        )

    # Rotating QR code (replay prevention). Only enforced once the instructor
    # has issued one for this session.
    qr_verified = False
    if session.qr_code_secret:
        expired = (
            session.qr_code_expires_at is not None
            and now > session.qr_code_expires_at
        )
        if (
            not payload.qr_code
            or expired
            or not secrets.compare_digest(payload.qr_code, session.qr_code_secret)
        ):
            _audit_rejected_attempt(db, current_user, request, session.id, "qr_invalid")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired QR code",
            )
        qr_verified = True

    enrolled = (
        db.query(Enrollment.id)
        .filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == session.course_id,
            Enrollment.is_active.is_(True),
        )
        .first()
    )
    if enrolled is None:
        _audit_rejected_attempt(db, current_user, request, session.id, "not_enrolled")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not enrolled in this course",
        )

    duplicate = (
        db.query(CheckIn.id)
        .filter(
            CheckIn.session_id == session.id,
            CheckIn.student_id == current_user.id,
        )
        .first()
    )
    if duplicate is not None:
        _audit_rejected_attempt(db, current_user, request, session.id, "duplicate")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already checked in to this session",
        )

    assessment = RiskAssessment()

    # -- Device binding ------------------------------------------------------
    device = None
    if payload.device_fingerprint:
        device = (
            db.query(Device)
            .filter(Device.device_fingerprint == payload.device_fingerprint)
            .first()
        )
        if device is None:
            # First sighting: bind it now so later check-ins recognise it, but
            # still score this attempt as coming from an unknown device.
            device = register_device(
                db,
                current_user,
                DeviceCreate(
                    device_fingerprint=payload.device_fingerprint,
                    device_name="Auto-registered at check-in",
                    platform="web",
                ),
            )
            assessment.add(SignalType.DEVICE_UNKNOWN)
        elif device.user_id != current_user.id:
            # The same physical device checking in for two people is the
            # classic proxy sign-in.
            assessment.add(
                SignalType.PATTERN_ANOMALY,
                details={"reason": "device_shared_with_another_account"},
            )
            device = None
        elif not device.is_trusted:
            assessment.add(SignalType.DEVICE_UNKNOWN, confidence=0.5)

        if device is not None:
            device.last_seen_at = now
            device.total_checkins = (device.total_checkins or 0) + 1

    # -- Geofence ------------------------------------------------------------
    venue_lat, venue_lon, radius = _venue(session)
    distance = None

    if coordinates_valid(payload.latitude, payload.longitude):
        if coordinates_valid(venue_lat, venue_lon):
            distance = haversine_distance(
                payload.latitude, payload.longitude, venue_lat, venue_lon
            )
            if distance > radius * 2:
                assessment.add(
                    SignalType.GEO_OUT_OF_BOUNDS,
                    details={"distance_meters": round(distance, 1)},
                    critical=True,
                )
            elif distance > radius:
                assessment.add(
                    SignalType.GEO_OUT_OF_BOUNDS,
                    details={"distance_meters": round(distance, 1)},
                )

        if (
            payload.location_accuracy_meters is not None
            and payload.location_accuracy_meters > POOR_ACCURACY_METERS
        ):
            assessment.add(
                SignalType.GEO_ACCURACY_LOW,
                details={"accuracy_meters": payload.location_accuracy_meters},
            )
    else:
        assessment.add(
            SignalType.GEO_ACCURACY_LOW, details={"reason": "no_location_provided"}
        )

    # -- Behavioural ---------------------------------------------------------
    previous = (
        db.query(CheckIn)
        .filter(CheckIn.student_id == current_user.id)
        .order_by(CheckIn.checked_in_at.desc())
        .first()
    )
    if previous is not None:
        elapsed = (now - previous.checked_in_at).total_seconds()
        if elapsed < RAPID_SUCCESSION_SECONDS:
            assessment.add(
                SignalType.RAPID_SUCCESSION, details={"seconds_since_last": elapsed}
            )
        if (
            distance is not None
            and previous.latitude is not None
            and previous.longitude is not None
            and coordinates_valid(payload.latitude, payload.longitude)
        ):
            travelled = haversine_distance(
                previous.latitude,
                previous.longitude,
                payload.latitude,
                payload.longitude,
            )
            speed = travel_speed_kmh(travelled, elapsed)
            if speed > IMPOSSIBLE_TRAVEL_KMH:
                assessment.add(
                    SignalType.IMPOSSIBLE_TRAVEL,
                    details={
                        "implied_speed_kmh": round(speed, 1),
                        "distance_meters": round(travelled, 1),
                    },
                )

    # -- Liveness and face match --------------------------------------------
    liveness_passed = None
    liveness_score = None
    face_passed = None
    face_score = None
    face_hash = None

    if payload.liveness_challenge_response:
        result = face_client.check_liveness(
            payload.liveness_challenge_response,
            payload.liveness_challenge_type or "passive",
        )
        if result.get("available", True):
            liveness_passed = result.get("liveness_passed")
            liveness_score = result.get("liveness_score")
            face_hash = result.get("face_embedding_hash")

            if liveness_passed is False:
                assessment.add(
                    SignalType.LIVENESS_FAILED,
                    details={"score": liveness_score},
                    critical=True,
                )
            elif (
                liveness_score is not None
                and liveness_score < settings.LIVENESS_THRESHOLD
            ):
                assessment.add(
                    SignalType.LIVENESS_LOW_CONFIDENCE,
                    details={"score": liveness_score},
                )

        if session.require_face_match and current_user.face_embedding_hash:
            match = face_client.verify_face(
                payload.liveness_challenge_response,
                current_user.face_embedding_hash,
            )
            if match.get("available", True):
                face_passed = match.get("match_passed")
                face_score = match.get("match_score")
                face_hash = match.get("current_template_hash") or face_hash
                if face_passed is False:
                    assessment.add(
                        SignalType.FACE_MATCH_FAILED, details={"score": face_score}
                    )
                elif (
                    face_score is not None
                    and face_score < settings.FACE_MATCH_THRESHOLD
                ):
                    assessment.add(
                        SignalType.FACE_MATCH_LOW_CONFIDENCE,
                        details={"score": face_score},
                    )

    # -- Network (face service second opinion) ------------------------------
    # Module 3 owns VPN/proxy detection. Only its network component is taken:
    # liveness, face and geolocation are already scored above.
    if settings.FACE_RISK_ASSESS_ENABLED:
        remote = face_client.assess_risk(
            {
                "liveness_score": liveness_score,
                "face_match_score": face_score,
                "device_signature": payload.device_fingerprint,
                "user_agent": get_user_agent(request),
                "ip_address": get_client_ip(request),
                "geolocation": (
                    {
                        "latitude": payload.latitude,
                        "longitude": payload.longitude,
                        "accuracy": payload.location_accuracy_meters,
                    }
                    if coordinates_valid(payload.latitude, payload.longitude)
                    else None
                ),
            }
        )
        network_risk = ((remote or {}).get("signal_breakdown") or {}).get("network")
        if isinstance(network_risk, (int, float)) and network_risk >= 0.05:
            # The face service weights network at 15%, so 0.15 is "certain".
            assessment.add(
                SignalType.VPN_DETECTED,
                confidence=min(1.0, float(network_risk) / 0.15),
                details={"source": "face_service", "network_risk": network_risk},
            )

    # -- Decision ------------------------------------------------------------
    threshold = _threshold(session)
    decision = assessment.decide(threshold)

    stored_lat, stored_lon = round_coordinates(payload.latitude, payload.longitude)

    checkin = CheckIn(
        session_id=session.id,
        student_id=current_user.id,
        device_id=device.id if device is not None else None,
        status=decision.value,
        checked_in_at=now,
        verified_at=now if decision == CheckInStatus.APPROVED else None,
        latitude=stored_lat,
        longitude=stored_lon,
        location_accuracy_meters=payload.location_accuracy_meters,
        distance_from_venue_meters=round(distance, 2) if distance is not None else None,
        liveness_passed=liveness_passed,
        liveness_score=liveness_score,
        liveness_challenge_type=payload.liveness_challenge_type,
        face_match_passed=face_passed,
        face_match_score=face_score,
        face_embedding_hash=face_hash,
        risk_score=round(assessment.score, 4),
        risk_factors=json.dumps(assessment.signals),
        qr_code_verified=qr_verified,
        scheduled_deletion_at=now + timedelta(days=settings.DATA_RETENTION_DAYS),
    )
    db.add(checkin)

    try:
        db.flush()
    except IntegrityError:
        # Lost a race with a concurrent submission for the same session.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already checked in to this session",
        )

    for signal in assessment.signals:
        db.add(
            RiskSignal(
                checkin_id=checkin.id,
                signal_type=signal["type"],
                severity=signal["severity"],
                confidence=signal["confidence"],
                weight=signal["weight"],
                details=json.dumps(signal.get("details") or {}),
            )
        )

    log_action(
        db,
        AuditAction.CHECKIN_ATTEMPTED,
        user_id=current_user.id,
        resource_type="checkin",
        resource_id=checkin.id,
        request=request,
        device_id=device.id if device is not None else None,
        details={"session_id": session.id},
    )

    audit_action = {
        CheckInStatus.APPROVED: AuditAction.CHECKIN_APPROVED,
        CheckInStatus.FLAGGED: AuditAction.CHECKIN_FLAGGED,
        CheckInStatus.REJECTED: AuditAction.CHECKIN_REJECTED,
    }.get(decision, AuditAction.CHECKIN_ATTEMPTED)

    log_action(
        db,
        audit_action,
        user_id=current_user.id,
        resource_type="checkin",
        resource_id=checkin.id,
        request=request,
        device_id=device.id if device is not None else None,
        details={
            "session_id": session.id,
            "risk_score": checkin.risk_score,
            "risk_level": assessment.level.value,
            "distance_meters": checkin.distance_from_venue_meters,
            "signals": [s["type"] for s in assessment.signals],
        },
        success=decision != CheckInStatus.REJECTED,
    )

    db.commit()
    db.refresh(checkin)

    response = _to_response(checkin)
    response.risk_level = assessment.level.value
    return response


# =============================================================================
# Reads - literal paths before /{checkin_id}
# =============================================================================

@router.get("/my-checkins", response_model=List[MyCheckInItem])
def my_checkins(
    course_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The current student's own attendance history."""
    query = (
        db.query(CheckIn)
        .options(
            joinedload(CheckIn.session).joinedload(AttendanceSession.course)
        )
        .filter(CheckIn.student_id == current_user.id)
    )
    if course_id:
        query = query.join(
            AttendanceSession, AttendanceSession.id == CheckIn.session_id
        ).filter(AttendanceSession.course_id == course_id)

    rows = query.order_by(CheckIn.checked_in_at.desc()).limit(limit).all()

    return [
        MyCheckInItem(
            id=row.id,
            session_id=row.session_id,
            session_name=row.session.name if row.session else None,
            course_code=(
                row.session.course.code if row.session and row.session.course else None
            ),
            status=row.status,
            checked_in_at=row.checked_in_at,
            risk_score=row.risk_score,
        )
        for row in rows
    ]


@router.get("/flagged", response_model=PaginatedResponse[CheckInListItem])
def flagged_checkins(
    course_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Review queue: check-ins that are flagged or under appeal."""
    query = (
        db.query(CheckIn)
        .options(
            joinedload(CheckIn.student),
            joinedload(CheckIn.session).joinedload(AttendanceSession.course),
            joinedload(CheckIn.device),
        )
        .filter(
            CheckIn.status.in_(
                [CheckInStatus.FLAGGED.value, CheckInStatus.APPEALED.value]
            )
        )
    )

    if session_id:
        query = query.filter(CheckIn.session_id == session_id)
    if course_id:
        query = query.join(
            AttendanceSession, AttendanceSession.id == CheckIn.session_id
        ).filter(AttendanceSession.course_id == course_id)

    total = query.count()
    rows = (
        query.order_by(CheckIn.risk_score.desc(), CheckIn.checked_in_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return paginate([_to_list_item(r) for r in rows], total, limit, offset)


@router.get("/session/{session_id}", response_model=List[CheckInListItem])
def session_checkins(
    session_id: str,
    _staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """All check-ins for one session. Course staff only."""
    session = (
        db.query(AttendanceSession)
        .filter(AttendanceSession.id == session_id)
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Eager loading keeps this to a constant number of queries regardless of
    # how many students checked in.
    rows = (
        db.query(CheckIn)
        .options(
            joinedload(CheckIn.student),
            joinedload(CheckIn.session).joinedload(AttendanceSession.course),
            joinedload(CheckIn.device),
        )
        .filter(CheckIn.session_id == session_id)
        .order_by(CheckIn.checked_in_at)
        .all()
    )
    return [_to_list_item(r) for r in rows]


@router.get("/", response_model=PaginatedResponse[CheckInListItem])
def list_checkins(
    session_id: Optional[str] = None,
    course_id: Optional[str] = None,
    student_id: Optional[str] = None,
    status_filter: Optional[CheckInStatus] = Query(default=None, alias="status"),
    min_risk_score: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    max_risk_score: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """List check-ins across sessions with filters. Course staff only."""
    query = db.query(CheckIn).options(
        joinedload(CheckIn.student),
        joinedload(CheckIn.session).joinedload(AttendanceSession.course),
        joinedload(CheckIn.device),
    )

    if session_id:
        query = query.filter(CheckIn.session_id == session_id)
    if student_id:
        query = query.filter(CheckIn.student_id == student_id)
    if status_filter is not None:
        query = query.filter(CheckIn.status == status_filter.value)
    if min_risk_score is not None:
        query = query.filter(CheckIn.risk_score >= min_risk_score)
    if max_risk_score is not None:
        query = query.filter(CheckIn.risk_score <= max_risk_score)
    if start_date:
        query = query.filter(CheckIn.checked_in_at >= start_date)
    if end_date:
        query = query.filter(CheckIn.checked_in_at <= end_date)
    if course_id:
        query = query.join(
            AttendanceSession, AttendanceSession.id == CheckIn.session_id
        ).filter(AttendanceSession.course_id == course_id)

    total = query.count()
    rows = (
        query.order_by(CheckIn.checked_in_at.desc()).offset(offset).limit(limit).all()
    )
    return paginate([_to_list_item(r) for r in rows], total, limit, offset)


@router.get("/{checkin_id}", response_model=CheckInResponse)
def get_checkin(
    checkin_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One check-in with its full risk breakdown. Owner or course staff."""
    checkin = (
        db.query(CheckIn)
        .options(joinedload(CheckIn.device))
        .filter(CheckIn.id == checkin_id)
        .first()
    )
    if checkin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Check-in not found"
        )

    if checkin.student_id != current_user.id and not is_staff(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    return _to_response(checkin)


# =============================================================================
# Appeal and review
# =============================================================================

@router.post("/{checkin_id}/appeal", response_model=CheckInResponse)
def appeal_checkin(
    checkin_id: str,
    payload: CheckInAppeal,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Appeal a rejected or flagged check-in.

    Only the owner, only once, and only within the retention window - a GPS
    dispute weeks later cannot be verified against anything.
    """
    checkin = db.query(CheckIn).filter(CheckIn.id == checkin_id).first()
    if checkin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Check-in not found"
        )
    if checkin.student_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only appeal your own check-ins",
        )
    if checkin.status not in (
        CheckInStatus.REJECTED.value,
        CheckInStatus.FLAGGED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only rejected or flagged check-ins can be appealed",
        )
    if checkin.appealed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This check-in has already been appealed",
        )
    if utcnow() - checkin.checked_in_at > timedelta(days=7):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The 7-day appeal window has closed",
        )

    checkin.appeal_reason = sanitize_text(payload.appeal_reason, max_length=2000)
    checkin.appealed_at = utcnow()
    checkin.status = CheckInStatus.APPEALED.value

    log_action(
        db,
        AuditAction.CHECKIN_APPEALED,
        user_id=current_user.id,
        resource_type="checkin",
        resource_id=checkin.id,
        request=request,
        details={"session_id": checkin.session_id},
    )
    db.commit()
    db.refresh(checkin)
    return _to_response(checkin)


@router.post("/{checkin_id}/review", response_model=CheckInResponse)
def review_checkin(
    checkin_id: str,
    payload: CheckInReview,
    request: Request,
    reviewer: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Approve or reject a flagged or appealed check-in. Course staff only."""
    checkin = (
        db.query(CheckIn)
        .options(joinedload(CheckIn.session))
        .filter(CheckIn.id == checkin_id)
        .first()
    )
    if checkin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Check-in not found"
        )
    if not _can_review(reviewer, checkin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    if payload.status not in (CheckInStatus.APPROVED, CheckInStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A review must resolve to approved or rejected",
        )

    checkin.status = payload.status.value
    checkin.reviewed_by_id = reviewer.id
    checkin.reviewed_at = utcnow()
    checkin.review_notes = (
        sanitize_text(payload.review_notes, max_length=2000)
        if payload.review_notes
        else None
    )
    if payload.status == CheckInStatus.APPROVED:
        checkin.verified_at = utcnow()

    log_action(
        db,
        AuditAction.CHECKIN_REVIEWED,
        user_id=reviewer.id,
        resource_type="checkin",
        resource_id=checkin.id,
        request=request,
        details={"decision": payload.status.value},
    )
    db.commit()
    db.refresh(checkin)
    return _to_response(checkin)

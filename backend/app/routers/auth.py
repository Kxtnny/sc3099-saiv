"""
Authentication endpoints: registration, login, token refresh, logout.

Handlers are sync `def` on purpose. FastAPI runs them in a worker thread, so a
~90ms bcrypt hash never blocks the event loop - which is what keeps concurrent
logins within the latency budget.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token_of_type,
    get_password_hash,
    verify_password,
)
from app.core.utils import utcnow
from app.dependencies import get_current_user
from app.enums import AuditAction
from app.models import User
from app.schemas.common import MessageResponse
from app.schemas.user import (
    RefreshRequest,
    TokenRefreshResponse,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.services.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _token_claims(user: User) -> dict:
    """
    Non-sensitive claims embedded in tokens.

    Identity and role only - never consent flags, biometric data or anything
    else a client could act on without re-checking the database.
    """
    return {"email": user.email, "role": user.role}


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register(payload: UserCreate, request: Request, db: Session = Depends(get_db)):
    """
    Register a new account.

    Weak passwords and malformed emails are rejected by the schema with 422; a
    duplicate email returns 400.
    """
    email = payload.email.lower().strip()

    if db.query(User.id).filter(User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=get_password_hash(payload.password),
        role=payload.role.value,
        is_active=True,
    )
    db.add(user)

    try:
        db.flush()
    except IntegrityError:
        # Lost a race with a concurrent registration for the same address.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    log_action(
        db,
        AuditAction.USER_CREATED,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
        details={"email": email, "role": user.role},
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    """
    Exchange credentials for an access and refresh token pair.

    401 for bad credentials, 403 for a deactivated account. The failure
    responses deliberately do not reveal whether the email exists.
    """
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()

    if user is None or not verify_password(payload.password, user.hashed_password):
        log_action(
            db,
            AuditAction.LOGIN_FAILED,
            user_id=user.id if user else None,
            resource_type="user",
            request=request,
            details={"email": email, "reason": "invalid_credentials"},
            success=False,
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )

    if not user.is_active:
        log_action(
            db,
            AuditAction.LOGIN_FAILED,
            user_id=user.id,
            resource_type="user",
            resource_id=user.id,
            request=request,
            details={"email": email, "reason": "account_disabled"},
            success=False,
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )

    user.last_login_at = utcnow()
    log_action(
        db,
        AuditAction.LOGIN_SUCCESS,
        user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
        details={"email": email},
    )
    db.commit()
    db.refresh(user)

    claims = _token_claims(user)
    return TokenResponse(
        access_token=create_access_token(user.id, claims),
        refresh_token=create_refresh_token(user.id, claims),
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenRefreshResponse)
def refresh_tokens(payload: RefreshRequest, db: Session = Depends(get_db)):
    """
    Issue a fresh token pair from a valid refresh token.

    Rotating the refresh token on every use limits the damage if one leaks.
    """
    claims = decode_token_of_type(payload.refresh_token, TOKEN_TYPE_REFRESH)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    user = db.query(User).filter(User.id == claims.get("sub")).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )

    token_claims = _token_claims(user)
    return TokenRefreshResponse(
        access_token=create_access_token(user.id, token_claims),
        refresh_token=create_refresh_token(user.id, token_claims),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Record a logout.

    JWTs are stateless, so the server cannot revoke an already-issued access
    token; the client discards it. The event is audited for compliance. A
    Redis deny-list would be the next step if true revocation is needed.
    """
    log_action(
        db,
        AuditAction.LOGOUT,
        user_id=current_user.id,
        resource_type="user",
        resource_id=current_user.id,
        request=request,
    )
    db.commit()
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
def read_me(current_user: User = Depends(get_current_user)):
    """Current user. Mirrors GET /users/me, which the frontend uses."""
    return current_user

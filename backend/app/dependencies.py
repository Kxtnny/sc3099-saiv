"""
Shared FastAPI dependencies: authentication and role-based access control.

Role rules come from docs/SECURITY-REQUIREMENTS.md (admin 4 > instructor 3 >
ta 2 > student 1).
"""

from typing import Optional, Sequence

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import TOKEN_TYPE_ACCESS, decode_token_of_type
from app.enums import ROLE_LEVELS, UserRole
from app.models import User

# auto_error=False so a missing header produces our own 401 with a "detail"
# body rather than FastAPI's default 403.
bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the authenticated user from a bearer access token.

    Raises 401 for a missing, malformed, expired or refresh-type token, and 403
    for a deactivated account.
    """
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_EXCEPTION

    payload = decode_token_of_type(credentials.credentials, TOKEN_TYPE_ACCESS)
    if payload is None:
        raise CREDENTIALS_EXCEPTION

    user_id = payload.get("sub")
    if not user_id:
        raise CREDENTIALS_EXCEPTION

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise CREDENTIALS_EXCEPTION

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )

    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Resolve the user when a valid token is present, otherwise return None.

    Used by endpoints that are readable anonymously but richer when
    authenticated, such as GET /courses/.
    """
    if credentials is None or not credentials.credentials:
        return None

    payload = decode_token_of_type(credentials.credentials, TOKEN_TYPE_ACCESS)
    if payload is None:
        return None

    user = db.query(User).filter(User.id == payload.get("sub")).first()
    return user if user and user.is_active else None


def require_roles(*roles: UserRole):
    """
    Dependency factory restricting an endpoint to specific roles.

    Usage:
        @router.post("/", dependencies=[Depends(require_roles(UserRole.ADMIN))])
    """
    allowed = {r.value for r in roles}

    def _guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _guard


def require_min_role(minimum: UserRole):
    """Restrict an endpoint to a role level and everything above it."""
    threshold = ROLE_LEVELS[minimum]

    def _guard(current_user: User = Depends(get_current_user)) -> User:
        level = ROLE_LEVELS.get(UserRole(current_user.role), 0)
        if level < threshold:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _guard


# Common guards, ready to use.
require_admin = require_roles(UserRole.ADMIN)
require_instructor = require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN)
require_staff = require_roles(UserRole.TA, UserRole.INSTRUCTOR, UserRole.ADMIN)
require_student = require_roles(UserRole.STUDENT)


def has_role(user: User, *roles: UserRole) -> bool:
    """Check a user's role outside the dependency system."""
    return user.role in {r.value for r in roles}


def is_staff(user: User) -> bool:
    """True for TAs, instructors and admins."""
    return has_role(user, UserRole.TA, UserRole.INSTRUCTOR, UserRole.ADMIN)


def paginate(items: Sequence, total: int, limit: int, offset: int) -> dict:
    """Build the standard pagination envelope."""
    return {"items": list(items), "total": total, "limit": limit, "offset": offset}

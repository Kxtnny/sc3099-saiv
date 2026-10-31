"""Centralized dashboard roles and permissions."""

from enum import Enum
from typing import Any, Dict, FrozenSet, Optional

import streamlit as st


class Permission(str, Enum):
    CHECK_IN = "check_in"
    VIEW_OWN_RECORDS = "view_own_records"
    MANAGE_OWN_DEVICES = "manage_own_devices"
    APPEAL_OWN_CHECKIN = "appeal_own_checkin"
    VIEW_SESSION_CHECKINS = "view_session_checkins"
    REVIEW_FLAGGED_CHECKINS = "review_flagged_checkins"
    MANAGE_SESSIONS = "manage_sessions"
    VIEW_COURSE_ANALYTICS = "view_course_analytics"
    MANAGE_ENROLLMENTS = "manage_enrollments"
    VIEW_AUDIT = "view_audit"
    VIEW_OBSERVABILITY = "view_observability"
    VIEW_CHECKIN_EXPLORER = "view_checkin_explorer"
    MANAGE_ADMINISTRATION = "manage_administration"


_STUDENT_PERMISSIONS = frozenset(
    {
        Permission.CHECK_IN,
        Permission.VIEW_OWN_RECORDS,
        Permission.MANAGE_OWN_DEVICES,
        Permission.APPEAL_OWN_CHECKIN,
    }
)
_TA_PERMISSIONS = frozenset(
    {
        Permission.VIEW_SESSION_CHECKINS,
        Permission.REVIEW_FLAGGED_CHECKINS,
    }
)
_INSTRUCTOR_PERMISSIONS = frozenset(
    {
        Permission.MANAGE_SESSIONS,
        Permission.VIEW_COURSE_ANALYTICS,
        Permission.MANAGE_ENROLLMENTS,
    }
)
_ADMIN_PERMISSIONS = frozenset(
    {
        Permission.VIEW_AUDIT,
        Permission.VIEW_OBSERVABILITY,
        Permission.VIEW_CHECKIN_EXPLORER,
        Permission.MANAGE_ADMINISTRATION,
    }
)

ROLE_PERMISSIONS: Dict[str, FrozenSet[Permission]] = {
    "student": _STUDENT_PERMISSIONS,
    "ta": _STUDENT_PERMISSIONS | _TA_PERMISSIONS,
    "instructor": _STUDENT_PERMISSIONS | _TA_PERMISSIONS | _INSTRUCTOR_PERMISSIONS,
    "admin": (
        _STUDENT_PERMISSIONS
        | _TA_PERMISSIONS
        | _INSTRUCTOR_PERMISSIONS
        | _ADMIN_PERMISSIONS
    ),
}

DASHBOARD_PAGE_PERMISSIONS: Dict[str, Permission] = {
    "👤 My Attendance & Devices": Permission.VIEW_OWN_RECORDS,
    "📊 Overview": Permission.VIEW_COURSE_ANALYTICS,
    "📅 Sessions": Permission.MANAGE_SESSIONS,
    "📋 Session Check-ins": Permission.VIEW_SESSION_CHECKINS,
    "🚨 Review Queue": Permission.REVIEW_FLAGGED_CHECKINS,
    "🎓 Courses & Rosters": Permission.VIEW_COURSE_ANALYTICS,
    "📋 Check-in Explorer": Permission.VIEW_CHECKIN_EXPLORER,
    "📜 Security Audit": Permission.VIEW_AUDIT,
    "📈 Observability": Permission.VIEW_OBSERVABILITY,
    "🛠️ Administration": Permission.MANAGE_ADMINISTRATION,
}


def role_for_user(user: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return a known normalized role; missing and unknown roles fail closed."""
    if not isinstance(user, dict):
        return None
    role = user.get("role")
    if not isinstance(role, str):
        return None
    normalized_role = role.strip().lower()
    return normalized_role if normalized_role in ROLE_PERMISSIONS else None


def has_permission(
    user: Optional[Dict[str, Any]], permission: Permission
) -> bool:
    """Check a permission without granting access to unknown roles."""
    role = role_for_user(user)
    return role is not None and permission in ROLE_PERMISSIONS[role]


def allowed_dashboard_pages(
    user: Optional[Dict[str, Any]],
) -> FrozenSet[str]:
    """Return navigation pages allowed for the authenticated role."""
    return frozenset(
        page
        for page, permission in DASHBOARD_PAGE_PERMISSIONS.items()
        if has_permission(user, permission)
    )


def require_permission(
    user: Optional[Dict[str, Any]], permission: Permission
) -> bool:
    """Render a consistent denial message when a view/action is not allowed."""
    if has_permission(user, permission):
        return True
    st.error("Access denied. Your account does not have permission to view this page.")
    return False


def resolve_dashboard_page(
    requested_page: Any, allowed_pages: FrozenSet[str], default_page: str
) -> str:
    """Keep refresh state when allowed and replace stale/forged page selections."""
    if isinstance(requested_page, str) and requested_page in allowed_pages:
        return requested_page
    if default_page not in allowed_pages:
        raise ValueError("The dashboard default page must be allowed.")
    return default_page

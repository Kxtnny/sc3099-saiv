"""
API Client for interacting with the SAIV Backend REST API and Prometheus.
"""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import requests

from app.config import (
    API_BASE_URL,
    BACKEND_URL,
    DEFAULT_TIMEOUT,
    EXPORT_TIMEOUT,
    FACE_SERVICE_URL,
    PROMETHEUS_URL,
)

logger = logging.getLogger(__name__)


class APIClient:
    """Helper class managing HTTP requests to backend and observability services."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._refresh_lock = threading.Lock()
        self._refresh_handler: Optional[Callable[[str], Optional[str]]] = None
        self.session.hooks["response"].append(self._retry_after_unauthorized)

    def set_refresh_handler(
        self, handler: Callable[[str], Optional[str]]
    ) -> None:
        """Register the Streamlit-session callback used after an access-token 401."""
        self._refresh_handler = handler

    def _retry_after_unauthorized(
        self, response: requests.Response, *args: Any, **kwargs: Any
    ) -> requests.Response:
        """Refresh and retry an authenticated request at most once."""
        request = response.request
        if (
            response.status_code != 401
            or request is None
            or request.url.split("?", 1)[0].endswith("/auth/refresh")
            or not self._refresh_handler
        ):
            return response

        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return response

        with self._refresh_lock:
            refreshed_token = self._refresh_handler(authorization[7:])
        if not refreshed_token:
            return response

        retry_request = request.copy()
        retry_request.headers["Authorization"] = f"Bearer {refreshed_token}"
        retry_request.hooks["response"] = []
        response.close()
        return self.session.send(retry_request, **kwargs)

    def _headers(self, token: Optional[str] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _handle_response(
        self, response: requests.Response
    ) -> Tuple[bool, Union[Dict[str, Any], List[Any], str]]:
        # A 401 on a bearer-token request means the session expired; a 401 on
        # login/refresh (no token sent) carries a reason the user should see.
        request = response.request
        if (
            response.status_code == 401
            and request is not None
            and request.headers.get("Authorization", "").startswith("Bearer ")
        ):
            return False, "Your session has expired. Please sign in again."
        try:
            if response.status_code == 204:
                return True, {}
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                data = response.json()
                return response.ok, data
            return response.ok, response.text
        except Exception as e:
            logger.error("Failed to parse response: %s", e)
            return False, str(response.text or e)

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def login(self, email: str, password: str) -> Tuple[bool, Any]:
        """Authenticate user and retrieve tokens."""
        url = f"{self.base_url}/auth/login"
        try:
            res = self.session.post(
                url,
                json={"email": email, "password": password},
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def refresh_token(self, refresh_token_str: str) -> Tuple[bool, Any]:
        """Refresh access token."""
        url = f"{self.base_url}/auth/refresh"
        try:
            res = self.session.post(
                url,
                json={"refresh_token": refresh_token_str},
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_current_user(self, token: str) -> Tuple[bool, Any]:
        """Fetch current user profile and role."""
        url = f"{self.base_url}/users/me"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def logout(self, token: str) -> Tuple[bool, Any]:
        """Audit logout."""
        url = f"{self.base_url}/auth/logout"
        try:
            res = self.session.post(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    # -------------------------------------------------------------------------
    # Statistics & Analytics
    # -------------------------------------------------------------------------

    def get_overview_stats(
        self, token: str, days: int = 7, course_id: Optional[str] = None
    ) -> Tuple[bool, Any]:
        """Fetch high-level overview metrics."""
        url = f"{self.base_url}/stats/overview"
        params: Dict[str, Any] = {"days": days}
        if course_id:
            params["course_id"] = course_id
        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_session_stats(self, token: str, session_id: str) -> Tuple[bool, Any]:
        """Fetch attendance breakdown for a single session."""
        url = f"{self.base_url}/stats/sessions/{session_id}"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_course_stats(
        self,
        token: str,
        course_id: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """Fetch analytics across a course, optionally limited to a date range."""
        url = f"{self.base_url}/stats/courses/{course_id}"
        params: Dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_student_stats(self, token: str, student_id: str) -> Tuple[bool, Any]:
        """Fetch individual student attendance history."""
        url = f"{self.base_url}/stats/students/{student_id}"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    def list_sessions(
        self,
        token: str,
        status: Optional[str] = None,
        course_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        instructor_id: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """List sessions with optional filters."""
        url = f"{self.base_url}/sessions/"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if course_id:
            params["course_id"] = course_id
        if instructor_id:
            params["instructor_id"] = instructor_id
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_active_sessions(self) -> Tuple[bool, Any]:
        """List currently open/active sessions (public endpoint)."""
        url = f"{self.base_url}/sessions/active"
        try:
            res = self.session.get(url, timeout=DEFAULT_TIMEOUT)
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_my_sessions(
        self, token: str, limit: int = 100
    ) -> Tuple[bool, Any]:
        """List sessions associated with the authenticated user."""
        url = f"{self.base_url}/sessions/my-sessions"
        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params={"limit": limit},
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_session(self, token: str, session_id: str) -> Tuple[bool, Any]:
        """Fetch details for one session."""
        url = f"{self.base_url}/sessions/{session_id}"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def create_session(self, token: str, payload: Dict[str, Any]) -> Tuple[bool, Any]:
        """Create and schedule a new session."""
        url = f"{self.base_url}/sessions/"
        try:
            res = self.session.post(
                url,
                headers=self._headers(token),
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def update_session(
        self, token: str, session_id: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Any]:
        """Update session details or change status (active/closed/cancelled)."""
        url = f"{self.base_url}/sessions/{session_id}"
        try:
            res = self.session.patch(
                url,
                headers=self._headers(token),
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def generate_session_qr(self, token: str, session_id: str) -> Tuple[bool, Any]:
        """Issue a fresh rotating QR code secret."""
        url = f"{self.base_url}/sessions/{session_id}/qr"
        try:
            res = self.session.post(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def clear_session_qr(self, token: str, session_id: str) -> Tuple[bool, Any]:
        """Clear the QR requirement for a session."""
        url = f"{self.base_url}/sessions/{session_id}/qr"
        try:
            res = self.session.delete(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def delete_session(self, token: str, session_id: str) -> Tuple[bool, Any]:
        """Delete a scheduled session."""
        url = f"{self.base_url}/sessions/{session_id}"
        try:
            res = self.session.delete(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    # -------------------------------------------------------------------------
    # Check-ins & Flagged Queue
    # -------------------------------------------------------------------------

    def list_checkins(
        self,
        token: str,
        session_id: Optional[str] = None,
        course_id: Optional[str] = None,
        student_id: Optional[str] = None,
        status: Optional[str] = None,
        min_risk: Optional[float] = None,
        max_risk: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """Query check-ins across courses with filters."""
        url = f"{self.base_url}/checkins/"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if session_id:
            params["session_id"] = session_id
        if course_id:
            params["course_id"] = course_id
        if student_id:
            params["student_id"] = student_id
        if status:
            params["status"] = status
        if min_risk is not None:
            params["min_risk_score"] = min_risk
        if max_risk is not None:
            params["max_risk_score"] = max_risk
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_flagged_checkins(
        self,
        token: str,
        course_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[bool, Any]:
        """Review queue of flagged and appealed check-ins."""
        url = f"{self.base_url}/checkins/flagged"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if course_id:
            params["course_id"] = course_id
        if session_id:
            params["session_id"] = session_id
        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_my_checkins(
        self, token: str, limit: int = 100
    ) -> Tuple[bool, Any]:
        """Fetch the authenticated user's own attendance history."""
        url = f"{self.base_url}/checkins/my-checkins"
        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params={"limit": limit},
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_session_checkins(self, token: str, session_id: str) -> Tuple[bool, Any]:
        """Fetch all check-ins for a specific session."""
        url = f"{self.base_url}/checkins/session/{session_id}"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_checkin(self, token: str, checkin_id: str) -> Tuple[bool, Any]:
        """Fetch single check-in details with full signal breakdown."""
        url = f"{self.base_url}/checkins/{checkin_id}"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def appeal_checkin(
        self, token: str, checkin_id: str, appeal_reason: str
    ) -> Tuple[bool, Any]:
        """Submit an appeal for the authenticated student's own check-in."""
        url = f"{self.base_url}/checkins/{checkin_id}/appeal"
        try:
            res = self.session.post(
                url,
                headers=self._headers(token),
                json={"appeal_reason": appeal_reason},
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def review_checkin(
        self,
        token: str,
        checkin_id: str,
        status: str,
        review_notes: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """Instructor decision on a flagged/appealed check-in (approved or rejected)."""
        url = f"{self.base_url}/checkins/{checkin_id}/review"
        payload = {"status": status}
        if review_notes:
            payload["review_notes"] = review_notes
        try:
            res = self.session.post(
                url,
                headers=self._headers(token),
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_my_devices(self, token: str) -> Tuple[bool, Any]:
        """Fetch devices belonging to the authenticated user."""
        url = f"{self.base_url}/devices/my-devices"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def update_device(
        self,
        token: str,
        device_id: str,
        *,
        device_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_trusted: Optional[bool] = None,
    ) -> Tuple[bool, Any]:
        """Update device fields; changing trust is an admin-only API action."""
        payload: Dict[str, Any] = {}
        if device_name is not None:
            payload["device_name"] = device_name
        if is_active is not None:
            payload["is_active"] = is_active
        if is_trusted is not None:
            payload["is_trusted"] = is_trusted
        url = f"{self.base_url}/devices/{device_id}"
        try:
            res = self.session.patch(
                url,
                headers=self._headers(token),
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def list_devices(
        self,
        token: str,
        *,
        is_active: Optional[bool] = None,
        is_trusted: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[bool, Any]:
        """List system devices using the admin-only endpoint."""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if is_active is not None:
            params["is_active"] = is_active
        if is_trusted is not None:
            params["is_trusted"] = is_trusted
        try:
            res = self.session.get(
                f"{self.base_url}/devices/",
                headers=self._headers(token),
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def revoke_device(self, token: str, device_id: str) -> Tuple[bool, Any]:
        """Revoke an owned device."""
        url = f"{self.base_url}/devices/{device_id}"
        try:
            res = self.session.delete(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    # -------------------------------------------------------------------------
    # Courses & Enrollments
    # -------------------------------------------------------------------------

    def list_users(
        self,
        token: str,
        *,
        role: Optional[str] = None,
        is_active: Optional[bool] = True,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[bool, Any]:
        """List users using the admin-only paginated API."""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if role:
            params["role"] = role
        if is_active is not None:
            params["is_active"] = is_active
        try:
            res = self.session.get(
                f"{self.base_url}/users/",
                headers=self._headers(token),
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def update_user(
        self, token: str, user_id: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Any]:
        """Update a user's role or active status (admin only)."""
        try:
            res = self.session.patch(
                f"{self.base_url}/users/{user_id}",
                headers=self._headers(token),
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def create_users(
        self, token: str, users: List[Dict[str, Any]]
    ) -> Tuple[bool, Any]:
        """Create users through the admin-only bulk account endpoint."""
        try:
            res = self.session.post(
                f"{self.base_url}/admin/users/bulk",
                headers=self._headers(token),
                json={"users": users},
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def list_courses(
        self,
        token: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[bool, Any]:
        """List active courses."""
        url = f"{self.base_url}/courses/"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if is_active is not None:
            params["is_active"] = is_active
        try:
            res = self.session.get(
                url,
                headers=self._headers(token) if token else {},
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def create_course(
        self, token: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Any]:
        """Create a course (admin only)."""
        try:
            res = self.session.post(
                f"{self.base_url}/courses/",
                headers=self._headers(token),
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def update_course(
        self, token: str, course_id: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Any]:
        """Update a course (admin only)."""
        try:
            res = self.session.patch(
                f"{self.base_url}/courses/{course_id}",
                headers=self._headers(token),
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def delete_course(self, token: str, course_id: str) -> Tuple[bool, Any]:
        """Soft-delete a course (admin only)."""
        try:
            res = self.session.delete(
                f"{self.base_url}/courses/{course_id}",
                headers=self._headers(token),
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_course(
        self, course_id: str, token: Optional[str] = None
    ) -> Tuple[bool, Any]:
        """Get course details."""
        url = f"{self.base_url}/courses/{course_id}"
        try:
            res = self.session.get(
                url,
                headers=self._headers(token) if token else {},
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_course_tas(
        self, token: str, course_id: str
    ) -> Tuple[bool, Any]:
        """List TAs assigned to a course."""
        try:
            res = self.session.get(
                f"{self.base_url}/courses/{course_id}/tas",
                headers=self._headers(token),
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def assign_course_ta(
        self, token: str, course_id: str, ta_id: str
    ) -> Tuple[bool, Any]:
        """Assign a TA to a course (admin only)."""
        try:
            res = self.session.post(
                f"{self.base_url}/courses/{course_id}/tas",
                headers=self._headers(token),
                json={"ta_id": ta_id},
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def unassign_course_ta(
        self, token: str, course_id: str, ta_id: str
    ) -> Tuple[bool, Any]:
        """Remove a TA assignment (admin only)."""
        try:
            res = self.session.delete(
                f"{self.base_url}/courses/{course_id}/tas/{ta_id}",
                headers=self._headers(token),
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_course_enrollments(
        self,
        token: str,
        course_id: str,
        is_active: bool = True,
        search: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """Roster for a course."""
        url = f"{self.base_url}/enrollments/course/{course_id}"
        params: Dict[str, Any] = {"is_active": is_active}
        if search:
            params["search"] = search
        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def bulk_enroll(
        self,
        token: str,
        course_id: str,
        student_emails: List[str],
        create_accounts: bool = True,
    ) -> Tuple[bool, Any]:
        """Bulk enroll student emails."""
        url = f"{self.base_url}/enrollments/bulk"
        payload = {
            "course_id": course_id,
            "student_emails": student_emails,
            "create_accounts": create_accounts,
        }
        try:
            res = self.session.post(
                url,
                headers=self._headers(token),
                json=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def delete_enrollment(self, token: str, enrollment_id: str) -> Tuple[bool, Any]:
        """Drop student enrollment."""
        url = f"{self.base_url}/enrollments/{enrollment_id}"
        try:
            res = self.session.delete(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    # -------------------------------------------------------------------------
    # Gradebook & Attendance Export
    # -------------------------------------------------------------------------

    def export_session_csv(self, token: str, session_id: str) -> Tuple[bool, Any]:
        """Download session attendance as CSV bytes."""
        url = f"{self.base_url}/export/session/{session_id}?format=csv"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=EXPORT_TIMEOUT
            )
            if res.ok:
                return True, res.content
            return False, res.text
        except Exception as e:
            return False, f"Connection error: {e}"

    def export_session_json(self, token: str, session_id: str) -> Tuple[bool, Any]:
        """Download session attendance as JSON."""
        url = f"{self.base_url}/export/session/{session_id}?format=json"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=EXPORT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def export_course_csv(
        self,
        token: str,
        course_id: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """Download course attendance as CSV bytes."""
        params: Dict[str, Any] = {"format": "csv"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        try:
            res = self.session.get(
                f"{self.base_url}/export/attendance/{course_id}",
                headers=self._headers(token),
                params=params,
                timeout=EXPORT_TIMEOUT,
            )
            if res.ok:
                return True, res.content
            return False, res.text
        except Exception as e:
            return False, f"Connection error: {e}"

    def export_course_json(
        self,
        token: str,
        course_id: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """Download course attendance as JSON."""
        params: Dict[str, Any] = {"format": "json"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        try:
            res = self.session.get(
                f"{self.base_url}/export/attendance/{course_id}",
                headers=self._headers(token),
                params=params,
                timeout=EXPORT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    # -------------------------------------------------------------------------
    # Audit Logs
    # -------------------------------------------------------------------------

    def get_audit_summary(self, token: str, days: int = 7) -> Tuple[bool, Any]:
        """Get audit log summary aggregate."""
        url = f"{self.base_url}/audit/summary"
        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params={"days": days},
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def list_audit_logs(
        self,
        token: str,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        success: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """Query audit log entries."""
        url = f"{self.base_url}/audit/"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if user_id:
            params["user_id"] = user_id
        if action:
            params["action"] = action
        if resource_type:
            params["resource_type"] = resource_type
        if resource_id:
            params["resource_id"] = resource_id
        if success is not None:
            params["success"] = success
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        try:
            res = self.session.get(
                url,
                headers=self._headers(token),
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def export_audit_csv(self, token: str) -> Tuple[bool, Any]:
        """Download audit trail CSV."""
        url = f"{self.base_url}/audit/export?format=csv"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=EXPORT_TIMEOUT
            )
            if res.ok:
                return True, res.content
            return False, res.text
        except Exception as e:
            return False, f"Connection error: {e}"

    def export_audit_json(self, token: str) -> Tuple[bool, Any]:
        """Download the audit trail as JSON."""
        url = f"{self.base_url}/audit/export?format=json"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=EXPORT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    # -------------------------------------------------------------------------
    # Observability, Health & Prometheus
    # -------------------------------------------------------------------------

    def get_backend_health(self) -> Tuple[bool, Any]:
        """Probe Backend health endpoint."""
        url = f"{BACKEND_URL.rstrip('/')}/health"
        try:
            res = self.session.get(url, timeout=DEFAULT_TIMEOUT)
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_dependency_health(self) -> Tuple[bool, Any]:
        """Probe Backend dependencies (DB, Redis, Face-service)."""
        url = f"{BACKEND_URL.rstrip('/')}/health/dependencies"
        try:
            res = self.session.get(url, timeout=DEFAULT_TIMEOUT)
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def get_face_service_health(self) -> Tuple[bool, Any]:
        """Probe Face Recognition service health endpoint."""
        url = f"{FACE_SERVICE_URL.rstrip('/')}/health"
        try:
            res = self.session.get(url, timeout=DEFAULT_TIMEOUT)
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def query_prometheus(self, query: str) -> Tuple[bool, Any]:
        """Execute PromQL query."""
        url = f"{PROMETHEUS_URL.rstrip('/')}/api/v1/query"
        try:
            res = self.session.get(
                url, params={"query": query}, timeout=DEFAULT_TIMEOUT
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"

    def query_prometheus_range(
        self,
        query: str,
        start: str,
        end: str,
        step: str,
    ) -> Tuple[bool, Any]:
        """Execute a Prometheus range query for dashboard trend charts."""
        url = f"{PROMETHEUS_URL.rstrip('/')}/api/v1/query_range"
        try:
            res = self.session.get(
                url,
                params={
                    "query": query,
                    "start": start,
                    "end": end,
                    "step": step,
                },
                timeout=DEFAULT_TIMEOUT,
            )
            return self._handle_response(res)
        except Exception as e:
            return False, f"Connection error: {e}"


# Singleton instance
api_client = APIClient()

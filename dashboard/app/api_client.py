"""
API Client for interacting with the SAIV Backend REST API and Prometheus.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union
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

    def _headers(self, token: Optional[str] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _handle_response(
        self, response: requests.Response
    ) -> Tuple[bool, Union[Dict[str, Any], List[Any], str]]:
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

    def get_course_stats(self, token: str, course_id: str) -> Tuple[bool, Any]:
        """Fetch analytics across all sessions in a course."""
        url = f"{self.base_url}/stats/courses/{course_id}"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=DEFAULT_TIMEOUT
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
    ) -> Tuple[bool, Any]:
        """List sessions with optional filters."""
        url = f"{self.base_url}/sessions/"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
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

    def get_active_sessions(self) -> Tuple[bool, Any]:
        """List currently open/active sessions (public endpoint)."""
        url = f"{self.base_url}/sessions/active"
        try:
            res = self.session.get(url, timeout=DEFAULT_TIMEOUT)
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

    # -------------------------------------------------------------------------
    # Courses & Enrollments
    # -------------------------------------------------------------------------

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

    def export_course_csv(self, token: str, course_id: str) -> Tuple[bool, Any]:
        """Download course attendance as CSV bytes."""
        url = f"{self.base_url}/export/attendance/{course_id}?format=csv"
        try:
            res = self.session.get(
                url, headers=self._headers(token), timeout=EXPORT_TIMEOUT
            )
            if res.ok:
                return True, res.content
            return False, res.text
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
    ) -> Tuple[bool, Any]:
        """Query audit log entries."""
        url = f"{self.base_url}/audit/"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if user_id:
            params["user_id"] = user_id
        if action:
            params["action"] = action
        if success is not None:
            params["success"] = success
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


# Singleton instance
api_client = APIClient()


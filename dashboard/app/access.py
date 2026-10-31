"""Dashboard-side resource scoping for course-owned views."""

from typing import Any, Dict, List, Optional, Tuple

from app.api_client import api_client
from app.rbac import role_for_user


def filter_courses_for_user(
    user: Optional[Dict[str, Any]], courses: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Return only courses the dashboard can associate with this user's role."""
    role = role_for_user(user)
    if role == "admin":
        return courses
    if role != "instructor" or not user or not isinstance(user.get("id"), str):
        return []
    return [
        course
        for course in courses
        if course.get("instructor_id") == user["id"]
    ]


def load_visible_courses(
    token: str, user: Optional[Dict[str, Any]]
) -> Tuple[bool, List[Dict[str, Any]], Optional[str]]:
    """Load courses and apply the dashboard's owner scope before rendering."""
    role = role_for_user(user)
    if role == "ta":
        return (
            True,
            [],
            "The API does not expose TA course assignments. Course-scoped staff "
            "data is withheld until the backend provides that mapping.",
        )
    if role not in {"admin", "instructor"}:
        return False, [], "Your role cannot access course-scoped dashboard data."

    all_courses: List[Dict[str, Any]] = []
    offset = 0
    while True:
        ok, response = api_client.list_courses(
            token=token, limit=100, offset=offset
        )
        if not ok:
            return False, [], f"Unable to load courses: {response}"
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            return False, [], "Unable to load courses: invalid response format."

        page = response["items"]
        if any(not isinstance(course, dict) for course in page):
            return False, [], "Unable to load courses: invalid course entry."
        all_courses.extend(page)

        total = response.get("total")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            return False, [], "Unable to load courses: invalid total count."
        offset += len(page)
        if offset >= total or not page:
            break

    return True, filter_courses_for_user(user, all_courses), None

"""
Keeps a dashboard login alive across browser reloads.

Streamlit's session_state belongs to one websocket connection, so reloading the
page starts empty. The tokens therefore stay on the server, and the browser only
holds a random ID in a cookie that points at them. That ID is useless against
the API, and signing out deletes the server entry, which matters because the
backend's JWTs cannot be revoked.

The store lives in this process, so restarting the dashboard signs everyone out.
"""

import secrets
import threading
import time
from http.cookies import CookieError, SimpleCookie
from typing import Any, Dict, Optional, Tuple

import streamlit as st
import streamlit.components.v1 as components
from streamlit.web.server.websocket_headers import _get_websocket_headers

COOKIE_NAME = "saiv_dashboard_session"
# Matches the backend's REFRESH_TOKEN_EXPIRE_DAYS: past this the login is dead.
LOGIN_TTL_SECONDS = 7 * 24 * 60 * 60


class _LoginStore:
    """Logins by browser ID. Shared by every session, so guarded by a lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._logins: Dict[str, Dict[str, Any]] = {}

    def add(self, login: Dict[str, Any]) -> str:
        browser_id = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._logins = {
                key: value
                for key, value in self._logins.items()
                if value["expires_at"] > now
            }
            self._logins[browser_id] = {
                **login,
                "expires_at": now + LOGIN_TTL_SECONDS,
            }
        return browser_id

    def get(self, browser_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            login = self._logins.get(browser_id)
            if login and login["expires_at"] > time.time():
                return dict(login)
        return None

    def update(self, browser_id: str, changes: Dict[str, Any]) -> None:
        with self._lock:
            if browser_id in self._logins:
                self._logins[browser_id].update(changes)

    def remove(self, browser_id: str) -> None:
        with self._lock:
            self._logins.pop(browser_id, None)


@st.cache_resource
def _store() -> _LoginStore:
    return _LoginStore()


def _cookie_browser_id() -> Optional[str]:
    """Read our cookie from the headers sent when this websocket connected."""
    try:
        headers = _get_websocket_headers()
        cookie_header = headers.get("Cookie") if headers else None
        if not cookie_header:
            return None
        morsel = SimpleCookie(cookie_header).get(COOKIE_NAME)
    except (CookieError, RuntimeError):
        return None
    return morsel.value if morsel else None


def remember_login(login: Dict[str, Any]) -> str:
    """Store a login and return the ID the browser should hold."""
    return _store().add(login)


def recall_login() -> Optional[Tuple[str, Dict[str, Any]]]:
    """Find the login belonging to this browser, if it still has one."""
    browser_id = _cookie_browser_id()
    login = _store().get(browser_id) if browser_id else None
    return (browser_id, login) if login else None


def update_login(browser_id: str, changes: Dict[str, Any]) -> None:
    _store().update(browser_id, changes)


def forget_login(browser_id: str) -> None:
    _store().remove(browser_id)


def _run_cookie_script(assignment: str) -> None:
    # Streamlit cannot set a cookie from the server, so a zero-height component
    # does it from the browser. Component frames share the page's origin.
    components.html(
        f"""<script>
        const secure = window.parent.location.protocol === "https:" ? "; Secure" : "";
        window.parent.document.cookie = "{assignment}; Path=/; SameSite=Strict" + secure;
        </script>""",
        height=0,
    )


def write_cookie(browser_id: str) -> None:
    _run_cookie_script(f"{COOKIE_NAME}={browser_id}; Max-Age={LOGIN_TTL_SECONDS}")


def clear_cookie() -> None:
    _run_cookie_script(f"{COOKIE_NAME}=; Max-Age=0")

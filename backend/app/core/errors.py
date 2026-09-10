"""
Consistent error responses and request correlation.

Follows the Module 2 design guidance:

* every error body has the same shape - `detail`, a machine-readable `code`,
  and the `request_id` so a user report can be matched to a server log line;
* internal details never leak: an unhandled exception or database failure
  becomes a generic message, while the full traceback goes to the server log.
"""

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Machine-readable codes for each status the API returns.
STATUS_CODES: Dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}


def get_request_id(request: Request) -> Optional[str]:
    """Request id assigned by the middleware, if any."""
    return getattr(request.state, "request_id", None)


def error_body(detail: Any, status_code: int, request: Request, code: Optional[str] = None) -> Dict[str, Any]:
    return {
        "detail": detail,
        "code": code or STATUS_CODES.get(status_code, "ERROR"),
        "request_id": get_request_id(request),
    }


def install_request_id_middleware(app: FastAPI) -> None:
    """
    Tag every request with an id.

    Honours an incoming X-Request-ID (so the frontend or a gateway can
    propagate its own) and echoes it back on the response.
    """

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming[:64] if incoming else uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def install_exception_handlers(app: FastAPI) -> None:
    """Register the handlers that give every error the same shape."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Raised deliberately by route code (401, 403, 404, 429 ...). Message
        # is already safe to show.
        headers = dict(exc.headers or {})
        request_id = get_request_id(request)
        if request_id:
            headers[REQUEST_ID_HEADER] = request_id
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.detail, exc.status_code, request),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Keep FastAPI's per-field list in `detail`: it names every invalid
        # field and why, which is exactly what the design guidance asks for.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(
                jsonable_encoder(exc.errors()),
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                request,
            ),
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(request: Request, exc: SQLAlchemyError):
        request_id = get_request_id(request)
        logger.error(
            "Database error (request_id=%s %s %s): %s",
            request_id,
            request.method,
            request.url.path,
            exc,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(
                "Database error occurred",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                request,
                code="DATABASE_ERROR",
            ),
            headers={REQUEST_ID_HEADER: request_id} if request_id else None,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = get_request_id(request)
        # Full stack trace server-side; nothing but a generic message and the
        # correlation id goes back to the client.
        logger.error(
            "Unhandled error (request_id=%s %s %s)",
            request_id,
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(
                "Internal server error",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                request,
            ),
            headers={REQUEST_ID_HEADER: request_id} if request_id else None,
        )

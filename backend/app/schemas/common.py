"""Shared schema building blocks: UTC datetimes and pagination envelopes."""

from datetime import datetime
from typing import Annotated, Generic, List, TypeVar

from pydantic import BaseModel, PlainSerializer

T = TypeVar("T")


def _serialize_utc(value: datetime) -> str:
    """
    Render a naive-UTC datetime as ISO 8601 with an explicit 'Z'.

    Without the suffix, browsers parse the string as local time, which silently
    shifts every timestamp the frontend and dashboard display.
    """
    return value.replace(microsecond=0).isoformat() + "Z"


UTCDateTime = Annotated[datetime, PlainSerializer(_serialize_utc, return_type=str)]


class PaginatedResponse(BaseModel, Generic[T]):
    """Envelope used by every list endpoint (API-SPECIFICATION.md)."""

    items: List[T]
    total: int
    limit: int
    offset: int


class MessageResponse(BaseModel):
    """Simple acknowledgement body."""

    message: str

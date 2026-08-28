"""Small shared helpers: UUIDs and UTC timestamp normalisation."""

import uuid
from datetime import datetime, timezone
from typing import Optional


def new_uuid() -> str:
    """Primary keys are VARCHAR(36) UUID strings (see DATABASE-SCHEMA.md)."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """
    Current UTC time as a naive datetime.

    Every TIMESTAMP column in the schema is naive, so all datetimes are stored
    in UTC without tzinfo. Mixing naive and aware values raises TypeError on
    comparison, so this is the single source of "now" for the whole backend.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """
    Normalise an incoming datetime to naive UTC.

    Clients send ISO 8601 strings with a 'Z' suffix, which Pydantic parses into
    timezone-aware datetimes. Convert to UTC and drop tzinfo before storing.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def is_valid_uuid(value: str) -> bool:
    """Validate a UUID string without raising."""
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False

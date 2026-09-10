"""Device schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UTCDateTime


class DeviceCreate(BaseModel):
    """
    Device registration.

    public_key is optional even though the schema doc marks it NOT NULL: the
    web client has no key pair, and the public test suite registers without one.
    """

    device_fingerprint: str = Field(min_length=1, max_length=64)
    device_name: Optional[str] = Field(default=None, max_length=255)
    platform: Optional[str] = Field(default=None, max_length=50)
    browser: Optional[str] = Field(default=None, max_length=100)
    os_version: Optional[str] = Field(default=None, max_length=50)
    app_version: Optional[str] = Field(default=None, max_length=50)
    public_key: Optional[str] = None


class DeviceUpdate(BaseModel):
    device_name: Optional[str] = Field(default=None, max_length=255)
    is_trusted: Optional[bool] = None   # admin only
    is_active: Optional[bool] = None


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    device_fingerprint: str
    device_name: Optional[str] = None
    platform: Optional[str] = None
    browser: Optional[str] = None
    is_trusted: bool
    trust_score: str
    is_active: bool
    total_checkins: int
    first_seen_at: UTCDateTime
    last_seen_at: UTCDateTime

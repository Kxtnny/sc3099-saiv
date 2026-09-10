"""Enrollment schemas."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import UTCDateTime


class EnrollmentCreate(BaseModel):
    student_id: str
    course_id: str


class EnrollmentBulkCreate(BaseModel):
    course_id: str
    student_emails: List[EmailStr] = Field(min_length=1, max_length=500)
    create_accounts: bool = False


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    course_id: str
    is_active: bool
    enrolled_at: UTCDateTime
    dropped_at: Optional[UTCDateTime] = None


class MyEnrollmentResponse(BaseModel):
    """Student-facing view, denormalised with course details."""

    id: str
    course_id: str
    course_code: str
    course_name: str
    semester: str
    instructor_name: Optional[str] = None
    enrolled_at: UTCDateTime
    is_active: bool


class EnrolledStudent(BaseModel):
    id: str
    student_id: str
    student_email: str
    student_name: str
    enrolled_at: UTCDateTime
    is_active: bool
    face_enrolled: bool


class CourseEnrollmentList(BaseModel):
    course_id: str
    course_code: str
    total_enrolled: int
    students: List[EnrolledStudent]


class BulkEnrollmentResult(BaseModel):
    enrolled: int
    already_enrolled: int
    not_found: int
    created: int
    details: List[dict]

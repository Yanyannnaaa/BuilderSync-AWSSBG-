import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import AttendanceStatus, Department, MeetingType, TargetAudience, UserRole


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _lower(v):
    return v.strip().lower() if isinstance(v, str) else v


# ---------- Auth ----------
class CodeRequest(BaseModel):
    email: EmailStr
    send_to_personal: bool = False

    _l = field_validator("email", mode="after")(_lower)


class CodeVerify(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")

    _l = field_validator("email", mode="after")(_lower)


# ---------- Members ----------
class UserBase(BaseModel):
    student_number: str = Field(min_length=3, max_length=20)
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    year_level: int = Field(ge=1, le=5)
    school_email: EmailStr
    personal_email: EmailStr
    contact_number: str | None = Field(default=None, max_length=32)
    role: UserRole = UserRole.MEMBER
    department: Department | None = None
    officer_title: str | None = Field(default=None, max_length=60)
    is_admin: bool = False
    is_active: bool = True

    _l = field_validator("school_email", "personal_email", mode="after")(_lower)


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=50)
    last_name: str | None = Field(default=None, min_length=1, max_length=50)
    year_level: int | None = Field(default=None, ge=1, le=5)
    school_email: EmailStr | None = None
    personal_email: EmailStr | None = None
    contact_number: str | None = None
    role: UserRole | None = None
    department: Department | None = None
    officer_title: str | None = Field(default=None, max_length=60)
    is_admin: bool | None = None
    is_active: bool | None = None

    _l = field_validator("school_email", "personal_email", mode="after")(_lower)


class UserOut(ORM, UserBase):
    id: uuid.UUID
    full_name: str
    created_at: datetime
    last_login: datetime | None = None


class ImportRowError(BaseModel):
    row: int
    error: str


class ImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[ImportRowError]


# ---------- Member self-service ----------
class AttendanceHistoryItem(BaseModel):
    meeting_title: str
    meeting_date: datetime
    meeting_type: MeetingType
    is_mandatory: bool
    status: AttendanceStatus


class MyProfile(BaseModel):
    user: UserOut
    attendance_rate: float | None  # 0-100, None if no mandatory meetings logged
    meetings_logged: int
    absences: int


# ---------- Meetings & attendance ----------
class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    meeting_date: datetime
    meeting_type: MeetingType = MeetingType.GENERAL
    is_mandatory: bool = True


class MeetingOut(ORM, MeetingCreate):
    id: uuid.UUID


class AttendanceEntry(BaseModel):
    user_id: uuid.UUID | None = None
    student_number: str | None = None
    status: AttendanceStatus


class AttendanceBatch(BaseModel):
    records: list[AttendanceEntry] = Field(min_length=1)


class AttendanceOut(ORM):
    id: uuid.UUID
    meeting_id: uuid.UUID
    user_id: uuid.UUID
    status: AttendanceStatus
    logged_at: datetime


class ActivityChange(BaseModel):
    user_id: uuid.UUID
    absent_count: int
    deactivated: bool
    warning_queued: bool


class AttendanceResult(BaseModel):
    saved: list[AttendanceOut]
    not_found: list[str]
    activity_changes: list[ActivityChange]


# ---------- Submissions ----------
class SubmissionOut(ORM):
    id: uuid.UUID
    user_id: uuid.UUID
    requirement_type: str
    original_filename: str
    standardized_filename: str
    file_s3_key: str
    submitted_at: datetime


class SubmissionListItem(SubmissionOut):
    student_number: str
    full_name: str
    role: UserRole


class DownloadURL(BaseModel):
    url: str
    expires_in: int


# ---------- Announcements ----------
class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    target_audience: TargetAudience = TargetAudience.ALL


class AnnouncementOut(ORM, AnnouncementCreate):
    id: uuid.UUID
    posted_by: uuid.UUID | None = None
    sent_at: datetime
    recipient_count: int = 0


# ---------- Audit ----------
class AuditOut(ORM):
    id: uuid.UUID
    actor_label: str | None
    action: str
    detail: str | None
    ip: str | None
    created_at: datetime

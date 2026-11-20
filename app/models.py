import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    MEMBER = "Member"
    OFFICER = "Officer"


OFFICER_ROLES = (UserRole.OFFICER,)


class Department(str, enum.Enum):
    CREATIVES = "Creatives"
    MARKETING = "Marketing"
    MEDIA = "Media"
    RELATIONS = "Relations"
    OPERATIONS = "Operations"
    TECHNOLOGY = "Technology"


class MeetingType(str, enum.Enum):
    GENERAL = "General"
    EXECUTIVE = "Executive"
    COMMITTEE = "Committee"


class AttendanceStatus(str, enum.Enum):
    PRESENT = "Present"
    EXCUSED = "Excused"
    ABSENT = "Absent"


class TargetAudience(str, enum.Enum):
    ALL = "All"
    OFFICERS_ONLY = "Officers_Only"
    ACTIVE_ONLY = "Active_Only"


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    student_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    school_email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    personal_email: Mapped[str] = mapped_column(String(100), unique=True)
    contact_number: Mapped[str | None] = mapped_column(String(32))
    year_level: Mapped[int] = mapped_column(Integer)
    role: Mapped[UserRole] = mapped_column(
        _pg_enum(UserRole, "user_role"), default=UserRole.MEMBER, index=True
    )
    department: Mapped[Department | None] = mapped_column(
        _pg_enum(Department, "department"), nullable=True, index=True
    )
    officer_title: Mapped[str | None] = mapped_column(String(60))  # e.g. "President"
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attendance_records: Mapped[list["Attendance"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    announcements: Mapped[list["Announcement"]] = relationship(back_populates="author")

    __table_args__ = (CheckConstraint("year_level BETWEEN 1 AND 5", name="ck_users_year_level"),)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def is_officer(self) -> bool:
        return self.role in OFFICER_ROLES or self.is_admin


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(String(100))
    meeting_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    meeting_type: Mapped[MeetingType] = mapped_column(
        _pg_enum(MeetingType, "meeting_type"), default=MeetingType.GENERAL
    )
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    attendance_records: Mapped[list["Attendance"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class Attendance(Base):
    __tablename__ = "attendance"

    id: Mapped[uuid.UUID] = _uuid_pk()
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[AttendanceStatus] = mapped_column(
        _pg_enum(AttendanceStatus, "attendance_status"), default=AttendanceStatus.ABSENT
    )
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting: Mapped[Meeting] = relationship(back_populates="attendance_records")
    user: Mapped[User] = relationship(back_populates="attendance_records")

    __table_args__ = (UniqueConstraint("meeting_id", "user_id", name="uq_attendance_meeting_user"),)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    requirement_type: Mapped[str] = mapped_column(String(50), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    standardized_filename: Mapped[str] = mapped_column(String(255))
    file_s3_key: Mapped[str] = mapped_column(String(512), unique=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="submissions")


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    target_audience: Mapped[TargetAudience] = mapped_column(
        _pg_enum(TargetAudience, "target_audience"), default=TargetAudience.ALL
    )
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    author: Mapped[User | None] = relationship(back_populates="announcements")


# ---------------- auth & audit ----------------
class LoginCode(Base):
    __tablename__ = "login_codes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_label: Mapped[str | None] = mapped_column(String(150))  # snapshot of name/email
    action: Mapped[str] = mapped_column(String(60), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

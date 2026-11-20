"""Rule A: Active/Inactive status engine."""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Attendance, AttendanceStatus, Meeting, User


@dataclass
class ActivityResult:
    user_id: uuid.UUID
    absent_count: int
    deactivated: bool = False
    send_warning: bool = False


def evaluate_member_activity(db: Session, user_id: uuid.UUID) -> ActivityResult:
    """Look at the member's last N mandatory meetings (N = limit, default 3).

    - absent_count >= limit  -> is_active = False
    - absent_count == warn   -> caller should send the heads-up email
    Excused counts as not absent. Fewer than N records never deactivates.
    """
    s = get_settings()
    limit = s.consecutive_absence_limit
    rows = db.scalars(
        select(Attendance.status)
        .join(Meeting, Meeting.id == Attendance.meeting_id)
        .where(Attendance.user_id == user_id, Meeting.is_mandatory.is_(True))
        .order_by(Meeting.meeting_date.desc(), Meeting.id.desc())
        .limit(limit)
    ).all()
    absent = sum(1 for st in rows if st == AttendanceStatus.ABSENT)
    result = ActivityResult(user_id=user_id, absent_count=absent)

    user = db.get(User, user_id)
    if user is None:
        return result
    if len(rows) >= limit and absent >= limit:
        if user.is_active:
            user.is_active = False
            result.deactivated = True
    elif absent == s.warning_absence_threshold and user.is_active:
        result.send_warning = True
    return result


def warning_email_html(full_name: str, limit: int) -> str:
    return (
        f"<p>Hi {full_name},</p>"
        f"<p>Heads-up: you have missed 2 of your last {limit} mandatory meetings. "
        f"One more absence will mark your membership as <b>Inactive</b>.</p>"
        "<p>If you have a valid reason, please contact the Secretary to file an excuse.</p>"
    )

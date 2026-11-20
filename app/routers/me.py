from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.deps import current_user
from app.models import Attendance, AttendanceStatus, Meeting, User

router = APIRouter(prefix="/api/me", tags=["me"])


def _history(db: Session, user: User):
    return db.execute(
        select(Attendance, Meeting)
        .join(Meeting, Meeting.id == Attendance.meeting_id)
        .where(Attendance.user_id == user.id)
        .order_by(Meeting.meeting_date.desc())
    ).all()


@router.get("/profile", response_model=schemas.MyProfile)
def profile(db: Session = Depends(get_db), user: User = Depends(current_user)):
    mandatory = [a for a, m in _history(db, user) if m.is_mandatory]
    attended = sum(1 for a in mandatory if a.status in (AttendanceStatus.PRESENT, AttendanceStatus.EXCUSED))
    rate = round(100 * attended / len(mandatory), 1) if mandatory else None
    return schemas.MyProfile(
        user=schemas.UserOut.model_validate(user),
        attendance_rate=rate,
        meetings_logged=len(mandatory),
        absences=sum(1 for a in mandatory if a.status == AttendanceStatus.ABSENT),
    )


@router.get("/attendance", response_model=list[schemas.AttendanceHistoryItem])
def my_attendance(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [
        schemas.AttendanceHistoryItem(
            meeting_title=m.title,
            meeting_date=m.meeting_date,
            meeting_type=m.meeting_type,
            is_mandatory=m.is_mandatory,
            status=a.status,
        )
        for a, m in _history(db, user)
    ]

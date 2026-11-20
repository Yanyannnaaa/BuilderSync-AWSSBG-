import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.config import get_settings
from app.database import get_db
from app.deps import require_officer
from app.models import Attendance, Meeting, User
from app.services.audit_service import audit
from app.services.activity_service import evaluate_member_activity, warning_email_html
from app.services.email_service import send_batch_emails

router = APIRouter(prefix="/api/meetings", tags=["attendance"], dependencies=[Depends(require_officer)])


@router.post("", response_model=schemas.MeetingOut, status_code=201)
def create_meeting(
    body: schemas.MeetingCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_officer)
):
    meeting = Meeting(**body.model_dump())
    db.add(meeting)
    audit(db, actor, 'meeting_create', body.title, request)
    db.commit()
    return meeting


@router.get("", response_model=list[schemas.MeetingOut])
def list_meetings(db: Session = Depends(get_db)):
    return db.scalars(select(Meeting).order_by(Meeting.meeting_date.desc())).all()


@router.get("/{meeting_id}/attendance", response_model=list[schemas.AttendanceOut])
def get_attendance(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    if not db.get(Meeting, meeting_id):
        raise HTTPException(404, "Meeting not found")
    return db.scalars(select(Attendance).where(Attendance.meeting_id == meeting_id)).all()


@router.post("/{meeting_id}/attendance", response_model=schemas.AttendanceResult)
def record_attendance(
    meeting_id: uuid.UUID,
    body: schemas.AttendanceBatch,
    background: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_officer),
):
    """Upsert attendance for a meeting, then run the Active/Inactive engine."""
    if not db.get(Meeting, meeting_id):
        raise HTTPException(404, "Meeting not found")

    saved: list[Attendance] = []
    not_found: list[str] = []
    for entry in body.records:
        if entry.user_id:
            user = db.get(User, entry.user_id)
        elif entry.student_number:
            user = db.scalars(select(User).where(User.student_number == entry.student_number)).first()
        else:
            raise HTTPException(422, "Each record needs user_id or student_number")
        if not user:
            not_found.append(str(entry.user_id or entry.student_number))
            continue
        rec = db.scalars(
            select(Attendance).where(Attendance.meeting_id == meeting_id, Attendance.user_id == user.id)
        ).first()
        if rec:
            rec.status = entry.status
        else:
            rec = Attendance(meeting_id=meeting_id, user_id=user.id, status=entry.status)
            db.add(rec)
        saved.append(rec)
    db.flush()

    limit = get_settings().consecutive_absence_limit
    changes: list[schemas.ActivityChange] = []
    for rec in saved:
        res = evaluate_member_activity(db, rec.user_id)
        if res.deactivated or res.send_warning:
            if res.send_warning:
                u = db.get(User, rec.user_id)
                background.add_task(
                    send_batch_emails,
                    [u.school_email, u.personal_email],
                    "Attendance warning: one absence away from Inactive",
                    warning_email_html(u.first_name, limit),
                )
            changes.append(
                schemas.ActivityChange(
                    user_id=res.user_id,
                    absent_count=res.absent_count,
                    deactivated=res.deactivated,
                    warning_queued=res.send_warning,
                )
            )
    audit(db, actor, 'attendance_record', f'meeting={meeting_id} records={len(saved)}', request)
    db.commit()
    return schemas.AttendanceResult(
        saved=[schemas.AttendanceOut.model_validate(r) for r in saved],
        not_found=not_found,
        activity_changes=changes,
    )

import html

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.deps import current_user, require_officer
from app.models import OFFICER_ROLES, Announcement, TargetAudience, User
from app.services.audit_service import audit
from app.services.email_service import send_batch_emails

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


def _render_html(title: str, content: str) -> str:
    body = "<br>".join(html.escape(content).splitlines())
    return f"<h2>{html.escape(title)}</h2><p>{body}</p>"


@router.post("", response_model=schemas.AnnouncementOut, status_code=201)
def create_announcement(
    body: schemas.AnnouncementCreate,
    background: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_officer),
):
    stmt = select(User)
    if body.target_audience == TargetAudience.OFFICERS_ONLY:
        stmt = stmt.where(User.role.in_(OFFICER_ROLES) | User.is_admin.is_(True))
    elif body.target_audience == TargetAudience.ACTIVE_ONLY:
        stmt = stmt.where(User.is_active.is_(True))
    recipients = [e for u in db.scalars(stmt) for e in (u.school_email, u.personal_email) if e]

    ann = Announcement(**body.model_dump(), posted_by=actor.id)
    db.add(ann)
    audit(db, actor, "announcement_post", f"{body.title} -> {body.target_audience.value}", request)
    db.commit()

    background.add_task(send_batch_emails, recipients, body.title, _render_html(body.title, body.content))
    out = schemas.AnnouncementOut.model_validate(ann)
    out.recipient_count = len({r.lower() for r in recipients})
    return out


@router.get("", response_model=list[schemas.AnnouncementOut])
def list_announcements(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Officers see everything; members only see announcements aimed at them."""
    stmt = select(Announcement).order_by(Announcement.sent_at.desc()).limit(50)
    if not user.is_officer:
        allowed = [TargetAudience.ALL] + ([TargetAudience.ACTIVE_ONLY] if user.is_active else [])
        stmt = stmt.where(Announcement.target_audience.in_(allowed))
    return db.scalars(stmt).all()

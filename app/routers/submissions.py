import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.config import get_settings
from app.database import get_db
from app.deps import current_user, require_officer
from app.models import Submission, User
from app.services import storage_service as storage
from app.services.audit_service import audit

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


@router.get("/preview-name")
def preview_name(requirement_type: str, ext: str = "pdf", user: User = Depends(current_user)):
    """Live filename preview for the member dropzone."""
    if not re.fullmatch(r"[A-Za-z0-9_]{1,50}", requirement_type) or ext.lower() not in storage.ALLOWED_EXTENSIONS:
        raise HTTPException(422, "Invalid requirement type or extension")
    name = storage.standardized_filename(user, requirement_type, ext.lower())
    return {"filename": name, "key": storage.build_key(user, requirement_type, name)}


@router.post("/upload", response_model=schemas.SubmissionOut, status_code=201)
async def upload_submission(
    request: Request,
    requirement_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # identity comes from the session, never from the form
):
    if not re.fullmatch(r"[A-Za-z0-9_]{1,50}", requirement_type):
        raise HTTPException(422, "requirement_type may only contain letters, digits and underscores")
    ext = storage.get_extension(file.filename or "")
    if not ext:
        raise HTTPException(415, "Only .pdf, .docx and .png files are allowed")
    if not storage.s3_configured():
        raise HTTPException(503, "S3 is not configured (set S3_BUCKET_NAME and AWS credentials)")

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > max_bytes:
        raise HTTPException(413, f"File exceeds {get_settings().max_upload_mb} MB")

    new_name = storage.standardized_filename(user, requirement_type, ext)
    key = storage.build_key(user, requirement_type, new_name)
    try:
        storage.upload_stream(file.file, key, ext)
    except Exception as e:
        raise HTTPException(502, f"S3 upload failed: {type(e).__name__}")

    sub = db.scalars(select(Submission).where(Submission.file_s3_key == key)).first()
    if sub:  # same-day re-upload overwrites
        sub.original_filename = file.filename
    else:
        sub = Submission(
            user_id=user.id,
            requirement_type=requirement_type,
            original_filename=file.filename,
            standardized_filename=new_name,
            file_s3_key=key,
        )
        db.add(sub)
    audit(db, user, "submission_upload", new_name, request)
    db.commit()
    return sub


@router.get("/mine", response_model=list[schemas.SubmissionOut])
def my_submissions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(
        select(Submission).where(Submission.user_id == user.id).order_by(Submission.submitted_at.desc())
    ).all()


@router.get("", response_model=list[schemas.SubmissionListItem], dependencies=[Depends(require_officer)])
def list_submissions(requirement_type: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Submission, User).join(User, User.id == Submission.user_id).order_by(Submission.submitted_at.desc())
    if requirement_type:
        stmt = stmt.where(Submission.requirement_type == requirement_type)
    out = []
    for sub, u in db.execute(stmt):
        item = schemas.SubmissionOut.model_validate(sub).model_dump()
        out.append(
            schemas.SubmissionListItem(**item, student_number=u.student_number, full_name=u.full_name, role=u.role)
        )
    return out


@router.get("/{submission_id}/download", response_model=schemas.DownloadURL)
def download_url(
    submission_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_officer)
):
    sub = db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    if not storage.s3_configured():
        raise HTTPException(503, "S3 is not configured")
    audit(db, actor, "submission_download", sub.standardized_filename, request)
    db.commit()
    url, ttl = storage.presigned_download_url(sub.file_s3_key, sub.standardized_filename)
    return schemas.DownloadURL(url=url, expires_in=ttl)

import csv
import io
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.deps import require_officer
from app.models import Department, User, UserRole
from app.services.audit_service import audit

router = APIRouter(prefix="/api/members", tags=["members"], dependencies=[Depends(require_officer)])

PRIVILEGED_FIELDS = ("role", "officer_title", "is_admin")


def _duplicate(db: Session, data: dict, exclude: uuid.UUID | None = None) -> str | None:
    conds = []
    if data.get("student_number"):
        conds.append(User.student_number == data["student_number"])
    for f in ("school_email", "personal_email"):
        if data.get(f):
            # an address may not collide with either email column of another user
            conds += [User.school_email == data[f], User.personal_email == data[f]]
    if not conds:
        return None
    q = select(User).where(or_(*conds))
    if exclude:
        q = q.where(User.id != exclude)
    hit = db.scalars(q).first()
    return "Student number or email already registered" if hit else None


def _forbid_privilege(actor: User, role: UserRole | None, title: str | None, is_admin: bool | None = None):
    if not actor.is_admin and ((role and role != UserRole.MEMBER) or title or is_admin):
        raise HTTPException(403, "Only an Admin can assign officer roles, titles, or admin access")


@router.get("", response_model=list[schemas.UserOut])
def list_members(
    role: list[UserRole] | None = Query(None),
    department: list[Department] | None = Query(None),
    year_level: list[int] | None = Query(None),
    is_active: bool | None = None,
    q: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.last_name, User.first_name)
    if role:
        stmt = stmt.where(User.role.in_(role))
    if department:
        stmt = stmt.where(User.department.in_(department))
    if year_level:
        stmt = stmt.where(User.year_level.in_(year_level))
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            User.first_name.ilike(like) | User.last_name.ilike(like) | User.student_number.ilike(like)
        )
    return db.scalars(stmt).all()


@router.post("", response_model=schemas.UserOut, status_code=201)
def create_member(
    body: schemas.UserCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_officer)
):
    _forbid_privilege(actor, body.role, body.officer_title, body.is_admin)
    if _duplicate(db, body.model_dump()):
        raise HTTPException(409, "Student number or email already registered")
    user = User(**body.model_dump())
    db.add(user)
    audit(db, actor, "member_create", f"{user.student_number} role={user.role.value}", request)
    db.commit()
    return user


@router.post("/import-csv", response_model=schemas.ImportResult)
async def import_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(require_officer),
):
    """Headers: student_number, first_name, last_name, year_level, school_email, personal_email
    (+ optional department, contact_number, role, officer_title)."""
    raw = (await file.read(5 * 1024 * 1024 + 1))
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "CSV too large (5 MB max)")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
    required = {"student_number", "first_name", "last_name", "year_level", "school_email", "personal_email"}
    if not reader.fieldnames or not required <= {h.strip().lower() for h in reader.fieldnames if h}:
        raise HTTPException(400, f"CSV must include columns: {', '.join(sorted(required))}")

    created = skipped = 0
    errors: list[schemas.ImportRowError] = []
    seen = set(db.scalars(select(User.student_number))) | set(db.scalars(select(User.school_email))) | set(
        db.scalars(select(User.personal_email))
    )
    for i, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        for k in ("contact_number", "officer_title", "department"):
            row[k] = row.get(k) or None
        if row["department"]:
            row["department"] = row["department"].title()
        row["role"] = (row.get("role") or "Member").title()
        try:
            data = schemas.UserCreate.model_validate(row)
        except ValidationError as e:
            err = e.errors()[0]
            errors.append(schemas.ImportRowError(row=i, error=f"{err['loc'][0]}: {err['msg']}"))
            continue
        if not actor.is_admin and (data.role != UserRole.MEMBER or data.officer_title or data.is_admin):
            errors.append(schemas.ImportRowError(row=i, error="Only an Admin can import officer roles/titles"))
            continue
        keys = {data.student_number, str(data.school_email), str(data.personal_email)}
        if keys & seen:
            skipped += 1
            continue
        db.add(User(**data.model_dump()))
        seen |= keys
        created += 1
    audit(db, actor, "member_import_csv", f"created={created} skipped={skipped} errors={len(errors)}", request)
    db.commit()
    return schemas.ImportResult(created=created, skipped=skipped, errors=errors)


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_member(user_id: uuid.UUID, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Member not found")
    return user


@router.patch("/{user_id}", response_model=schemas.UserOut)
def update_member(
    user_id: uuid.UUID,
    body: schemas.UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_officer),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Member not found")
    data = body.model_dump(exclude_unset=True)
    if not actor.is_admin:
        if user.role != UserRole.MEMBER or user.is_admin:
            raise HTTPException(403, "Only an Admin can edit officer accounts")
        for f in PRIVILEGED_FIELDS:
            if f in data and data[f] != getattr(user, f) and not (f == "role" and data[f] == UserRole.MEMBER) and not (f == "is_admin" and data[f] is False):
                raise HTTPException(403, "Only an Admin can change roles, titles, or admin access")
    if data.get("is_admin") is False and user.is_admin:
        admins = db.scalars(select(User).where(User.is_admin.is_(True))).all()
        if len(admins) <= 1:
            raise HTTPException(409, "Cannot remove admin access from the last Admin")
    if _duplicate(db, data, exclude=user.id):
        raise HTTPException(409, "Email already registered")
    changes = {k: v for k, v in data.items() if getattr(user, k) != v}
    for k, v in data.items():
        setattr(user, k, v)
    audit(db, actor, "member_update", f"{user.student_number}: {', '.join(f'{k}={getattr(v, 'value', v)}' for k, v in changes.items())}", request)
    db.commit()
    return user


@router.delete("/{user_id}", status_code=204)
def delete_member(
    user_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_officer)
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Member not found")
    if user.id == actor.id:
        raise HTTPException(409, "You cannot delete your own account")
    if (user.role != UserRole.MEMBER or user.is_admin) and not actor.is_admin:
        raise HTTPException(403, "Only an Admin can delete officer accounts")
    audit(db, actor, "member_delete", user.student_number, request)
    db.delete(user)
    db.commit()

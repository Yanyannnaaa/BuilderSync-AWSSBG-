import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_db, init_models
from app.routers import announcements, attendance, audit, auth, me, members, submissions
from app.services.auth_service import COOKIE_NAME, get_session_user

_ready = False


def _seed_demo_if_empty() -> None:
    if not os.getenv("VERCEL"):
        return
    from app.models import Announcement, Attendance, AttendanceStatus, Department, Meeting, TargetAudience, User, UserRole

    with SessionLocal() as db:
        if db.scalars(select(User.id).limit(1)).first():
            return
        pres = User(
            student_number="2019-108253", first_name="Julianna", last_name="Villaluna",
            school_email="jullianna.villaluna@my.jru.edu", personal_email="yanadigital@email.com",
            year_level=4, role=UserRole.OFFICER, is_admin=True, officer_title="President",
        )
        tech = User(
            student_number="2021-00412", first_name="Marco", last_name="Santos",
            school_email="marco.santos@my.jru.edu", personal_email="marco.s@gmail.com",
            year_level=3, role=UserRole.OFFICER, department=Department.TECHNOLOGY, officer_title="Chief of Technology",
        )
        m1 = User(
            student_number="2023-10992", first_name="Juan", last_name="Dela Cruz",
            school_email="juan.delacruz@my.jru.edu", personal_email="juan.dc@gmail.com",
            year_level=3, role=UserRole.MEMBER, department=Department.CREATIVES, is_active=True,
        )
        m2 = User(
            student_number="2023-11005", first_name="Maria", last_name="Reyes",
            school_email="maria.reyes@my.jru.edu", personal_email="maria.r@gmail.com",
            year_level=2, role=UserRole.MEMBER, department=Department.MARKETING, is_active=False,
        )
        db.add_all([pres, tech, m1, m2])
        db.flush()
        mtg = Meeting(title="AWS SBG General Assembly", meeting_date=datetime.now(timezone.utc), is_mandatory=True)
        db.add(mtg)
        db.flush()
        db.add_all([
            Attendance(meeting_id=mtg.id, user_id=pres.id, status=AttendanceStatus.PRESENT),
            Attendance(meeting_id=mtg.id, user_id=m1.id, status=AttendanceStatus.PRESENT),
            Attendance(meeting_id=mtg.id, user_id=m2.id, status=AttendanceStatus.ABSENT),
        ])
        db.add(Announcement(
            title="Welcome to BuilderSync",
            content="Preview mode is active. Explore the Officer and Member portals!",
            target_audience=TargetAudience.ALL,
            posted_by=pres.id,
        ))
        db.commit()


def ensure_ready() -> None:
    global _ready
    if not _ready:
        init_models()
        _seed_demo_if_empty()
        _ready = True


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_ready()
    yield


app = FastAPI(title="BuilderSync", lifespan=lifespan)


@app.middleware("http")
async def _init_mw(request: Request, call_next):
    ensure_ready()
    return await call_next(request)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, me, members, attendance, submissions, announcements, audit):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND / "static"), name="static")


def _page(name: str) -> FileResponse:
    return FileResponse(FRONTEND / name, headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def root(request: Request, db: Session = Depends(get_db)):
    user = get_session_user(db, request.cookies.get(COOKIE_NAME))
    if not user:
        return RedirectResponse("/login")
    return RedirectResponse("/admin" if user.is_officer else "/member")


@app.get("/login", include_in_schema=False)
def login_page():
    return _page("login.html")


@app.get("/member", include_in_schema=False)
def member_page(request: Request, db: Session = Depends(get_db)):
    user = get_session_user(db, request.cookies.get(COOKIE_NAME))
    return _page("member.html") if user else RedirectResponse("/login")


@app.get("/admin", include_in_schema=False)
def admin_page(request: Request, db: Session = Depends(get_db)):
    user = get_session_user(db, request.cookies.get(COOKIE_NAME))
    if not user:
        return RedirectResponse("/login")
    return _page("admin.html") if user.is_officer else RedirectResponse("/member")

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, init_models
from app.routers import announcements, attendance, audit, auth, me, members, submissions
from app.services.auth_service import COOKIE_NAME, get_session_user


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_models()  # dev convenience; use Alembic in production
    yield


app = FastAPI(title="BuilderSync", lifespan=lifespan)
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

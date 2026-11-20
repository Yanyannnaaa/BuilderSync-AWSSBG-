import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import schemas
from app.config import get_settings
from app.database import SessionLocal, get_db
from app.deps import current_user
from app.models import User
from app.services import auth_service as auth
from app.services.audit_service import audit, client_ip
from app.services.email_service import send_email

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("uvicorn.error")

def deliver_code(user_id, to: str, html: str, text: str) -> None:
    """Background task: email the code; on failure record it for admins (page stays generic)."""
    try:
        send_email(to, "Your BuilderSync login code", html, text)
    except Exception as e:  # noqa: BLE001
        log.error("Login code email to %s failed: %s: %s", to, type(e).__name__, e)
        with SessionLocal() as db:
            user = db.get(User, user_id)
            audit(db, user, "login_email_failed", f"{type(e).__name__}: {str(e)[:300]}")
            db.commit()


GENERIC = {"detail": "If that email is registered, a login code has been sent."}


@router.post("/request-code")
def request_code(
    body: schemas.CodeRequest,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Always returns the same response so emails can't be enumerated."""
    user = auth.find_user_by_email(db, body.email)
    if user is None:
        return GENERIC
    if auth.recent_code_count(db, user.id) >= 3:
        audit(db, user, "login_code_throttled", request=request)
        db.commit()
        return GENERIC
    code = auth.create_login_code(db, user)
    audit(db, user, "login_code_requested", request=request)
    db.commit()

    s = get_settings()
    to = user.personal_email if body.send_to_personal else user.school_email
    if s.dev_print_login_codes:
        log.warning("DEV LOGIN CODE for %s: %s", to, code)
    else:
        html = (
            f"<p>Hi {user.first_name},</p><p>Your BuilderSync login code is "
            f"<b style='font-size:22px;letter-spacing:4px'>{code}</b></p>"
            f"<p>It expires in {s.login_code_ttl_minutes} minutes. If you didn't request it, ignore this email.</p>"
        )
        text = f"Your BuilderSync login code is {code}. It expires in {s.login_code_ttl_minutes} minutes."
        background.add_task(deliver_code, user.id, to, html, text)
    if s.demo_show_login_code:  # demo only: no email is needed, code is shown on the page
        return {**GENERIC, "demo_code": code, "demo": True}
    return GENERIC


@router.post("/verify")
def verify(body: schemas.CodeVerify, request: Request, response: Response, db: Session = Depends(get_db)):
    user = auth.find_user_by_email(db, body.email)
    if user is None or not auth.verify_login_code(db, user, body.code):
        audit(db, user, "login_failed", detail=body.email, request=request, actor_label=body.email)
        db.commit()
        raise HTTPException(401, "Invalid or expired code")
    token, expires = auth.create_session(db, user, client_ip(request))
    audit(db, user, "login", request=request)
    db.commit()
    s = get_settings()
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=s.session_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
        path="/",
    )
    return {"role": user.role.value, "redirect": "/admin" if user.is_officer else "/member"}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(auth.COOKIE_NAME)
    user = auth.get_session_user(db, token)
    if user:
        audit(db, user, "logout", request=request)
    auth.destroy_session(db, token)
    db.commit()
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"detail": "Signed out"}


@router.get("/me", response_model=schemas.UserOut)
def me(user: User = Depends(current_user)):
    return user

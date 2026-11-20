import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuthSession, LoginCode, User

COOKIE_NAME = "session"


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite drops tzinfo


def _hash_code(user_id, code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(User.school_email == email.strip().lower())).first()


def recent_code_count(db: Session, user_id, minutes: int = 10) -> int:
    since = now() - timedelta(minutes=minutes)
    rows = db.scalars(select(LoginCode.created_at).where(LoginCode.user_id == user_id)).all()
    return sum(1 for r in rows if _aware(r) >= since)


def create_login_code(db: Session, user: User) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    s = get_settings()
    # invalidate older codes
    for old in db.scalars(select(LoginCode).where(LoginCode.user_id == user.id, LoginCode.used.is_(False))):
        old.used = True
    db.add(
        LoginCode(
            user_id=user.id,
            code_hash=_hash_code(user.id, code),
            expires_at=now() + timedelta(minutes=s.login_code_ttl_minutes),
        )
    )
    return code


def verify_login_code(db: Session, user: User, code: str) -> bool:
    s = get_settings()
    rec = db.scalars(
        select(LoginCode)
        .where(LoginCode.user_id == user.id, LoginCode.used.is_(False))
        .order_by(LoginCode.created_at.desc())
    ).first()
    if not rec or _aware(rec.expires_at) < now() or rec.attempts >= s.login_code_max_attempts:
        return False
    rec.attempts += 1
    if hmac.compare_digest(rec.code_hash, _hash_code(user.id, code.strip())):
        rec.used = True
        return True
    return False


def create_session(db: Session, user: User, ip: str | None) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = now() + timedelta(hours=get_settings().session_hours)
    db.add(AuthSession(token_hash=hash_token(token), user_id=user.id, expires_at=expires, ip=ip))
    user.last_login = now()
    return token, expires


def get_session_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    sess = db.scalars(select(AuthSession).where(AuthSession.token_hash == hash_token(token))).first()
    if not sess or _aware(sess.expires_at) < now():
        return None
    return db.get(User, sess.user_id)


def destroy_session(db: Session, token: str | None) -> None:
    if not token:
        return
    sess = db.scalars(select(AuthSession).where(AuthSession.token_hash == hash_token(token))).first()
    if sess:
        db.delete(sess)

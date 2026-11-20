from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.services.auth_service import COOKIE_NAME, get_session_user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_session_user(db, request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(401, "Not signed in")
    return user


def require_officer(user: User = Depends(current_user)) -> User:
    if not user.is_officer:
        raise HTTPException(403, "Officer access required")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user

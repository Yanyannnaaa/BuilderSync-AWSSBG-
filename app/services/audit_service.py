from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def client_ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


def audit(
    db: Session,
    user: User | None,
    action: str,
    detail: str | None = None,
    request: Request | None = None,
    actor_label: str | None = None,
) -> None:
    """Add an audit row to the session; the caller commits with its own transaction."""
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            actor_label=actor_label or (f"{user.full_name} <{user.school_email}>" if user else None),
            action=action,
            detail=detail,
            ip=client_ip(request),
        )
    )

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

_kwargs = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    _kwargs = {"connect_args": {"check_same_thread": False}}

engine = create_engine(settings.database_url, echo=settings.db_echo, **_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_models() -> None:
    """Create tables (dev). Use Alembic in production."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

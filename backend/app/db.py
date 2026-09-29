from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker, Session
from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow() -> datetime:
    """Naive UTC datetime, the format stored in MySQL."""
    n = datetime.now(timezone.utc).replace(tzinfo=None)
    return n.replace(microsecond=n.microsecond // 1000 * 1000)


def parse_dt(value) -> datetime | None:
    """Parse an ISO string from the browser (with or without Z/offset) into naive UTC."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def next_id(db: Session, prefix: str) -> str:
    """Allocate the next reference number (e.g. AST-00042) under a row lock."""
    row = db.execute(text("SELECT value FROM counters WHERE name=:n FOR UPDATE"), {"n": prefix}).first()
    if row is None:
        db.execute(text("INSERT INTO counters (name, value) VALUES (:n, 0)"), {"n": prefix})
        value = 0
    else:
        value = row[0]
    value += 1
    db.execute(text("UPDATE counters SET value=:v WHERE name=:n"), {"v": value, "n": prefix})
    return f"{prefix}-{value:05d}"

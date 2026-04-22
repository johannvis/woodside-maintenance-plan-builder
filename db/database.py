from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from config import DATABASE_URL
from db.models import Base

_is_sqlite = DATABASE_URL.startswith("sqlite")

_connect_args = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}

# NullPool: each call to get_session() opens a fresh connection and closes it
# on session.close() — no shared pool, no contention between threads.
engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    poolclass=NullPool if _is_sqlite else None,
)

# Enable WAL mode for SQLite — allows concurrent reads alongside writes
if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_wal_mode(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA busy_timeout=30000")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal()

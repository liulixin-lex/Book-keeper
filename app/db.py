import sqlite3
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
settings.ensure_directories()

connect_args: dict[str, object] = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=FULL")
    cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
    cursor.close()


def sqlite_version_tuple() -> tuple[int, int, int]:
    values = sqlite3.sqlite_version.split(".")[:3]
    return tuple(int(value) for value in values)  # type: ignore[return-value]


def validate_sqlite_runtime() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    minimum = tuple(int(value) for value in settings.sqlite_min_version.split("."))
    if sqlite_version_tuple() < minimum:
        raise RuntimeError(
            f"SQLite {settings.sqlite_min_version}+ is required; found {sqlite3.sqlite_version}"
        )


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session

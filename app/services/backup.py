from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.config import Settings, get_settings


class BackupError(RuntimeError):
    pass


def sqlite_database_path(settings: Settings | None = None) -> Path:
    current = settings or get_settings()
    prefix = "sqlite:///"
    if not current.database_url.startswith(prefix):
        raise BackupError("Backup API currently supports SQLite only")
    return Path(current.database_url.removeprefix(prefix)).resolve()


def create_backup(settings: Settings | None = None) -> Path:
    current = settings or get_settings()
    source_path = sqlite_database_path(current)
    if not source_path.exists():
        raise BackupError(f"Database does not exist: {source_path}")
    backup_dir = Path(current.backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    target_path = backup_dir / f"ledger-{timestamp}.db"
    with (
        closing(sqlite3.connect(source_path)) as source,
        closing(sqlite3.connect(target_path)) as target,
    ):
        source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            target.close()
            target_path.unlink(missing_ok=True)
            raise BackupError("Backup integrity check failed")
    return target_path


def verify_backup(path: Path) -> bool:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return bool(row and row[0] == "ok")


def restore_backup(path: Path, settings: Settings | None = None) -> Path:
    current = settings or get_settings()
    source_path = path.resolve()
    target_path = sqlite_database_path(current)
    if not source_path.is_file() or not verify_backup(source_path):
        raise BackupError("Backup file is missing or failed integrity validation")
    if source_path == target_path:
        raise BackupError("Backup source and database target must be different files")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_name(f".{target_path.name}.restore-{uuid4().hex}.tmp")
    try:
        with (
            closing(sqlite3.connect(source_path)) as source,
            closing(sqlite3.connect(temporary)) as target,
        ):
            source.backup(target)
        if not verify_backup(temporary):
            raise BackupError("Restored database failed integrity validation")
        for suffix in ("-wal", "-shm"):
            target_path.with_name(f"{target_path.name}{suffix}").unlink(missing_ok=True)
        temporary.replace(target_path)
        if not verify_backup(target_path):
            raise BackupError("Restored database failed post-replacement validation")
    finally:
        temporary.unlink(missing_ok=True)
    return target_path

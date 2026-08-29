import sqlite3
from contextlib import closing
from pathlib import Path

from app.config import Settings
from app.services.backup import create_backup, restore_backup, verify_backup


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'ledger.db'}",
        backup_dir=tmp_path / "backups",
    )


def test_online_backup_and_restore(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = tmp_path / "ledger.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('original')")
        connection.commit()
    backup = create_backup(settings)
    assert verify_backup(backup)

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE sample SET value = 'changed'")
        connection.commit()
    wal_path = database.with_name(f"{database.name}-wal")
    shm_path = database.with_name(f"{database.name}-shm")
    wal_path.write_bytes(b"stale wal sidecar")
    shm_path.write_bytes(b"stale shm sidecar")
    restored = restore_backup(backup, settings)
    assert not wal_path.exists()
    assert not shm_path.exists()
    with closing(sqlite3.connect(restored)) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("original",)

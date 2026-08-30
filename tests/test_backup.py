import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.ai.crypto import encrypt_secret
from app.config import Settings
from app.db import Base
from app.models import BackupRun, BackupSettings
from app.services.backup import (
    create_backup,
    next_scheduled_backup_at,
    restore_backup,
    run_remote_backup,
    verify_backup,
)


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


class FakeS3Client:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str]] = []
        self.deleted: list[tuple[str, str]] = []

    def upload_file(
        self,
        file_name: str,
        bucket: str,
        key: str,
        *,
        ExtraArgs: dict[str, str],
    ) -> None:
        assert ExtraArgs == {"ContentType": "application/vnd.sqlite3"}
        assert Path(file_name).is_file()
        self.uploads.append((file_name, bucket, key))

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append((Bucket, Key))


def test_remote_backup_uploads_verified_sqlite_snapshot(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        app_env="test",
        app_secret_key="test-backup-secret",
        database_url=f"sqlite:///{tmp_path / 'ledger.db'}",
        backup_dir=tmp_path / "backups",
        _env_file=None,
    )
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    fake_s3 = FakeS3Client()
    monkeypatch.setattr(
        "app.services.backup.create_object_storage_client",
        lambda _configuration: fake_s3,
    )

    with factory() as session:
        session.add(
            BackupSettings(
                id="default",
                storage_type="r2",
                endpoint_url="https://account.r2.cloudflarestorage.com",
                region="auto",
                bucket="ledger-backups",
                access_key_id="access-key",
                encrypted_secret_access_key=encrypt_secret(
                    "secret-key", settings.app_secret_key
                ),
                prefix="book-keeper",
                retain_days=14,
                retain_count=10,
            )
        )
        session.commit()

        record = run_remote_backup(session, trigger="manual", settings=settings)
        assert record.status == "completed"
        assert record.object_key is not None
        assert record.object_key.startswith("book-keeper/")
        assert record.checksum_sha256 is not None
        assert len(record.checksum_sha256) == 64
        assert record.size_bytes and record.size_bytes > 0
        assert len(fake_s3.uploads) == 1
        assert fake_s3.uploads[0][1] == "ledger-backups"
        assert session.scalar(select(BackupRun).where(BackupRun.id == record.id)) is not None

    engine.dispose()


def test_cron_schedule_uses_configured_timezone() -> None:
    after = datetime(2026, 8, 30, 16, 30, tzinfo=UTC)
    next_run = next_scheduled_backup_at("0 2 * * *", "Asia/Shanghai", after)
    assert next_run == datetime(2026, 8, 30, 18, 0, tzinfo=UTC)

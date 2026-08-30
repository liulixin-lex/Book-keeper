from __future__ import annotations

import hashlib
import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from croniter import croniter  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.crypto import SecretDecryptionError, decrypt_secret
from app.config import Settings, get_settings
from app.models import BackupRun, BackupSettings

logger = logging.getLogger("ledger.backup")


class BackupError(RuntimeError):
    pass


class BackupNotConfigured(BackupError):
    pass


class BackupInProgress(BackupError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectStorageConfig:
    storage_type: str
    endpoint_url: str | None
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    prefix: str
    force_path_style: bool


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


def get_or_create_backup_settings(session: Session) -> BackupSettings:
    configuration = session.get(BackupSettings, "default")
    if configuration is None:
        configuration = BackupSettings(id="default")
        session.add(configuration)
        session.flush()
    return configuration


def validate_cron_expression(expression: str) -> str:
    normalized = " ".join(expression.split())
    if len(normalized.split()) != 5 or not croniter.is_valid(normalized):
        raise ValueError("请输入有效的 5 段 Cron 表达式")
    return normalized


def next_scheduled_backup_at(expression: str, timezone: str, after: datetime) -> datetime:
    normalized = validate_cron_expression(expression)
    zone = ZoneInfo(timezone)
    base = after.astimezone(zone)
    next_value = croniter(normalized, base).get_next(datetime)
    if not isinstance(next_value, datetime):
        raise ValueError("无法计算下次备份时间")
    if next_value.tzinfo is None:
        next_value = next_value.replace(tzinfo=zone)
    return next_value.astimezone(UTC)


def object_storage_config(
    configuration: BackupSettings,
    application_secret: str,
) -> ObjectStorageConfig:
    if not configuration.bucket or not configuration.access_key_id:
        raise BackupNotConfigured("对象存储配置不完整")
    if not configuration.encrypted_secret_access_key:
        raise BackupNotConfigured("对象存储密钥尚未配置")
    if configuration.storage_type == "r2" and not configuration.endpoint_url:
        raise BackupNotConfigured("Cloudflare R2 Endpoint 尚未配置")
    try:
        secret_access_key = decrypt_secret(
            configuration.encrypted_secret_access_key,
            application_secret,
        )
    except SecretDecryptionError as exc:
        raise BackupNotConfigured("对象存储密钥无法解密") from exc
    return ObjectStorageConfig(
        storage_type=configuration.storage_type,
        endpoint_url=configuration.endpoint_url or None,
        region=configuration.region,
        bucket=configuration.bucket,
        access_key_id=configuration.access_key_id,
        secret_access_key=secret_access_key,
        prefix=configuration.prefix.strip("/"),
        force_path_style=configuration.force_path_style,
    )


def create_object_storage_client(configuration: ObjectStorageConfig) -> Any:
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config as BotocoreConfig  # type: ignore[import-untyped]

    options: dict[str, Any] = {
        "service_name": "s3",
        "region_name": configuration.region,
        "aws_access_key_id": configuration.access_key_id,
        "aws_secret_access_key": configuration.secret_access_key,
        "config": BotocoreConfig(
            s3={
                "addressing_style": "path" if configuration.force_path_style else "auto"
            },
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    }
    if configuration.endpoint_url:
        options["endpoint_url"] = configuration.endpoint_url
    return boto3.client(**options)


def test_object_storage(configuration: ObjectStorageConfig) -> None:
    client = create_object_storage_client(configuration)
    client.head_bucket(Bucket=configuration.bucket)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object_key(configuration: ObjectStorageConfig, path: Path, now: datetime) -> str:
    parts = [
        configuration.prefix,
        now.strftime("%Y"),
        now.strftime("%m"),
        path.name,
    ]
    return "/".join(part.strip("/") for part in parts if part.strip("/"))


def run_remote_backup(
    session: Session,
    *,
    trigger: str,
    settings: Settings | None = None,
) -> BackupRun:
    current = settings or get_settings()
    configuration = get_or_create_backup_settings(session)
    storage = object_storage_config(configuration, current.app_secret_key)
    now = datetime.now(UTC)
    record = BackupRun(
        status="running",
        trigger=trigger,
        active_slot="database-backup",
        file_name="pending.db",
        started_at=now,
        expires_at=(
            now + timedelta(days=configuration.retain_days)
            if configuration.retain_days > 0
            else None
        ),
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise BackupInProgress("已有备份任务正在执行") from exc

    backup_path: Path | None = None
    try:
        backup_path = create_backup(current)
        object_key = _object_key(storage, backup_path, now)
        client = create_object_storage_client(storage)
        client.upload_file(
            str(backup_path),
            storage.bucket,
            object_key,
            ExtraArgs={"ContentType": "application/vnd.sqlite3"},
        )
        record.file_name = backup_path.name
        record.object_key = object_key
        record.size_bytes = backup_path.stat().st_size
        record.checksum_sha256 = _sha256(backup_path)
        record.status = "completed"
        record.finished_at = datetime.now(UTC)
        record.active_slot = None
        session.commit()
        try:
            prune_remote_backups(session, configuration, storage, current)
        except Exception:
            logger.exception("remote backup retention cleanup failed")
        return record
    except Exception as exc:
        logger.exception("remote backup failed")
        session.rollback()
        failed = session.get(BackupRun, record.id)
        if failed is not None:
            failed.file_name = backup_path.name if backup_path else record.file_name
            failed.status = "failed"
            failed.error_message = str(exc)[:1000]
            failed.finished_at = datetime.now(UTC)
            failed.active_slot = None
            session.commit()
        raise BackupError("远程备份失败") from exc


def prune_remote_backups(
    session: Session,
    configuration: BackupSettings,
    storage: ObjectStorageConfig,
    settings: Settings | None = None,
) -> None:
    records = list(
        session.scalars(
            select(BackupRun)
            .where(BackupRun.status == "completed")
            .order_by(BackupRun.finished_at.desc(), BackupRun.started_at.desc())
        )
    )
    now = datetime.now(UTC)
    expired_ids: set[str] = set()
    for index, record in enumerate(records):
        expires_at = record.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at is not None and expires_at <= now:
            expired_ids.add(record.id)
        if configuration.retain_count > 0 and index >= configuration.retain_count:
            expired_ids.add(record.id)
    if not expired_ids:
        return

    client = create_object_storage_client(storage)
    current = settings or get_settings()
    for record in records:
        if record.id not in expired_ids or not record.object_key:
            continue
        try:
            client.delete_object(Bucket=storage.bucket, Key=record.object_key)
        except Exception:
            logger.exception("failed to prune remote backup: %s", record.id)
            continue
        Path(current.backup_dir, record.file_name).unlink(missing_ok=True)
        session.delete(record)
    session.commit()


def presign_backup_download(
    record: BackupRun,
    configuration: BackupSettings,
    settings: Settings | None = None,
    *,
    expires_in_seconds: int = 900,
) -> str:
    if record.status != "completed" or not record.object_key:
        raise BackupError("备份文件尚不可下载")
    current = settings or get_settings()
    storage = object_storage_config(configuration, current.app_secret_key)
    client = create_object_storage_client(storage)
    return str(
        client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": storage.bucket,
                "Key": record.object_key,
                "ResponseContentDisposition": f'attachment; filename="{record.file_name}"',
            },
            ExpiresIn=expires_in_seconds,
        )
    )


def delete_remote_backup(
    session: Session,
    record: BackupRun,
    configuration: BackupSettings,
    settings: Settings | None = None,
) -> None:
    current = settings or get_settings()
    if record.object_key:
        storage = object_storage_config(configuration, current.app_secret_key)
        client = create_object_storage_client(storage)
        client.delete_object(Bucket=storage.bucket, Key=record.object_key)
    Path(current.backup_dir, record.file_name).unlink(missing_ok=True)
    session.delete(record)
    session.commit()

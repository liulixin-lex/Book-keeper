from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.crypto import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.config import Settings, get_settings
from app.db import get_db
from app.dependencies import AuthContext, require_bookkeeper, require_csrf
from app.models import BackupRun, BackupSettings, User
from app.schemas import (
    BackupConnectionTestRead,
    BackupDownloadRead,
    BackupListRead,
    BackupRunRead,
    BackupScheduleRead,
    BackupScheduleWrite,
    BackupStorageRead,
    BackupStorageWrite,
)
from app.services.backup import (
    BackupError,
    BackupInProgress,
    BackupNotConfigured,
    ObjectStorageConfig,
    delete_remote_backup,
    get_or_create_backup_settings,
    next_scheduled_backup_at,
    presign_backup_download,
    run_remote_backup,
    test_object_storage,
    validate_cron_expression,
)

router = APIRouter(prefix="/backups", tags=["backups"])


def _storage_view(configuration: BackupSettings) -> BackupStorageRead:
    return BackupStorageRead(
        storage_type=configuration.storage_type,
        endpoint_url=configuration.endpoint_url,
        region=configuration.region,
        bucket=configuration.bucket,
        access_key_id=configuration.access_key_id,
        prefix=configuration.prefix,
        force_path_style=configuration.force_path_style,
        secret_configured=bool(configuration.encrypted_secret_access_key),
        version=configuration.version,
    )


def _schedule_view(configuration: BackupSettings, settings: Settings) -> BackupScheduleRead:
    next_run_at = None
    if configuration.schedule_enabled:
        try:
            next_run_at = next_scheduled_backup_at(
                configuration.cron_expression,
                settings.timezone,
                datetime.now(UTC),
            )
        except ValueError:
            next_run_at = None
    return BackupScheduleRead(
        enabled=configuration.schedule_enabled,
        cron_expression=configuration.cron_expression,
        retain_days=configuration.retain_days,
        retain_count=configuration.retain_count,
        timezone=settings.timezone,
        next_run_at=next_run_at,
        version=configuration.version,
    )


def _runtime_storage(
    payload: BackupStorageWrite,
    current: BackupSettings,
    settings: Settings,
) -> ObjectStorageConfig:
    if payload.secret_access_key is not None:
        secret_access_key = payload.secret_access_key.get_secret_value()
    elif current.encrypted_secret_access_key:
        try:
            secret_access_key = decrypt_secret(
                current.encrypted_secret_access_key,
                settings.app_secret_key,
            )
        except SecretDecryptionError as exc:
            raise HTTPException(status_code=422, detail="已保存的对象存储密钥无法解密") from exc
    else:
        raise HTTPException(status_code=422, detail="请输入 Secret Access Key")
    return ObjectStorageConfig(
        storage_type=payload.storage_type,
        endpoint_url=payload.endpoint_url or None,
        region=payload.region,
        bucket=payload.bucket,
        access_key_id=payload.access_key_id,
        secret_access_key=secret_access_key,
        prefix=payload.prefix.strip("/"),
        force_path_style=payload.force_path_style,
    )


def _run_or_404(db: Session, run_id: str) -> BackupRun:
    record = db.get(BackupRun, run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    return record


@router.get("/storage", response_model=BackupStorageRead)
def get_storage_configuration(
    _admin: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
) -> BackupStorageRead:
    configuration = get_or_create_backup_settings(db)
    db.commit()
    return _storage_view(configuration)


@router.put("/storage", response_model=BackupStorageRead)
def update_storage_configuration(
    payload: BackupStorageWrite,
    admin: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackupStorageRead:
    configuration = get_or_create_backup_settings(db)
    if payload.secret_access_key is not None:
        configuration.encrypted_secret_access_key = encrypt_secret(
            payload.secret_access_key.get_secret_value(),
            settings.app_secret_key,
        )
    elif configuration.encrypted_secret_access_key is None:
        raise HTTPException(status_code=422, detail="请输入 Secret Access Key")
    configuration.storage_type = payload.storage_type
    configuration.endpoint_url = payload.endpoint_url or None
    configuration.region = payload.region
    configuration.bucket = payload.bucket
    configuration.access_key_id = payload.access_key_id
    configuration.prefix = payload.prefix.strip("/")
    configuration.force_path_style = payload.force_path_style
    configuration.updated_by_id = admin.id
    configuration.version += 1
    db.commit()
    db.refresh(configuration)
    return _storage_view(configuration)


@router.post("/storage/test", response_model=BackupConnectionTestRead)
def test_storage_connection(
    payload: BackupStorageWrite,
    _admin: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackupConnectionTestRead:
    current = get_or_create_backup_settings(db)
    runtime = _runtime_storage(payload, current, settings)
    try:
        test_object_storage(runtime)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="对象存储连接测试失败") from exc
    return BackupConnectionTestRead(ok=True, message="连接成功")


@router.get("/schedule", response_model=BackupScheduleRead)
def get_backup_schedule(
    _admin: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackupScheduleRead:
    configuration = get_or_create_backup_settings(db)
    db.commit()
    return _schedule_view(configuration, settings)


@router.put("/schedule", response_model=BackupScheduleRead)
def update_backup_schedule(
    payload: BackupScheduleWrite,
    admin: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackupScheduleRead:
    try:
        cron_expression = validate_cron_expression(payload.cron_expression)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    configuration = get_or_create_backup_settings(db)
    if payload.enabled and not configuration.encrypted_secret_access_key:
        raise HTTPException(status_code=422, detail="请先完成对象存储配置")
    configuration.schedule_enabled = payload.enabled
    configuration.cron_expression = cron_expression
    configuration.retain_days = payload.retain_days
    configuration.retain_count = payload.retain_count
    configuration.updated_by_id = admin.id
    configuration.version += 1
    db.commit()
    db.refresh(configuration)
    return _schedule_view(configuration, settings)


@router.post("/run", response_model=BackupRunRead, status_code=status.HTTP_201_CREATED)
def create_remote_backup(
    _admin: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackupRunRead:
    try:
        record = run_remote_backup(db, trigger="manual", settings=settings)
    except BackupInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BackupNotConfigured as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BackupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return BackupRunRead.model_validate(record)


@router.get("", response_model=BackupListRead)
def list_backups(
    _admin: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> BackupListRead:
    records = list(
        db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(limit))
    )
    return BackupListRead(items=[BackupRunRead.model_validate(item) for item in records])


@router.get("/{run_id}/download", response_model=BackupDownloadRead)
def get_backup_download(
    run_id: str,
    _admin: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackupDownloadRead:
    record = _run_or_404(db, run_id)
    configuration = get_or_create_backup_settings(db)
    try:
        url = presign_backup_download(record, configuration, settings)
    except BackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="生成下载链接失败") from exc
    return BackupDownloadRead(url=url, expires_in_seconds=900)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(
    run_id: str,
    _admin: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    record = _run_or_404(db, run_id)
    if record.status == "running":
        raise HTTPException(status_code=409, detail="正在执行的备份不能删除")
    configuration = get_or_create_backup_settings(db)
    try:
        delete_remote_backup(db, record, configuration, settings)
    except BackupNotConfigured as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="删除远程备份失败") from exc

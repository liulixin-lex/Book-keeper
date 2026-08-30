from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from app.ai.documents import cleanup_failed_uploads
from app.ai.knowledge import process_next_index_job
from app.config import get_settings
from app.db import SessionLocal, validate_sqlite_runtime
from app.logging_config import configure_logging
from app.models import BackupSettings
from app.services.backup import (
    BackupError,
    create_backup,
    next_scheduled_backup_at,
    run_remote_backup,
)

logger = logging.getLogger("ledger.worker")


def main() -> None:
    configure_logging()
    settings = get_settings()
    settings.ensure_directories()
    validate_sqlite_runtime()
    logger.info("maintenance worker started")
    next_backup_at = 0.0
    next_cleanup_at = 0.0
    schedule_signature: tuple[int, str] | None = None
    next_remote_backup_at: datetime | None = None
    while True:
        now = time.monotonic()
        if now >= next_backup_at:
            try:
                path = create_backup(settings)
                logger.info("online backup completed: %s", path.name)
            except BackupError:
                logger.exception("online backup failed")
            next_backup_at = now + settings.backup_interval_seconds
        with SessionLocal() as session:
            now_utc = datetime.now(UTC)
            backup_settings = session.get(BackupSettings, "default")
            if backup_settings is not None and backup_settings.schedule_enabled:
                current_signature = (
                    backup_settings.version,
                    backup_settings.cron_expression,
                )
                if schedule_signature != current_signature:
                    next_remote_backup_at = next_scheduled_backup_at(
                        backup_settings.cron_expression,
                        settings.timezone,
                        now_utc,
                    )
                    schedule_signature = current_signature
                    logger.info(
                        "remote backup schedule loaded; next run: %s",
                        next_remote_backup_at.isoformat(),
                    )
                if next_remote_backup_at is not None and now_utc >= next_remote_backup_at:
                    try:
                        record = run_remote_backup(
                            session,
                            trigger="scheduled",
                            settings=settings,
                        )
                        logger.info("scheduled remote backup completed: %s", record.file_name)
                    except BackupError:
                        logger.exception("scheduled remote backup failed")
                    next_remote_backup_at = next_scheduled_backup_at(
                        backup_settings.cron_expression,
                        settings.timezone,
                        datetime.now(UTC),
                    )
            else:
                schedule_signature = None
                next_remote_backup_at = None
            for _ in range(25):
                if not process_next_index_job(session, settings):
                    break
            if now >= next_cleanup_at:
                removed = cleanup_failed_uploads(session, settings)
                if removed:
                    logger.info("expired AI uploads removed: %s", removed)
                next_cleanup_at = now + 3600
        time.sleep(settings.knowledge_worker_interval_seconds)


if __name__ == "__main__":
    main()

from __future__ import annotations

import logging
import time

from app.ai.documents import cleanup_failed_uploads
from app.ai.knowledge import process_next_index_job
from app.config import get_settings
from app.db import SessionLocal, validate_sqlite_runtime
from app.logging_config import configure_logging
from app.services.backup import BackupError, create_backup

logger = logging.getLogger("ledger.worker")


def main() -> None:
    configure_logging()
    settings = get_settings()
    settings.ensure_directories()
    validate_sqlite_runtime()
    logger.info("maintenance worker started")
    next_backup_at = 0.0
    next_cleanup_at = 0.0
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

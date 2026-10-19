"""Worker loop: heartbeat, schedules, job execution with retry."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import traceback
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from bookkeeper import __version__
from bookkeeper.db.models import WorkerHeartbeat
from bookkeeper.domain.ids import ulid
from bookkeeper.jobs import queue, registry, tasks

log = logging.getLogger("bookkeeper.worker")


class Worker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        poll_seconds: float = 2.0,
        heartbeat_seconds: float = 30.0,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self.session_factory = session_factory
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.timezone = timezone
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}-{ulid()[-6:]}"
        self.started_at = datetime.now(UTC)
        self._stop = threading.Event()
        self._last_beat = 0.0

    def stop(self, *_: object) -> None:
        self._stop.set()

    def beat(self) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            stmt = insert(WorkerHeartbeat).values(
                worker_id=self.worker_id,
                hostname=socket.gethostname(),
                version=__version__,
                started_at=self.started_at,
                beat_at=now,
            )
            session.execute(stmt.on_conflict_do_update(index_elements=["worker_id"], set_={"beat_at": now}))
        self._last_beat = time.monotonic()

    def install_default_schedules(self) -> None:
        with self.session_factory() as session, session.begin():
            for kind, expression in tasks.DEFAULT_SCHEDULES:
                queue.upsert_schedule(session, kind, expression, timezone=self.timezone)

    def run_once(self) -> str | None:
        """Process at most one job; returns its id."""
        with self.session_factory() as session, session.begin():
            queue.recover_stale(session)
            queue.enqueue_due_schedules(session)
            job = queue.claim(session, self.worker_id)
            if job is None:
                return None
            job_id, kind, payload = job.id, job.kind, dict(job.payload)
        handler = registry.get(kind)
        try:
            if handler is None:
                raise RuntimeError(f"no handler for job kind {kind}")
            if registry.owns_session(kind):  # long tasks: they get the job id to keep it alive (queue.touch)
                result = handler(self.session_factory, payload | {"_job_id": job_id})
            else:
                with self.session_factory() as session, session.begin():
                    result = handler(session, payload)
            with self.session_factory() as session, session.begin():
                queue.finish(session, job_id, result)
            log.info("job succeeded", extra={"job_id": job_id, "kind": kind})
        except Exception as exc:
            log.warning("job failed", extra={"job_id": job_id, "kind": kind, "error": str(exc)})
            with self.session_factory() as session, session.begin():
                queue.fail(session, job_id, "".join(traceback.format_exception_only(exc)).strip())
        return job_id

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.install_default_schedules()
        log.info("worker started", extra={"worker_id": self.worker_id})
        while not self._stop.is_set():
            if time.monotonic() - self._last_beat >= self.heartbeat_seconds:
                self.beat()
            try:
                processed = self.run_once()
            except Exception:
                log.exception("worker loop error")
                processed = None
            if processed is None:
                self._stop.wait(self.poll_seconds)
        log.info("worker stopped", extra={"worker_id": self.worker_id})

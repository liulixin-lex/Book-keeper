import threading
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from bookkeeper.db.models import Book
from bookkeeper.db.roles import grant_app_role
from bookkeeper.domain.scopes import ROLE_CAPS, Role
from bookkeeper.services import audit, idempotency
from bookkeeper.services.context import Actor, RequestContext


def _owner_ctx(world, key: str | None = None) -> RequestContext:
    actor = Actor(type="user", user_id=world.admin_id, role=Role.OWNER, scopes=ROLE_CAPS[Role.OWNER])
    return RequestContext(actor=actor, channel="api", book_id=world.book_id, idempotency_key=key)


def test_concurrent_same_key_writes_once(app, world) -> None:
    factory = app.state.sessionmaker
    req_hash = idempotency.request_hash("PATCH", "/x", {"n": 1})
    results: list[object] = []
    first_claimed = threading.Event()

    def worker(delay: float) -> None:
        time.sleep(delay)
        ctx = _owner_ctx(world, "race-key")
        with factory() as session, session.begin():
            claim = idempotency.begin(session, ctx, "books.update", req_hash, 30)
            if isinstance(claim, idempotency.Replay):
                results.append(("replay", claim.body))
                return
            first_claimed.set()
            book = session.get(Book, world.book_id, with_for_update=True)
            book.version += 1
            time.sleep(0.3)  # hold the claim while the second request arrives
            idempotency.complete(session, claim, 200, {"version": book.version})
            results.append(("fresh", {"version": book.version}))

    threads = [
        threading.Thread(target=worker, args=(0,)),
        threading.Thread(target=worker, args=(0.1,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(kind for kind, _ in results) == ["fresh", "replay"]
    assert results[0][1] == results[1][1] == {"version": 2}
    with factory() as session:
        assert session.get(Book, world.book_id).version == 2


def test_parallel_audit_writes_keep_chain_valid(app, world) -> None:
    factory = app.state.sessionmaker
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        try:
            for i in range(5):
                with factory() as session, session.begin():
                    audit.record(session, _owner_ctx(world), "test.event", "thing", f"{n}-{i}")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with factory() as session:
        result = audit.verify_chain(session, world.book_id)
    assert result.ok
    assert result.events >= 40


def test_app_role_cannot_rewrite_history(database_url, app, world) -> None:
    admin = create_engine(database_url)
    with admin.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='bk_app') "
                "THEN CREATE ROLE bk_app LOGIN; END IF; END $$"
            )
        )
        assert grant_app_role(conn)
    admin.dispose()
    app_url = database_url.replace("postgresql+psycopg://postgres@", "postgresql+psycopg://bk_app@")
    engine = create_engine(app_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar() > 0
        for statement in (
            "DELETE FROM audit_events",
            "TRUNCATE audit_events",
            "DELETE FROM commodities WHERE code = 'UCR'",  # currencies are added in the app but never deleted
        ):
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text(statement))
            conn.rollback()
    engine.dispose()

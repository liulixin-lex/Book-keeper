import io

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bookkeeper.jobs import queue
from bookkeeper.jobs.worker import Worker
from tests.api.conftest import bearer, create_token, login, write_headers


def test_audit_chain_records_and_verifies(client, world) -> None:
    csrf = login(client, world.admin_email)
    client.patch(
        f"/api/v1/books/{world.book_id}",
        json={"expected_version": 1, "name": "改名"},
        headers=write_headers(csrf),
    )
    events = client.get(f"/api/v1/books/{world.book_id}/audit-events").json()
    actions = [e["action"] for e in events["data"]]
    assert actions[0] == "book.update"
    assert "book.create" in actions
    update = events["data"][0]
    assert update["diff"] == {"name": ["测试账套", "改名"], "version": [1, 2]}
    assert update["channel"] == "ui"
    verify = client.get(f"/api/v1/books/{world.book_id}/audit-events/verify").json()["data"]
    assert verify["ok"]
    assert verify["events"] == len(actions)
    change_set = client.get(f"/api/v1/books/{world.book_id}/change-sets/{update['change_set_id']}").json()["data"]
    assert change_set["operation"] == "book.update"
    assert [e["action"] for e in change_set["events"]] == ["book.update"]


def test_audit_events_are_append_only(app, world) -> None:
    with app.state.engine.connect() as conn:
        with pytest.raises(DBAPIError, match="append-only"):
            conn.execute(text("UPDATE audit_events SET action = 'x'"))
        conn.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            conn.execute(text("DELETE FROM audit_events"))
        conn.rollback()


def test_tampering_breaks_chain(app, world) -> None:
    from bookkeeper.services import audit

    with app.state.engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_immutable"))
        conn.execute(
            text("UPDATE audit_events SET action = 'book.forged' WHERE seq = 1 AND scope = :s"),
            {"s": world.book_id},
        )
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_immutable"))
    with app.state.sessionmaker() as session:
        result = audit.verify_chain(session, world.book_id)
    assert not result.ok
    assert result.first_bad_seq == 1
    assert result.reason == "hash mismatch"


def test_file_upload_dedup_and_download(client, world) -> None:
    csrf = login(client, world.admin_email)
    url = f"/api/v1/books/{world.book_id}/files"
    files = {"file": ("账单.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    first = client.post(url, files=files, headers=write_headers(csrf))
    assert first.status_code == 201, first.text
    files = {"file": ("copy.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    second = client.post(url, files=files, headers=write_headers(csrf))
    assert second.json()["data"]["id"] == first.json()["data"]["id"]
    assert second.json()["data"]["created"] is False
    file_id = first.json()["data"]["id"]
    download = client.get(f"{url}/{file_id}/content")
    assert download.status_code == 200
    assert download.content == b"a,b\n1,2\n"
    assert "filename*=UTF-8''%E8%B4%A6%E5%8D%95.csv" in download.headers["content-disposition"]


def test_file_rules(client, world) -> None:
    csrf = login(client, world.admin_email)
    url = f"/api/v1/books/{world.book_id}/files"
    bad = client.post(
        url,
        files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/x-msdownload")},
        headers=write_headers(csrf),
    )
    assert bad.status_code == 415
    reader = create_token(client, world.book_id, csrf)["token"]
    good = client.post(
        url,
        files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")},
        headers=write_headers(csrf),
    ).json()["data"]
    client.cookies.clear()
    own = client.get(f"{url}/{good['id']}/content", headers=bearer(reader))  # user_read reads its user's uploads
    assert own.status_code == 200 and own.content == b"hello"
    assert client.get(f"{url}/{good['id']}", headers=bearer(reader)).status_code == 200


def test_worker_runs_jobs_with_retry(app, world) -> None:
    factory = app.state.sessionmaker
    with factory() as session, session.begin():
        ok = queue.enqueue(session, "system.noop", {"echo": 7}, book_id=world.book_id)
        bad = queue.enqueue(session, "system.noop", {"fail": "boom"}, book_id=world.book_id, max_attempts=2)
        ok_id, bad_id = ok.id, bad.id
    worker = Worker(factory)
    assert worker.run_once() is not None
    assert worker.run_once() is not None
    with factory() as session:
        from bookkeeper.db.models import Job

        done = session.get(Job, ok_id)
        failed = session.get(Job, bad_id)
        assert done.status == "succeeded"
        assert done.result == {"echo": 7}
        assert failed.status == "queued"
        assert failed.attempts == 1
        assert "boom" in failed.last_error
        failed_run_after = failed.run_after
    with factory() as session, session.begin():
        session.get(Job, bad_id).run_after = failed_run_after.replace(year=2000)
    worker.run_once()
    with factory() as session:
        assert session.get(Job, bad_id).status == "failed"


def test_default_schedules_install_once(app) -> None:
    from sqlalchemy import func, select

    from bookkeeper.db.models import JobSchedule

    worker = Worker(app.state.sessionmaker)
    worker.install_default_schedules()
    worker.install_default_schedules()
    with app.state.sessionmaker() as session:
        from bookkeeper.jobs.tasks import DEFAULT_SCHEDULES

        assert session.execute(select(func.count()).select_from(JobSchedule)).scalar_one() == len(DEFAULT_SCHEDULES)


def test_job_status_endpoint(client, world, app) -> None:
    with app.state.sessionmaker() as session, session.begin():
        job_id = queue.enqueue(session, "system.noop", {}, book_id=world.book_id).id
    login(client, world.admin_email)
    body = client.get(f"/api/v1/books/{world.book_id}/jobs/{job_id}").json()["data"]
    assert body["status"] == "queued"


def test_meta_enums_and_capabilities(client, world) -> None:
    login(client, world.admin_email)
    enums = client.get("/api/v1/meta/enums").json()["data"]
    assert enums["transaction_status"] == {"posted": "已入账", "reversed": "已删除"}
    caps = client.get("/api/v1/meta/capabilities").json()["data"]
    assert caps["auth_method"] == "session"

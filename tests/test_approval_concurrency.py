from __future__ import annotations

from threading import Event, Thread
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from app.api import approvals as approvals_api
from app.api.approvals import ApprovalDecision
from app.enums import ApprovalStatus, UserRole
from app.models import ApprovalRequest, User, Workspace


def test_approve_and_reject_cannot_both_win(
    db_session: Session, workspace: Workspace, monkeypatch: Any
) -> None:
    admin = User(
        workspace_id=workspace.id,
        username="Admin",
        email="approval-admin@example.com",
        display_name="Admin",
        password_hash="unused",
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    db_session.flush()
    approval = ApprovalRequest(
        workspace_id=workspace.id,
        kind="test.concurrent",
        status=ApprovalStatus.PENDING,
        payload_json={},
        requested_by_user_id=admin.id,
    )
    db_session.add(approval)
    db_session.commit()

    entered = Event()
    release = Event()

    def held_action(*_args: Any, **_kwargs: Any) -> dict[str, bool]:
        entered.set()
        assert release.wait(timeout=5)
        return {"ok": True}

    monkeypatch.setattr(approvals_api, "_execute_approved_action", held_action)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    outcomes: list[str] = []

    def approve() -> None:
        with factory() as session:
            current_admin = session.get(User, admin.id)
            assert current_admin is not None
            approvals_api.approve_request(
                approval.id,
                ApprovalDecision(reason="approve"),
                current_admin,
                None,  # type: ignore[arg-type]
                session,
            )
            outcomes.append("approved")

    def reject() -> None:
        with factory() as session:
            current_admin = session.get(User, admin.id)
            assert current_admin is not None
            try:
                approvals_api.reject_request(
                    approval.id,
                    ApprovalDecision(reason="reject"),
                    current_admin,
                    None,  # type: ignore[arg-type]
                    session,
                )
                outcomes.append("rejected")
            except HTTPException as exc:
                assert exc.status_code == 409
                outcomes.append("conflict")

    approve_thread = Thread(target=approve)
    reject_thread = Thread(target=reject)
    approve_thread.start()
    assert entered.wait(timeout=5)
    reject_thread.start()
    release.set()
    approve_thread.join(timeout=10)
    reject_thread.join(timeout=10)
    assert not approve_thread.is_alive()
    assert not reject_thread.is_alive()
    assert sorted(outcomes) == ["approved", "conflict"]

    db_session.expire_all()
    stored = db_session.get(ApprovalRequest, approval.id)
    assert stored is not None
    assert stored.status == ApprovalStatus.APPROVED

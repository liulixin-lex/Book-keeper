from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api import reports as reports_api
from app.enums import UserRole
from app.models import User, Workspace
from app.services.fx import FxProviderError


def _user(db_session: Session, workspace: Workspace) -> User:
    user = User(
        workspace_id=workspace.id,
        username="report-api-viewer",
        email="report-api-viewer@example.com",
        display_name="report-api-viewer",
        password_hash="unused",
        role=UserRole.VIEWER,
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_dashboard_rejects_unsupported_display_currency(
    db_session: Session, workspace: Workspace
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        reports_api.get_dashboard_report(
            date(2026, 8, 29),
            date(2026, 8, 29),
            _user(db_session, workspace),
            db_session,
            "BTC",
        )

    assert exc_info.value.status_code == 422
    assert "暂不支持币种 BTC" in str(exc_info.value.detail)


def test_dashboard_returns_502_when_rate_and_cache_are_unavailable(
    db_session: Session, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_rate(*_args: object, **_kwargs: object) -> None:
        raise FxProviderError("Frankfurter unavailable")

    monkeypatch.setattr(reports_api, "resolve_display_rate", fail_rate)

    with pytest.raises(HTTPException) as exc_info:
        reports_api.get_dashboard_report(
            date(2026, 8, 29),
            date(2026, 8, 29),
            _user(db_session, workspace),
            db_session,
            "USD",
        )

    assert exc_info.value.status_code == 502
    assert "汇率服务不可用" in str(exc_info.value.detail)

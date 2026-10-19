import pytest

from bookkeeper.config import Settings


def test_production_guard() -> None:
    safe = {"database_url": "postgresql+psycopg://bk_app:9f8e@db/bookkeeper", "public_url": "https://ledger.example"}
    Settings(environment="production", **safe).ensure_deployable()
    Settings(database_url="postgresql+psycopg://bk_app:change-me-app@db/x").ensure_deployable()  # development
    unsafe = Settings(
        environment="production",
        database_url="postgresql+psycopg://bk_app:change-me-app@db/bookkeeper",
        public_url="http://ledger.example",
    )
    assert len(unsafe.production_problems()) == 2
    with pytest.raises(RuntimeError, match="BK_DATABASE_URL"):
        unsafe.ensure_deployable()

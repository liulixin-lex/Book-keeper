from app.main import app


def test_openapi_contains_public_backend_surface() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        "/api/v1/auth/bootstrap",
        "/api/v1/records/income",
        "/api/v1/records/expenses",
        "/api/v1/ai/providers/{provider_id}/run",
        "/api/v1/ai/settings",
        "/api/v1/approvals/{approval_id}/approve",
        "/api/v1/reports/daily",
        "/api/v1/reports/overview",
        "/api/v1/catalog/providers",
        "/api/v1/audit",
    }
    assert expected <= set(paths)
    assert not any(path.startswith("/api/v1/imports") for path in paths)
    assert not any(path.startswith("/api/v1/rules") for path in paths)
    assert not any(path.startswith("/api/v1/settlements") for path in paths)
    assert not any(path.startswith("/api/v1/reconciliations") for path in paths)
    assert "/api/v1/catalog/payment-accounts" not in paths
    assert "/api/v1/records/topups" not in paths
    assert "/api/v1/records/refunds" not in paths
    assert not any(path.startswith("/api/v1/catalog/projects") for path in paths)
    assert not any(path.startswith("/api/v1/catalog/tags") for path in paths)
    assert not any(path.startswith("/api/v1/catalog/counterparties") for path in paths)
    assert "tool_scope" not in schema["components"]["schemas"]["AiRequest"]["properties"]
    for model_name in (
        "IncomeCreate",
        "ExpenseCreate",
        "DraftRecordUpdate",
        "SubscriptionCharge",
    ):
        assert "payment_account_id" not in schema["components"]["schemas"][model_name]["properties"]
        assert "project_id" not in schema["components"]["schemas"][model_name]["properties"]
        assert "tag_ids" not in schema["components"]["schemas"][model_name]["properties"]
    assert (
        "pending_adjustments" not in schema["components"]["schemas"]["OverviewRead"]["properties"]
    )
    assert (
        "pending_adjustments" not in schema["components"]["schemas"]["DailyReportRow"]["properties"]
    )
    assert schema["components"]["schemas"]["RecordRead"]["properties"]["record_type"]["enum"] == [
        "income",
        "expense",
    ]
    provider_fields = schema["components"]["schemas"]["ProviderCreate"]["properties"]
    assert "expense_category_id" in provider_fields
    assert "roles" not in provider_fields
    assert "metadata" not in provider_fields

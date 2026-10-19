from tests.api.conftest import login


def test_missing_key_rejected(client, world) -> None:
    csrf = login(client, world.admin_email)
    response = client.post(f"/api/v1/books/{world.book_id}/tokens", json={"name": "x"}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_replay_returns_same_response(client, world) -> None:
    csrf = login(client, world.admin_email)
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "same-key"}
    url = f"/api/v1/books/{world.book_id}"
    first = client.patch(url, json={"expected_version": 1, "name": "A"}, headers=headers)
    second = client.patch(url, json={"expected_version": 1, "name": "A"}, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.headers.get("idempotent-replayed") == "true"
    assert first.json() == second.json()
    assert client.get(url).json()["data"]["version"] == 2


def test_same_key_different_body_conflicts(client, world) -> None:
    csrf = login(client, world.admin_email)
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "k-x"}
    url = f"/api/v1/books/{world.book_id}"
    client.patch(url, json={"expected_version": 1, "name": "A"}, headers=headers)
    response = client.patch(url, json={"expected_version": 1, "name": "B"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_MISMATCH"


def test_token_replay_withholds_secret(client, world) -> None:
    csrf = login(client, world.admin_email)
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "tok-key"}
    first = client.post(f"/api/v1/books/{world.book_id}/tokens", json={"name": "x"}, headers=headers)
    second = client.post(f"/api/v1/books/{world.book_id}/tokens", json={"name": "x"}, headers=headers)
    assert first.json()["data"]["token"].startswith("bk_pat_")
    assert second.json()["data"]["token"] is None
    assert second.json()["meta"]["secret_fields_withheld"] == ["token"]
    assert second.json()["data"]["id"] == first.json()["data"]["id"]


def test_dry_run_writes_nothing(client, world) -> None:
    csrf = login(client, world.admin_email)
    url = f"/api/v1/books/{world.book_id}"
    preview = client.patch(
        url + "?dry_run=true",
        json={"expected_version": 1, "name": "预演"},
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["name"] == "预演"
    assert preview.json()["meta"]["dry_run"] is True
    assert client.get(url).json()["data"]["name"] == "测试账套"

def test_healthz(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-request-id"].startswith("req_")


def test_readyz_reports_checks(client) -> None:
    body = client.get("/readyz").json()
    assert body["checks"]["database"]["ok"]
    assert body["checks"]["migrations"]["ok"]
    assert body["checks"]["triggers"]["ok"]
    assert body["status"] == "ready"


def test_unknown_route_is_problem_json(client) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "NOT_FOUND"

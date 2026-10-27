"""App-level wiring: OpenAPI metadata, docs and lifespan."""
from fastapi.testclient import TestClient
from fastapi_limiter import FastAPILimiter

import main


def test_openapi_schema_served_at_versioned_url(client):
    response = client.get("/api/v1/schema.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "WhatsMyName-Docker"
    assert schema["info"]["version"] == main.app.version
    assert [tag["name"] for tag in schema["tags"]] == ["auth", "lookups", "results"]


def test_default_openapi_url_is_disabled(client):
    assert client.get("/openapi.json").status_code == 404


def test_schema_lists_all_routes(client):
    paths = client.get("/api/v1/schema.json").json()["paths"]

    assert set(paths) == {
        "/api/v1/token",
        "/api/v1/lookup",
        "/api/v1/batch",
        "/api/v1/status/{job_id}",
    }
    assert "post" in paths["/api/v1/token"]
    assert "post" in paths["/api/v1/lookup"]
    assert "post" in paths["/api/v1/batch"]
    assert "get" in paths["/api/v1/status/{job_id}"]


def test_docs_page_available(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "/api/v1/schema.json" in response.text


def test_unknown_route_is_404(client):
    assert client.get("/api/v1/nope").status_code == 404


def test_wrong_method_is_405(client):
    assert client.get("/api/v1/lookup").status_code == 405
    assert client.post("/api/v1/status/11111111-2222-3333-4444-555555555555").status_code == 405


def test_lifespan_initialises_rate_limiter(fake_redis, fake_celery):
    with TestClient(main.app):
        assert FastAPILimiter.redis is fake_redis
        assert FastAPILimiter.lua_sha

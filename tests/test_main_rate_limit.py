"""Rate limiting on the lookup and status routes."""
import pytest

from utils.config import RATE_LIMIT

JOB_ID = "11111111-2222-3333-4444-555555555555"


def exhaust(client, method, path, **kwargs):
    for _ in range(RATE_LIMIT):
        assert getattr(client, method)(path, **kwargs).status_code == 200


def test_default_limit_is_twenty_per_minute():
    assert RATE_LIMIT == 20


@pytest.mark.parametrize("method, path, kwargs", [
    ("post", "/api/v1/lookup", {"json": {"username": "kodama"}}),
    ("post", "/api/v1/batch", {"json": {"usernames": ["kodama"]}}),
    ("get", f"/api/v1/status/{JOB_ID}", {}),
], ids=["lookup", "batch", "status"])
def test_request_over_limit_is_429(client, method, path, kwargs):
    exhaust(client, method, path, **kwargs)

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 429
    assert response.json() == {"detail": "Too Many Requests"}
    assert 0 < int(response.headers["Retry-After"]) <= 60


def test_rejected_requests_do_not_submit_jobs(client, fake_celery):
    exhaust(client, "post", "/api/v1/batch", json={"usernames": ["a", "b"]})
    calls_before = fake_celery.delay.call_count

    assert client.post("/api/v1/batch", json={"usernames": ["c"]}).status_code == 429
    assert fake_celery.delay.call_count == calls_before


def test_limits_are_tracked_per_route(client):
    exhaust(client, "post", "/api/v1/lookup", json={"username": "kodama"})

    assert client.post("/api/v1/batch", json={"usernames": ["kodama"]}).status_code == 200


def test_status_limit_is_per_job_id(client):
    # The limiter key includes the full request path, which includes the job ID
    exhaust(client, "get", f"/api/v1/status/{JOB_ID}")

    other = "22222222-2222-3333-4444-555555555555"
    assert client.get(f"/api/v1/status/{other}").status_code == 200


def test_limits_are_tracked_per_client_ip(client):
    exhaust(client, "post", "/api/v1/lookup", json={"username": "kodama"},
            headers={"X-Forwarded-For": "10.0.0.1"})

    response = client.post("/api/v1/lookup", json={"username": "kodama"},
                           headers={"X-Forwarded-For": "10.0.0.2"})
    assert response.status_code == 200


def test_invalid_requests_still_count_toward_limit(client):
    for _ in range(RATE_LIMIT):
        assert client.post("/api/v1/lookup", json={"username": "bad name"}).status_code == 400

    assert client.post("/api/v1/lookup", json={"username": "kodama"}).status_code == 429


def test_token_endpoint_is_not_rate_limited(client, user_db):
    for _ in range(RATE_LIMIT + 5):
        response = client.post("/api/v1/token", json={"user_id": "x", "secret": "y"})
        assert response.status_code == 401

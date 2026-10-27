"""Tests for POST /api/v1/lookup."""
from unittest.mock import AsyncMock

import pytest

import main
from utils.config import CACHE_EXPIRATION

LOOKUP_URL = "/api/v1/lookup"
CACHED_JOB_ID = "11111111-2222-3333-4444-555555555555"


async def test_new_username_creates_job_and_caches_it(client, fake_redis, fake_celery):
    response = client.post(LOOKUP_URL, json={"username": "kodama"})

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    fake_celery.delay.assert_called_once_with("kodama")
    assert job_id in fake_celery.jobs
    assert await fake_redis.get("kodama") == job_id.encode()
    ttl = await fake_redis.ttl("kodama")
    assert 0 < ttl <= CACHE_EXPIRATION


def test_response_contains_only_job_id(client):
    response = client.post(LOOKUP_URL, json={"username": "kodama"})
    assert set(response.json()) == {"job_id"}


@pytest.mark.parametrize("username", [
    "a",
    "john.doe",
    "John_Doe-99",
    "a_b-c+d%20",
    "x:y/z?q=1&r#s",
    "user@example.com".replace("@", "%40"),
    "0" * 256,
])
def test_valid_username_characters_are_accepted(client, fake_celery, username):
    response = client.post(LOOKUP_URL, json={"username": username})

    assert response.status_code == 200
    fake_celery.delay.assert_called_once_with(username)


@pytest.mark.parametrize("username", [
    "",
    " ",
    "john doe",
    "<script>",
    "名前",
    "émile",
    "user\nname",
    "\nleading",
    "a;b",
    "a@b",
    "a!b",
    "a*b",
    "a\"b",
    "a'b",
    "{account}",
])
def test_invalid_username_characters_are_rejected(client, fake_celery, username):
    response = client.post(LOOKUP_URL, json={"username": username})

    assert response.status_code == 400
    assert response.json() == {"detail": "Username must contain only valid URL characters."}
    fake_celery.delay.assert_not_called()


@pytest.mark.parametrize("body", [
    {},
    {"user": "kodama"},
    {"username": None},
    {"username": 123},
    {"username": ["a", "b"]},
])
def test_malformed_body_is_422(client, fake_celery, body):
    assert client.post(LOOKUP_URL, json=body).status_code == 422
    fake_celery.delay.assert_not_called()


@pytest.mark.xfail(strict=True, reason=(
    "BUG: the username regex uses re.match with '$', which also matches before a trailing "
    "newline, so 'name\\n' passes validation (use re.fullmatch or \\Z)."
))
def test_trailing_newline_is_rejected(client, fake_celery):
    response = client.post(LOOKUP_URL, json={"username": "kodama\n"})

    assert response.status_code == 400
    fake_celery.delay.assert_not_called()


# Cache behaviour

@pytest.mark.parametrize("state, result", [
    ("PENDING", None),
    ("SUCCESS", {"websites": [], "stats": {"websites_checked": 1}}),
])
async def test_reusable_cached_job_is_returned(client, fake_redis, fake_celery, state, result):
    await fake_redis.set("kodama", CACHED_JOB_ID)
    fake_celery.set(CACHED_JOB_ID, state, result)

    response = client.post(LOOKUP_URL, json={"username": "kodama"})

    assert response.status_code == 200
    assert response.json() == {"job_id": CACHED_JOB_ID}
    fake_celery.delay.assert_not_called()


@pytest.mark.parametrize("state, result, info", [
    ("SUCCESS", {"error": "Task timeout", "message": "took too long"}, None),
    ("SUCCESS", None, None),
    ("SUCCESS", [], None),
    ("SUCCESS", {}, None),
    ("FAILURE", None, RuntimeError("boom")),
    ("REVOKED", None, None),
    ("STARTED", None, None),
    ("RETRY", None, None),
])
async def test_stale_cached_job_is_replaced(client, fake_redis, fake_celery, state, result, info):
    await fake_redis.set("kodama", CACHED_JOB_ID)
    fake_celery.set(CACHED_JOB_ID, state, result, info)

    response = client.post(LOOKUP_URL, json={"username": "kodama"})

    assert response.status_code == 200
    new_job_id = response.json()["job_id"]
    assert new_job_id != CACHED_JOB_ID
    fake_celery.delay.assert_called_once_with("kodama")
    assert await fake_redis.get("kodama") == new_job_id.encode()


async def test_cache_is_per_username(client, fake_redis, fake_celery):
    await fake_redis.set("other", CACHED_JOB_ID)

    response = client.post(LOOKUP_URL, json={"username": "kodama"})

    assert response.json()["job_id"] != CACHED_JOB_ID
    fake_celery.delay.assert_called_once_with("kodama")


async def test_cache_is_case_sensitive(client, fake_redis, fake_celery):
    await fake_redis.set("Kodama", CACHED_JOB_ID)

    response = client.post(LOOKUP_URL, json={"username": "kodama"})

    assert response.json()["job_id"] != CACHED_JOB_ID


def test_repeat_lookup_reuses_pending_job(client, fake_celery):
    first = client.post(LOOKUP_URL, json={"username": "kodama"}).json()["job_id"]
    second = client.post(LOOKUP_URL, json={"username": "kodama"}).json()["job_id"]

    assert first == second
    assert fake_celery.delay.call_count == 1


# Failure handling

def test_celery_submission_failure_is_generic_500(client, fake_celery):
    fake_celery.delay.side_effect = ConnectionError("broker unreachable at secret-host:6379")

    response = client.post(LOOKUP_URL, json={"username": "kodama"})

    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred."}
    assert "secret-host" not in response.text


@pytest.mark.parametrize("method", ["get", "setex"])
def test_redis_failure_is_generic_500(client, fake_redis, monkeypatch, method):
    monkeypatch.setattr(fake_redis, method, AsyncMock(side_effect=ConnectionError("redis down")))

    response = client.post(LOOKUP_URL, json={"username": "kodama"})

    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred."}


def test_result_backend_failure_is_generic_500(client, fake_redis, fake_celery, monkeypatch):
    client.post(LOOKUP_URL, json={"username": "kodama"})
    monkeypatch.setattr(main, "AsyncResult", lambda _: (_ for _ in ()).throw(OSError("backend")))

    response = client.post(LOOKUP_URL, json={"username": "kodama"})

    assert response.status_code == 500

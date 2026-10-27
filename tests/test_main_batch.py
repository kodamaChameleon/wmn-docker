"""Tests for POST /api/v1/batch."""
import json
from unittest.mock import AsyncMock, call
from uuid import UUID

import pytest

from utils.config import CACHE_EXPIRATION

BATCH_URL = "/api/v1/batch"
CACHED_JOB_ID = "11111111-2222-3333-4444-555555555555"


def test_all_new_usernames_get_new_jobs(client, fake_celery):
    response = client.post(BATCH_URL, json={"usernames": ["alice", "bob", "carol"]})

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert list(jobs) == ["alice", "bob", "carol"]
    for info in jobs.values():
        assert info["status"] == "new"
        assert info["job_id"] in fake_celery.jobs
    assert len({info["job_id"] for info in jobs.values()}) == 3
    fake_celery.delay.assert_has_calls([call("alice"), call("bob"), call("carol")])


def test_master_job_id_is_uuid4(client):
    response = client.post(BATCH_URL, json={"usernames": ["alice"]})

    master_job_id = response.json()["master_job_id"]
    assert UUID(master_job_id).version == 4


def test_each_batch_gets_a_distinct_master_job_id(client):
    first = client.post(BATCH_URL, json={"usernames": ["alice"]}).json()["master_job_id"]
    second = client.post(BATCH_URL, json={"usernames": ["alice"]}).json()["master_job_id"]

    assert first != second


async def test_master_job_is_stored_in_redis(client, fake_redis):
    body = client.post(BATCH_URL, json={"usernames": ["alice", "bad name"]}).json()

    stored = await fake_redis.get(body["master_job_id"])
    assert json.loads(stored) == body["jobs"]
    ttl = await fake_redis.ttl(body["master_job_id"])
    assert 0 < ttl <= CACHE_EXPIRATION


async def test_new_jobs_are_cached_per_username(client, fake_redis):
    jobs = client.post(BATCH_URL, json={"usernames": ["alice", "bob"]}).json()["jobs"]

    for username, info in jobs.items():
        assert await fake_redis.get(username) == info["job_id"].encode()
        assert 0 < await fake_redis.ttl(username) <= CACHE_EXPIRATION


def test_invalid_usernames_get_error_entries(client, fake_celery):
    response = client.post(BATCH_URL, json={"usernames": ["good", "bad name", "<x>"]})

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert jobs["good"]["status"] == "new"
    assert jobs["bad name"] == {"status": "error", "detail": "Invalid username format"}
    assert jobs["<x>"] == {"status": "error", "detail": "Invalid username format"}
    fake_celery.delay.assert_called_once_with("good")


async def test_cached_username_is_reused_and_decoded(client, fake_redis, fake_celery):
    await fake_redis.set("alice", CACHED_JOB_ID)

    jobs = client.post(BATCH_URL, json={"usernames": ["alice", "bob"]}).json()["jobs"]

    assert jobs["alice"] == {"job_id": CACHED_JOB_ID, "status": "cached"}
    assert jobs["bob"]["status"] == "new"
    fake_celery.delay.assert_called_once_with("bob")


def test_batch_reuses_job_from_single_lookup(client, fake_celery):
    single_job = client.post("/api/v1/lookup", json={"username": "alice"}).json()["job_id"]

    jobs = client.post(BATCH_URL, json={"usernames": ["alice"]}).json()["jobs"]

    assert jobs["alice"] == {"job_id": single_job, "status": "cached"}


def test_duplicate_usernames_collapse_to_one_job(client, fake_celery):
    response = client.post(BATCH_URL, json={"usernames": ["alice", "alice"]})

    # The second occurrence hits the cache written by the first, and both share a dict key
    assert response.json()["jobs"]["alice"]["status"] == "cached"
    assert fake_celery.delay.call_count == 1


@pytest.mark.xfail(strict=True, reason=(
    "BUG: the username regex uses re.match with '$', so a trailing newline passes validation."
))
def test_trailing_newline_is_rejected(client, fake_celery):
    jobs = client.post(BATCH_URL, json={"usernames": ["kodama\n"]}).json()["jobs"]

    assert jobs["kodama\n"]["status"] == "error"
    fake_celery.delay.assert_not_called()


def test_empty_batch_returns_no_jobs(client, fake_celery):
    response = client.post(BATCH_URL, json={"usernames": []})

    assert response.status_code == 200
    assert response.json()["jobs"] == {}
    fake_celery.delay.assert_not_called()


@pytest.mark.parametrize("body", [
    {},
    {"usernames": "alice"},
    {"usernames": None},
    {"usernames": [1, 2]},
    {"usernames": [["nested"]]},
    {"username": ["alice"]},
])
def test_malformed_body_is_422(client, fake_celery, body):
    assert client.post(BATCH_URL, json=body).status_code == 422
    fake_celery.delay.assert_not_called()


@pytest.mark.parametrize("method", ["get", "setex"])
def test_redis_failure_is_generic_500(client, fake_redis, monkeypatch, method):
    monkeypatch.setattr(fake_redis, method, AsyncMock(side_effect=ConnectionError("redis down")))

    response = client.post(BATCH_URL, json={"usernames": ["alice"]})

    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred during batch submission."}


def test_celery_failure_is_generic_500(client, fake_celery):
    fake_celery.delay.side_effect = ConnectionError("broker down")

    response = client.post(BATCH_URL, json={"usernames": ["alice"]})

    assert response.status_code == 500


@pytest.mark.xfail(strict=True, reason=(
    "BUG: /batch reuses any cached job_id without checking its state, so a FAILED or "
    "errored lookup is served from cache until expiry; /lookup resubmits in that case."
))
async def test_failed_cached_job_is_resubmitted(client, fake_redis, fake_celery):
    await fake_redis.set("alice", CACHED_JOB_ID)
    fake_celery.set(CACHED_JOB_ID, "FAILURE", info=RuntimeError("boom"))

    jobs = client.post(BATCH_URL, json={"usernames": ["alice"]}).json()["jobs"]

    assert jobs["alice"]["job_id"] != CACHED_JOB_ID
    fake_celery.delay.assert_called_once_with("alice")

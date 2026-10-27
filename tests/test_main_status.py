"""Tests for GET /api/v1/status/{job_id}."""
import json
from unittest.mock import AsyncMock

import pytest

STATUS_URL = "/api/v1/status/{}"
JOB_ID = "11111111-2222-3333-4444-555555555555"
RESULT = {
    "websites": [["GitHub", "https://github.com/kodama"]],
    "stats": {"websites_checked": 700, "profiles_found": 1, "errors": 0},
}


def get_status(client, job_id):
    return client.get(STATUS_URL.format(job_id))


# job_id validation

@pytest.mark.parametrize("job_id", [
    "abc",
    "11111111222233334444555555555555",
    "1111111-2222-3333-4444-555555555555",
    "11111111-2222-3333-4444-5555555555555",
    "11111111-2222-3333-4444-555555555555x",
    "x11111111-2222-3333-4444-555555555555",
    "gggggggg-2222-3333-4444-555555555555",
    "11111111_2222_3333_4444_555555555555",
    "11111111-2222-3333-4444-55555555555%20",
])
def test_invalid_job_id_is_400(client, fake_celery, job_id):
    response = get_status(client, job_id)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid job_id format. Must be a valid UUID."}


def test_uppercase_uuid_is_accepted(client):
    response = get_status(client, JOB_ID.replace("1", "A"))
    assert response.status_code == 200


def test_missing_job_id_is_404(client):
    assert client.get("/api/v1/status/").status_code == 404


@pytest.mark.xfail(strict=True, reason=(
    "BUG: the job_id regex uses re.match with '$', so a trailing newline passes validation."
))
def test_job_id_with_trailing_newline_is_400(client):
    assert get_status(client, JOB_ID + "%0A").status_code == 400


# Single jobs

def test_single_pending(client, fake_celery):
    fake_celery.set(JOB_ID, "PENDING")

    assert get_status(client, JOB_ID).json() == {
        "job_id": JOB_ID, "status": "pending", "type": "single",
    }


def test_unknown_job_reports_pending(client):
    # Celery reports PENDING for IDs it has never seen
    assert get_status(client, JOB_ID).json()["status"] == "pending"


def test_single_success(client, fake_celery):
    fake_celery.set(JOB_ID, "SUCCESS", RESULT)

    assert get_status(client, JOB_ID).json() == {
        "job_id": JOB_ID, "status": "complete", "results": RESULT, "type": "single",
    }


def test_single_success_with_task_error(client, fake_celery):
    fake_celery.set(JOB_ID, "SUCCESS", {"error": "Task timeout", "message": "too long"})

    assert get_status(client, JOB_ID).json() == {
        "job_id": JOB_ID, "status": "failed", "error": "Task timeout", "type": "single",
    }


def test_single_failure(client, fake_celery):
    fake_celery.set(JOB_ID, "FAILURE", info=RuntimeError("worker exploded"))

    assert get_status(client, JOB_ID).json() == {
        "job_id": JOB_ID, "status": "failed", "error": "worker exploded", "type": "single",
    }


@pytest.mark.parametrize("state", ["STARTED", "RETRY", "REVOKED", "RECEIVED"])
def test_single_other_states_are_unknown(client, fake_celery, state):
    fake_celery.set(JOB_ID, state)

    assert get_status(client, JOB_ID).json() == {
        "job_id": JOB_ID, "status": "unknown", "state": state, "type": "single",
    }


@pytest.mark.xfail(strict=True, reason=(
    "BUG: a SUCCESS task whose result is None (tasks.check_username on an exception) or [] "
    "(username_lookup when the WMN fetch fails) hits `.get` on a non-dict and returns 500."
))
@pytest.mark.parametrize("result", [None, []])
def test_single_success_with_empty_result_reports_failed(client, fake_celery, result):
    fake_celery.set(JOB_ID, "SUCCESS", result)

    response = get_status(client, JOB_ID)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_single_success_with_empty_dict_reports_failed(client, fake_celery):
    fake_celery.set(JOB_ID, "SUCCESS", {})

    assert get_status(client, JOB_ID).json()["error"] == "Unknown error"


def test_result_backend_failure_is_generic_500(client, monkeypatch):
    import main
    def broken(_):
        raise OSError("backend down")
    monkeypatch.setattr(main, "AsyncResult", broken)

    response = get_status(client, JOB_ID)

    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred while checking job status."}


def test_redis_failure_is_generic_500(client, fake_redis, monkeypatch):
    monkeypatch.setattr(fake_redis, "get", AsyncMock(side_effect=ConnectionError("down")))

    assert get_status(client, JOB_ID).status_code == 500


# Batch jobs

MASTER_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
SUB_IDS = {
    name: f"{i:08d}-0000-4000-8000-000000000000"
    for i, name in enumerate(["pending", "done", "errored", "crashed", "started"])
}


async def store_batch(fake_redis, entries):
    await fake_redis.set(MASTER_ID, json.dumps(entries))


async def test_batch_aggregates_each_state(client, fake_redis, fake_celery):
    await store_batch(fake_redis, {
        name: {"job_id": job_id, "status": "new"} for name, job_id in SUB_IDS.items()
    })
    fake_celery.set(SUB_IDS["pending"], "PENDING")
    fake_celery.set(SUB_IDS["done"], "SUCCESS", RESULT)
    fake_celery.set(SUB_IDS["errored"], "SUCCESS", {"error": "Task timeout"})
    fake_celery.set(SUB_IDS["crashed"], "FAILURE", info=ValueError("bad"))
    fake_celery.set(SUB_IDS["started"], "STARTED")

    body = get_status(client, MASTER_ID).json()

    assert body["type"] == "batch"
    assert body["results"] == {
        "pending": {"status": "pending"},
        "done": {"status": "complete", "results": RESULT},
        "errored": {"status": "failed", "error": "Task timeout"},
        "crashed": {"status": "failed", "error": "bad"},
        "started": {"status": "unknown", "state": "STARTED"},
    }


async def test_batch_entry_without_job_id_is_error(client, fake_redis):
    await store_batch(fake_redis, {
        "bad name": {"status": "error", "detail": "Invalid username format"},
    })

    body = get_status(client, MASTER_ID).json()

    assert body["results"] == {"bad name": {"status": "error", "detail": "Invalid job ID"}}


async def test_empty_batch(client, fake_redis):
    await store_batch(fake_redis, {})

    response = get_status(client, MASTER_ID)

    # An empty JSON object is still truthy as a string, so it is treated as a batch
    assert response.json()["type"] == "batch"
    assert response.json()["results"] == {}


def test_batch_round_trip(client, fake_celery):
    submitted = client.post("/api/v1/batch", json={"usernames": ["alice", "bob", "bad name"]}).json()
    fake_celery.set(submitted["jobs"]["alice"]["job_id"], "SUCCESS", RESULT)

    body = get_status(client, submitted["master_job_id"]).json()

    assert body["type"] == "batch"
    assert body["results"]["alice"] == {"status": "complete", "results": RESULT}
    assert body["results"]["bob"] == {"status": "pending"}
    assert body["results"]["bad name"]["status"] == "error"


def test_single_round_trip(client, fake_celery):
    job_id = client.post("/api/v1/lookup", json={"username": "alice"}).json()["job_id"]
    assert get_status(client, job_id).json()["status"] == "pending"

    fake_celery.set(job_id, "SUCCESS", RESULT)

    assert get_status(client, job_id).json()["status"] == "complete"


async def test_corrupt_batch_record_is_500(client, fake_redis):
    await fake_redis.set(MASTER_ID, "{not json")

    assert get_status(client, MASTER_ID).status_code == 500


@pytest.mark.xfail(strict=True, reason=(
    "BUG: the batch branch reuses `job_id` as its loop variable, so the response reports the "
    "last sub-job's ID instead of the master job ID."
))
async def test_batch_response_reports_master_job_id(client, fake_redis):
    await store_batch(fake_redis, {"alice": {"job_id": SUB_IDS["done"], "status": "new"}})

    assert get_status(client, MASTER_ID).json()["job_id"] == MASTER_ID


@pytest.mark.xfail(strict=True, reason=(
    "BUG: a SUCCESS sub-job whose result is None or [] raises AttributeError, failing the "
    "whole batch status request with 500."
))
@pytest.mark.parametrize("result", [None, []])
async def test_batch_with_empty_result_reports_failed(client, fake_redis, fake_celery, result):
    await store_batch(fake_redis, {
        "alice": {"job_id": SUB_IDS["done"], "status": "new"},
        "bob": {"job_id": SUB_IDS["pending"], "status": "new"},
    })
    fake_celery.set(SUB_IDS["done"], "SUCCESS", result)

    response = get_status(client, MASTER_ID)

    assert response.status_code == 200
    assert response.json()["results"]["alice"]["status"] == "failed"
    assert response.json()["results"]["bob"]["status"] == "pending"


@pytest.mark.xfail(strict=True, reason=(
    "BUG: username cache keys and batch master IDs share one Redis keyspace. Looking up a "
    "username that is itself a UUID makes /status/{that-uuid} parse the cached job ID as "
    "batch JSON and return 500."
))
def test_uuid_shaped_username_does_not_break_status(client):
    client.post("/api/v1/lookup", json={"username": JOB_ID})

    assert get_status(client, JOB_ID).status_code == 200

"""Unit tests for utils/tasks.py (Celery task wrapper)."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from utils import tasks
from utils.config import JOB_TIMEOUT


@pytest.fixture
def event_loop_for_task():
    """check_username drives its own loop via get_event_loop(); give it a fresh one."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()
    asyncio.set_event_loop(None)


def test_returns_lookup_result(monkeypatch, event_loop_for_task):
    result = {"websites": [], "stats": {"websites_checked": 0, "profiles_found": 0, "errors": 0}}
    lookup = AsyncMock(return_value=result)
    monkeypatch.setattr(tasks, "username_lookup", lookup)

    assert tasks.check_username("kodama") == result
    lookup.assert_awaited_once_with("kodama")


def test_soft_time_limit_returns_error_dict(monkeypatch, event_loop_for_task):
    monkeypatch.setattr(tasks, "username_lookup", AsyncMock(side_effect=SoftTimeLimitExceeded()))

    assert tasks.check_username("kodama") == {
        "error": "Task timeout",
        "message": "The task took too long and was canceled.",
    }


def test_unexpected_error_returns_none(monkeypatch, event_loop_for_task):
    monkeypatch.setattr(tasks, "username_lookup", AsyncMock(side_effect=RuntimeError("boom")))

    assert tasks.check_username("kodama") is None


def test_time_limits_follow_job_timeout():
    assert tasks.check_username.soft_time_limit == JOB_TIMEOUT
    assert tasks.check_username.time_limit == JOB_TIMEOUT + 60


def test_task_is_registered():
    assert tasks.check_username.name in tasks.celery.tasks

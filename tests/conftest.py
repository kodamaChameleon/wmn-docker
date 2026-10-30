"""
Shared fixtures for the WMN-Docker test suite.

The app reads its configuration at import time, so the environment has to be
prepared here before any app module is imported.
"""
import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from cryptography.fernet import Fernet

# Environment the app expects; must be in place before importing utils.config
os.environ["SECRET_KEY"] = Fernet.generate_key().decode()
os.environ["AUTH_REQUIRED"] = "false"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["CELERY_BROKER_URL"] = "memory://"
os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"
for var in ("RATE_LIMIT", "CACHE_EXPIRATION", "ACCESS_TOKEN_EXPIRATION", "VERBOSE"):
    os.environ.pop(var, None)

# Keep logs out of /var/log/wmn-docker
import utils.config  # noqa: E402
utils.config.LOG_DIR = tempfile.mkdtemp(prefix="wmn-test-logs-")

import fakeredis  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from passlib.context import CryptContext  # noqa: E402

import main  # noqa: E402
import users  # noqa: E402
from utils import authentication, core  # noqa: E402
from utils.config import SECRET_KEY, ALGORITHM  # noqa: E402
from utils.models import User, Users  # noqa: E402

from helpers import ACTIVE_USER_ID, ACTIVE_SECRET, DISABLED_USER_ID, DISABLED_SECRET  # noqa: E402


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    """Use the minimum bcrypt cost so hashing doesn't dominate test time."""
    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)
    monkeypatch.setattr(users, "pwd_context", ctx)
    monkeypatch.setattr(authentication, "pwd_context", ctx)
    return ctx


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    """Point the user database at a per-test temp file (never /home/kodama)."""
    db_file = str(tmp_path / "user.db")
    monkeypatch.setattr(users, "DB_FILE", db_file)
    return db_file


@pytest.fixture(autouse=True)
def reset_wmn_cache():
    """Clear the in-memory WMN site list cache between tests."""
    core._wmn_data_cache.update(data=None, fetched_at=0.0)
    yield
    core._wmn_data_cache.update(data=None, fetched_at=0.0)


@pytest.fixture
def user_db(fast_hashing, isolated_db):
    """A user database with one enabled and one disabled user."""
    users.save_user_data(Users(users=[
        User(user_id=ACTIVE_USER_ID, secret=fast_hashing.hash(ACTIVE_SECRET), disabled=False),
        User(user_id=DISABLED_USER_ID, secret=fast_hashing.hash(DISABLED_SECRET), disabled=True),
    ]))
    return isolated_db


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace the app's Redis connection with an isolated in-memory fake."""
    conn = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(main, "redis_connection", conn)
    return conn


class FakeCelery:
    """
    Stand-in for Celery: records submitted jobs and serves canned task states.
    Unknown job IDs report PENDING, matching real Celery behavior.
    """

    def __init__(self):
        self.jobs = {}
        self.delay = MagicMock(side_effect=self._delay)

    def _delay(self, username):
        job_id = str(uuid4())
        self.jobs.setdefault(job_id, ("PENDING", None, None))
        return SimpleNamespace(id=job_id)

    def set(self, job_id, state, result=None, info=None):
        if isinstance(job_id, bytes):
            job_id = job_id.decode()
        self.jobs[job_id] = (state, result, info if info is not None else result)

    def async_result(self, job_id):
        if isinstance(job_id, bytes):
            job_id = job_id.decode()
        state, result, info = self.jobs.get(job_id, ("PENDING", None, None))
        return SimpleNamespace(id=job_id, state=state, result=result, info=info)


@pytest.fixture
def fake_celery(monkeypatch):
    celery = FakeCelery()
    monkeypatch.setattr(main.check_username, "delay", celery.delay)
    monkeypatch.setattr(main, "AsyncResult", celery.async_result)
    return celery


@pytest.fixture
def client(fake_redis, fake_celery):
    """TestClient with the lifespan (rate limiter init) running against fake Redis."""
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def auth_required():
    """
    Enforce JWT auth on every route, as if AUTH_REQUIRED=true at startup.

    AUTH_REQUIRED is evaluated when routes are declared, so each route holds its own
    no-op lambda dependency; override each of those with the real get_current_user.
    """
    for route in main.app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for dep in dependant.dependencies:
            if getattr(dep.call, "__name__", "") == "<lambda>":
                main.app.dependency_overrides[dep.call] = authentication.get_current_user
    yield
    main.app.dependency_overrides.clear()


@pytest.fixture
def make_token():
    """Build JWTs with arbitrary claims, signed with the app's key by default."""
    def _make(sub=ACTIVE_USER_ID, exp=timedelta(days=1), key=SECRET_KEY, **extra):
        payload = dict(extra)
        if sub is not None:
            payload["sub"] = sub
        if isinstance(exp, timedelta):
            payload["exp"] = datetime.now(timezone.utc) + exp
        elif exp is not None:
            payload["exp"] = exp
        return jwt.encode(payload, key, algorithm=ALGORITHM)
    return _make

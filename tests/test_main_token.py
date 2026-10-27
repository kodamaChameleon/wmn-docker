"""Tests for POST /api/v1/token."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from helpers import ACTIVE_USER_ID, ACTIVE_SECRET, DISABLED_USER_ID, DISABLED_SECRET
from utils.config import SECRET_KEY, ALGORITHM

TOKEN_URL = "/api/v1/token"


def test_valid_credentials_return_bearer_token(client, user_db):
    response = client.post(TOKEN_URL, json={"user_id": ACTIVE_USER_ID, "secret": ACTIVE_SECRET})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    payload = jwt.decode(body["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == ACTIVE_USER_ID


def test_token_expires_after_configured_days(client, user_db):
    response = client.post(TOKEN_URL, json={"user_id": ACTIVE_USER_ID, "secret": ACTIVE_SECRET})

    payload = jwt.decode(response.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    expires = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    expected = datetime.now(timezone.utc) + timedelta(days=7)
    assert abs((expires - expected).total_seconds()) < 60


@pytest.mark.parametrize("user_id, secret", [
    (ACTIVE_USER_ID, "wrong-secret"),
    ("no-such-user", ACTIVE_SECRET),
    (DISABLED_USER_ID, DISABLED_SECRET),
    (ACTIVE_USER_ID, ""),
])
def test_rejected_credentials_share_one_generic_401(client, user_db, user_id, secret):
    response = client.post(TOKEN_URL, json={"user_id": user_id, "secret": secret})

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect user ID or secret"}


@pytest.mark.parametrize("body", [
    {},
    {"user_id": ACTIVE_USER_ID},
    {"secret": ACTIVE_SECRET},
    {"user_id": None, "secret": ACTIVE_SECRET},
    {"user_id": ["list"], "secret": ACTIVE_SECRET},
])
def test_malformed_body_is_422(client, user_db, body):
    assert client.post(TOKEN_URL, json=body).status_code == 422


def test_non_json_body_is_422(client, user_db):
    response = client.post(TOKEN_URL, content="user_id=1&secret=2",
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 422


def test_missing_user_database_is_500(client):
    # isolated_db points at a file that was never created
    response = client.post(TOKEN_URL, json={"user_id": ACTIVE_USER_ID, "secret": ACTIVE_SECRET})

    assert response.status_code == 500
    assert response.json() == {"detail": "Unknown error during authentication"}


def test_corrupt_user_database_is_500(client, isolated_db):
    with open(isolated_db, "wb") as f:
        f.write(b"not a fernet token")

    response = client.post(TOKEN_URL, json={"user_id": ACTIVE_USER_ID, "secret": ACTIVE_SECRET})

    assert response.status_code == 500
    assert "fernet" not in response.text.lower()

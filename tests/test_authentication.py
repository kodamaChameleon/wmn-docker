"""Unit tests for utils/authentication.py."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from helpers import ACTIVE_USER_ID, ACTIVE_SECRET, DISABLED_USER_ID, DISABLED_SECRET
from utils import authentication
from utils.config import SECRET_KEY, ALGORITHM


# authenticate_user

def test_authenticate_user_success(user_db):
    user = authentication.authenticate_user(ACTIVE_USER_ID, ACTIVE_SECRET)

    assert user.user_id == ACTIVE_USER_ID
    assert user.disabled is False


@pytest.mark.parametrize("user_id, secret", [
    (ACTIVE_USER_ID, "wrong"),
    (ACTIVE_USER_ID, ACTIVE_SECRET.upper()),
    ("unknown", ACTIVE_SECRET),
    (DISABLED_USER_ID, DISABLED_SECRET),
    ("", ""),
])
def test_authenticate_user_rejects(user_db, user_id, secret):
    assert authentication.authenticate_user(user_id, secret) is False


def test_authenticate_user_db_error_is_http_500():
    with pytest.raises(HTTPException) as exc:
        authentication.authenticate_user(ACTIVE_USER_ID, ACTIVE_SECRET)

    assert exc.value.status_code == 500


# create_access_token

def decode(token):
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


@pytest.mark.parametrize("days", [1, 7, 30])
def test_create_access_token_expiry(monkeypatch, days):
    monkeypatch.setattr(authentication, "ACCESS_TOKEN_EXPIRATION", days)

    payload = decode(authentication.create_access_token({"sub": "abc"}))

    expected = datetime.now(timezone.utc) + timedelta(days=days)
    assert abs(payload["exp"] - expected.timestamp()) < 60
    assert payload["sub"] == "abc"


def test_create_access_token_does_not_mutate_input():
    data = {"sub": "abc"}
    authentication.create_access_token(data)
    assert data == {"sub": "abc"}


def test_create_access_token_uses_hs256():
    token = authentication.create_access_token({"sub": "abc"})
    assert jwt.get_unverified_header(token)["alg"] == "HS256"


# get_current_user

def test_get_current_user_returns_user_id(make_token):
    assert authentication.get_current_user(make_token(sub="abc")) == {"user_id": "abc"}


def test_get_current_user_accepts_token_without_exp(make_token):
    assert authentication.get_current_user(make_token(exp=None)) == {"user_id": ACTIVE_USER_ID}


@pytest.mark.parametrize("token_kwargs, detail", [
    ({"exp": timedelta(seconds=-1)}, "Token has expired"),
    ({"key": "wrong-key"}, "Invalid authentication credentials"),
], ids=["expired", "bad-signature"])
def test_get_current_user_rejects(make_token, token_kwargs, detail):
    with pytest.raises(HTTPException) as exc:
        authentication.get_current_user(make_token(**token_kwargs))

    assert exc.value.status_code == 401
    assert exc.value.detail == detail


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "Bearer x"])
def test_get_current_user_rejects_garbage(token):
    with pytest.raises(HTTPException) as exc:
        authentication.get_current_user(token)

    assert exc.value.status_code == 401


def test_get_current_user_rejects_missing_sub(make_token):
    with pytest.raises(HTTPException) as exc:
        authentication.get_current_user(make_token(sub=None))

    assert exc.value.status_code == 401


@pytest.mark.xfail(strict=True, reason=(
    "BUG: HTTPExceptions raised inside get_current_user's try block are caught by the "
    "generic `except Exception` and replaced with 'Authentication error'."
))
def test_get_current_user_missing_sub_detail(make_token):
    with pytest.raises(HTTPException) as exc:
        authentication.get_current_user(make_token(sub=None))

    assert exc.value.detail == "Invalid authentication credentials"


@pytest.mark.xfail(strict=True, reason=(
    "BUG: ACCESS_TOKEN_EXPIRATION=0 encodes exp=null; PyJWT raises TypeError on decode, "
    "so 'never expire' tokens are always rejected."
))
def test_non_expiring_token_round_trip(monkeypatch):
    monkeypatch.setattr(authentication, "ACCESS_TOKEN_EXPIRATION", 0)
    token = authentication.create_access_token({"sub": "abc"})

    assert authentication.get_current_user(token) == {"user_id": "abc"}


# optional_auth_dependency

def test_optional_auth_disabled_returns_noop(monkeypatch):
    monkeypatch.setattr(authentication, "AUTH_REQUIRED", False)

    dependency = authentication.optional_auth_dependency()

    assert dependency is not authentication.get_current_user
    assert dependency() is None


def test_optional_auth_enabled_returns_get_current_user(monkeypatch):
    monkeypatch.setattr(authentication, "AUTH_REQUIRED", True)

    assert authentication.optional_auth_dependency() is authentication.get_current_user

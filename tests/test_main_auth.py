"""Route-level authentication when AUTH_REQUIRED is enabled."""
from datetime import timedelta

import pytest

import users
from helpers import ACTIVE_USER_ID, ACTIVE_SECRET, bearer
from utils import authentication

JOB_ID = "11111111-2222-3333-4444-555555555555"
PROTECTED = [
    ("post", "/api/v1/lookup", {"json": {"username": "kodama"}}),
    ("post", "/api/v1/batch", {"json": {"usernames": ["kodama"]}}),
    ("get", f"/api/v1/status/{JOB_ID}", {}),
]
route_ids = [path.split("/")[3] for _, path, _ in PROTECTED]


def call(client, method, path, kwargs, headers=None):
    return getattr(client, method)(path, headers=headers or {}, **kwargs)


@pytest.mark.parametrize("method, path, kwargs", PROTECTED, ids=route_ids)
def test_routes_are_open_when_auth_not_required(client, method, path, kwargs):
    assert call(client, method, path, kwargs).status_code == 200


@pytest.mark.parametrize("method, path, kwargs", PROTECTED, ids=route_ids)
def test_missing_token_is_401(client, auth_required, fake_celery, method, path, kwargs):
    response = call(client, method, path, kwargs)

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    fake_celery.delay.assert_not_called()


@pytest.mark.parametrize("method, path, kwargs", PROTECTED, ids=route_ids)
def test_valid_token_is_accepted(client, auth_required, make_token, method, path, kwargs):
    response = call(client, method, path, kwargs, bearer(make_token()))
    assert response.status_code == 200


@pytest.mark.parametrize("method, path, kwargs", PROTECTED, ids=route_ids)
@pytest.mark.parametrize("token_kwargs, detail", [
    ({"exp": timedelta(seconds=-10)}, "Token has expired"),
    ({"key": "some-other-signing-key"}, "Invalid authentication credentials"),
    ({"sub": None}, None),  # detail is wrong; see test_authentication
], ids=["expired", "bad-signature", "no-sub"])
def test_bad_token_is_401(client, auth_required, make_token, fake_celery,
                          method, path, kwargs, token_kwargs, detail):
    response = call(client, method, path, kwargs, bearer(make_token(**token_kwargs)))

    assert response.status_code == 401
    if detail:
        assert response.json() == {"detail": detail}
    fake_celery.delay.assert_not_called()


@pytest.mark.parametrize("header", [
    "Bearer not.a.jwt",
    "Bearer ",
    "Basic dXNlcjpwYXNz",
    "garbage",
])
def test_malformed_authorization_header_is_401(client, auth_required, header):
    response = client.post("/api/v1/lookup", json={"username": "kodama"},
                           headers={"Authorization": header})
    assert response.status_code == 401


def test_alg_none_token_is_rejected(client, auth_required):
    import jwt
    token = jwt.encode({"sub": ACTIVE_USER_ID}, key=None, algorithm="none")

    response = client.post("/api/v1/lookup", json={"username": "kodama"}, headers=bearer(token))

    assert response.status_code == 401


def test_token_endpoint_stays_public(client, auth_required, user_db):
    response = client.post("/api/v1/token", json={"user_id": ACTIVE_USER_ID, "secret": ACTIVE_SECRET})
    assert response.status_code == 200


def test_login_then_lookup_flow(client, auth_required, user_db, fake_celery):
    token = client.post(
        "/api/v1/token", json={"user_id": ACTIVE_USER_ID, "secret": ACTIVE_SECRET}
    ).json()["access_token"]

    lookup = client.post("/api/v1/lookup", json={"username": "kodama"}, headers=bearer(token))
    assert lookup.status_code == 200

    status = client.get(f"/api/v1/status/{lookup.json()['job_id']}", headers=bearer(token))
    assert status.status_code == 200
    assert status.json()["status"] == "pending"


def test_auth_is_checked_before_body_validation_side_effects(client, auth_required, fake_celery):
    response = client.post("/api/v1/lookup", json={"username": "bad name"})

    assert response.status_code == 401


@pytest.mark.xfail(strict=True, reason=(
    "BUG: ACCESS_TOKEN_EXPIRATION=0 is documented as 'never expire', but it encodes "
    "exp=null, which PyJWT rejects on decode, so every such token gets a 401."
))
def test_non_expiring_token_is_accepted(client, auth_required, user_db, monkeypatch):
    monkeypatch.setattr(authentication, "ACCESS_TOKEN_EXPIRATION", 0)
    token = client.post(
        "/api/v1/token", json={"user_id": ACTIVE_USER_ID, "secret": ACTIVE_SECRET}
    ).json()["access_token"]

    response = client.post("/api/v1/lookup", json={"username": "kodama"}, headers=bearer(token))

    assert response.status_code == 200


@pytest.mark.xfail(strict=True, reason=(
    "DESIGN GAP: get_current_user only verifies the JWT signature, so tokens issued before a "
    "user is disabled or deleted keep working until they expire."
))
@pytest.mark.parametrize("revoke", [users.disable_user, users.delete_user],
                         ids=["disabled", "deleted"])
def test_revoked_user_token_is_rejected(client, auth_required, user_db, revoke):
    token = client.post(
        "/api/v1/token", json={"user_id": ACTIVE_USER_ID, "secret": ACTIVE_SECRET}
    ).json()["access_token"]
    revoke(ACTIVE_USER_ID)

    response = client.post("/api/v1/lookup", json={"username": "kodama"}, headers=bearer(token))

    assert response.status_code == 401

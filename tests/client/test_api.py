"""Light tests for the CLI client in utils/api.py."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests


def response(status=200, data=None, text=""):
    resp = MagicMock(status_code=status, text=text)
    resp.json.return_value = data or {}
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    return resp


def args(username, api_id=None, api_secret=None, output=None):
    return SimpleNamespace(username=username, api_id=api_id, api_secret=api_secret, output=output)


# get_access_token

def test_get_access_token_success(api, monkeypatch):
    post = MagicMock(return_value=response(200, {"access_token": "tok"}))
    monkeypatch.setattr(api.requests, "post", post)

    assert api.get_access_token("id", "secret") == "tok"
    assert post.call_args.args[0] == "http://api.test/api/v1/token"
    assert post.call_args.kwargs["json"] == {"user_id": "id", "secret": "secret"}


def test_get_access_token_rejected(api, monkeypatch, capsys):
    monkeypatch.setattr(api.requests, "post", MagicMock(return_value=response(401, text="nope")))

    assert api.get_access_token("id", "bad") is None
    assert "401" in capsys.readouterr().out


def test_get_access_token_network_error(api, monkeypatch, capsys):
    monkeypatch.setattr(api.requests, "post", MagicMock(side_effect=requests.ConnectionError("down")))

    assert api.get_access_token("id", "secret") is None


# submit_username

def test_submit_username_returns_job_id(api, monkeypatch, capsys):
    post = MagicMock(return_value=response(200, {"job_id": "abc"}))
    monkeypatch.setattr(api.requests, "post", post)

    assert api.submit_username("kodama", token="tok") == "abc"
    assert post.call_args.kwargs["json"] == {"username": "kodama"}
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"


def test_submit_username_http_error(api, monkeypatch, capsys):
    monkeypatch.setattr(api.requests, "post", MagicMock(return_value=response(429)))

    assert api.submit_username("kodama") is None


def test_submit_batch_returns_master_job_id(api, monkeypatch, capsys):
    data = {"master_job_id": "m1", "jobs": {"a": {"status": "new", "job_id": "j1"}}}
    monkeypatch.setattr(api.requests, "post", MagicMock(return_value=response(200, data)))

    assert api.submit_batch_usernames(["a"]) == "m1"
    assert "j1" in capsys.readouterr().out


# display_results

def test_display_results_with_profiles(api, capsys):
    api.display_results({
        "websites": [["GitHub", "https://github.com/kodama"]],
        "stats": {"websites_checked": 700, "profiles_found": 1, "errors": 3},
    })

    out = capsys.readouterr().out
    assert "https://github.com/kodama" in out
    assert "700" in out and "3" in out


def test_display_results_empty(api, capsys):
    api.display_results({})

    assert "No profiles found." in capsys.readouterr().out


# user_lookup

@pytest.fixture
def stub_flow(api, monkeypatch):
    stubs = SimpleNamespace(
        submit=MagicMock(return_value="job-1"),
        batch=MagicMock(return_value="master-1"),
        poll=MagicMock(),
        token=MagicMock(return_value="tok"),
    )
    monkeypatch.setattr(api, "submit_username", stubs.submit)
    monkeypatch.setattr(api, "submit_batch_usernames", stubs.batch)
    monkeypatch.setattr(api, "poll_job_status", stubs.poll)
    monkeypatch.setattr(api, "get_access_token", stubs.token)
    monkeypatch.setattr(api, "AUTH_REQUIRED", False)
    return stubs


def test_user_lookup_single(api, stub_flow, capsys):
    api.user_lookup(args("kodama", output="out.json"))

    stub_flow.submit.assert_called_once_with("kodama", None)
    stub_flow.poll.assert_called_once_with("job-1", False, None, output_file="out.json", username="kodama")


def test_user_lookup_batch(api, stub_flow, capsys):
    api.user_lookup(args("alice,bob"))

    stub_flow.batch.assert_called_once_with(["alice", "bob"], None)
    stub_flow.poll.assert_called_once_with("master-1", True, None, output_file=None, username=None)


def test_user_lookup_auth_missing_credentials(api, stub_flow, monkeypatch, capsys):
    monkeypatch.setattr(api, "AUTH_REQUIRED", True)
    monkeypatch.setattr(api, "USER_ID", None)
    monkeypatch.setattr(api, "SECRET", None)

    api.user_lookup(args("kodama"))

    assert "required but not provided" in capsys.readouterr().out
    stub_flow.submit.assert_not_called()


def test_user_lookup_auth_passes_token(api, stub_flow, monkeypatch, capsys):
    monkeypatch.setattr(api, "AUTH_REQUIRED", True)

    api.user_lookup(args("kodama", api_id="id", api_secret="secret"))

    stub_flow.token.assert_called_once_with("id", "secret")
    stub_flow.submit.assert_called_once_with("kodama", "tok")


def test_user_lookup_stops_when_submit_fails(api, stub_flow, capsys):
    stub_flow.submit.return_value = None

    api.user_lookup(args("kodama"))

    stub_flow.poll.assert_not_called()

"""Unit tests for utils/core.py (site checks and WMN data fetching)."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError

from utils import core
from utils.config import CACHE_EXPIRATION, WMN_URL

SITE = {
    "name": "ExampleSite",
    "uri_check": "https://example.com/users/{account}",
    "e_code": 200,
    "e_string": "Profile of",
}


class FakeResponse:
    def __init__(self, status=200, text="", url=None, history=(),
                 content_type="application/json", json_data=None):
        self.status = status
        self._text = text
        self.url = url
        self.history = history
        self.content_type = content_type
        self._json = json_data

    async def text(self):
        return self._text

    async def json(self):
        return self._json


class FakeRequest:
    """Mimics aiohttp's _RequestContextManager: usable with both `await` and `async with`."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def _resolve(self):
        if self.error:
            raise self.error
        return self.response

    def __await__(self):
        return self._resolve().__await__()

    async def __aenter__(self):
        return await self._resolve()

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return FakeRequest(self.response, self.error)


# check_site

async def test_check_site_found():
    session = FakeSession(FakeResponse(200, "<h1>Profile of kodama</h1>"))

    result = await core.check_site(session, SITE, "kodama")

    assert result == ("ExampleSite", "https://example.com/users/kodama")


async def test_check_site_formats_username_into_uri():
    session = FakeSession(FakeResponse(404))

    await core.check_site(session, SITE, "kodama")

    url, kwargs = session.requests[0]
    assert url == "https://example.com/users/kodama"
    assert kwargs["headers"] == core.WMN_HEADERS
    assert kwargs["timeout"].total == core.CHECK_SITE_TIMEOUT


@pytest.mark.parametrize("status, text", [
    (404, "Profile of kodama"),
    (200, "Page not found"),
    (500, ""),
    (301, "Profile of kodama"),
])
async def test_check_site_not_found(status, text):
    session = FakeSession(FakeResponse(status, text))

    assert await core.check_site(session, SITE, "kodama") is None


async def test_check_site_redirect_away_from_username_is_ignored():
    session = FakeSession(FakeResponse(
        200, "Profile of", url="https://example.com/login", history=("redirect",)
    ))

    assert await core.check_site(session, SITE, "kodama") is None


async def test_check_site_redirect_keeping_username_is_found():
    session = FakeSession(FakeResponse(
        200, "Profile of", url="https://example.com/u/KODAMA", history=("redirect",)
    ))

    assert await core.check_site(session, SITE, "kodama") is not None


async def test_check_site_no_redirect_ignores_final_url():
    session = FakeSession(FakeResponse(200, "Profile of", url="https://other.example/", history=()))

    assert await core.check_site(session, SITE, "kodama") is not None


@pytest.mark.parametrize("error", [
    asyncio.TimeoutError(),
    ClientError("connection reset"),
    RuntimeError("unexpected"),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte"),
])
async def test_check_site_errors_are_reported(error):
    session = FakeSession(error=error)

    assert await core.check_site(session, SITE, "kodama") == ("error", "ExampleSite")


async def test_check_site_bad_uri_template_is_error():
    site = dict(SITE, uri_check="https://example.com/{missing}")

    with pytest.raises(KeyError):
        await core.check_site(FakeSession(), site, "kodama")


# check_username_existence

async def test_check_username_existence_aggregates(monkeypatch):
    sites = [dict(SITE, name=f"site{i}") for i in range(5)]
    outcomes = {
        "site0": ("site0", "https://a/kodama"),
        "site1": None,
        "site2": ("error", "site2"),
        "site3": ("site3", "https://b/kodama"),
        "site4": ("error", "site4"),
    }
    monkeypatch.setattr(core, "check_site", AsyncMock(side_effect=lambda s, site, u: outcomes[site["name"]]))

    found, stats = await core.check_username_existence("kodama", {"sites": sites})

    assert found == [("site0", "https://a/kodama"), ("site3", "https://b/kodama")]
    assert stats == {"websites_checked": 5, "profiles_found": 2, "errors": 2}


async def test_check_username_existence_no_sites():
    found, stats = await core.check_username_existence("kodama", {"sites": []})

    assert found == []
    assert stats == {"websites_checked": 0, "profiles_found": 0, "errors": 0}


async def test_check_username_existence_checks_every_site(monkeypatch):
    check = AsyncMock(return_value=None)
    monkeypatch.setattr(core, "check_site", check)
    sites = [dict(SITE, name=f"site{i}") for i in range(25)]

    await core.check_username_existence("kodama", {"sites": sites})

    assert check.await_count == 25
    assert {c.args[2] for c in check.await_args_list} == {"kodama"}


# fetch_wmn_data

WMN_DATA = {"sites": [SITE]}


@pytest.fixture
def fake_github(monkeypatch):
    """Patch ClientSession in core so fetch_wmn_data never hits the network."""
    state = {"calls": 0, "response": FakeResponse(json_data=WMN_DATA), "urls": []}

    class Session(FakeSession):
        def __init__(self, *args, **kwargs):
            super().__init__(state["response"])

        def get(self, url, **kwargs):
            state["calls"] += 1
            state["urls"].append(url)
            return super().get(url, **kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(core, "ClientSession", Session)
    return state


async def test_fetch_wmn_data_json(fake_github):
    assert await core.fetch_wmn_data() == WMN_DATA
    assert fake_github["urls"] == [WMN_URL]


async def test_fetch_wmn_data_parses_text_content_type(fake_github):
    fake_github["response"] = FakeResponse(content_type="text/plain", text=json.dumps(WMN_DATA))

    assert await core.fetch_wmn_data() == WMN_DATA


async def test_fetch_wmn_data_is_cached(fake_github):
    await core.fetch_wmn_data()
    await core.fetch_wmn_data()

    assert fake_github["calls"] == 1


async def test_fetch_wmn_data_refreshes_after_expiry(fake_github, monkeypatch):
    clock = {"now": 10_000.0}
    monkeypatch.setattr(core.time, "monotonic", lambda: clock["now"])

    await core.fetch_wmn_data()
    clock["now"] += CACHE_EXPIRATION - 1
    await core.fetch_wmn_data()
    assert fake_github["calls"] == 1

    clock["now"] += 1
    await core.fetch_wmn_data()
    assert fake_github["calls"] == 2


async def test_fetch_wmn_data_concurrent_calls_fetch_once(fake_github):
    results = await asyncio.gather(*(core.fetch_wmn_data() for _ in range(10)))

    assert all(r == WMN_DATA for r in results)
    assert fake_github["calls"] == 1


async def test_fetch_wmn_data_invalid_json_raises(fake_github):
    fake_github["response"] = FakeResponse(content_type="text/html", text="<html>rate limited</html>")

    with pytest.raises(json.JSONDecodeError):
        await core.fetch_wmn_data()
    assert core._wmn_data_cache["data"] is None


# username_lookup

async def test_username_lookup_success(monkeypatch):
    monkeypatch.setattr(core, "fetch_wmn_data", AsyncMock(return_value=WMN_DATA))
    stats = {"websites_checked": 1, "profiles_found": 1, "errors": 0}
    existence = AsyncMock(return_value=([("ExampleSite", "https://x")], stats))
    monkeypatch.setattr(core, "check_username_existence", existence)

    result = await core.username_lookup("kodama")

    assert result == {"websites": [("ExampleSite", "https://x")], "stats": stats}
    existence.assert_awaited_once_with("kodama", WMN_DATA)


async def test_username_lookup_fetch_error_returns_empty_list(monkeypatch):
    monkeypatch.setattr(core, "fetch_wmn_data", AsyncMock(side_effect=ClientError("offline")))

    assert await core.username_lookup("kodama") == []


@pytest.mark.parametrize("data", [None, {}])
async def test_username_lookup_no_data_returns_none(monkeypatch, data):
    monkeypatch.setattr(core, "fetch_wmn_data", AsyncMock(return_value=data))

    assert await core.username_lookup("kodama") is None

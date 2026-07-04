from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from modrinth_analytics.api import (
    BASE_URL,
    ModrinthAPIError,
    ModrinthClient,
)

SEARCH_RESPONSE = {
    "hits": [
        {
            "project_id": "AANobbMI",
            "slug": "sodium",
            "title": "Sodium",
            "project_type": "mod",
            "downloads": 5_000_000,
            "follows": 12_000,
            "categories": ["optimization", "fabric"],
            "versions": ["1.20.1", "1.21"],
            "date_created": "2021-01-03T00:53:34Z",
            "date_modified": "2024-05-01T12:00:00Z",
            "license": "LGPL-3.0-only",
        }
    ],
    "offset": 0,
    "limit": 100,
    "total_hits": 1,
}

PROJECT_RESPONSE = {
    "id": "AANobbMI",
    "slug": "sodium",
    "title": "Sodium",
    "project_type": "mod",
    "downloads": 5_000_000,
    "followers": 12_000,
    "categories": ["optimization"],
    "game_versions": ["1.20.1", "1.21"],
    "loaders": ["fabric", "quilt"],
    "license": {"id": "LGPL-3.0-only", "name": "GNU Lesser General Public License v3 only"},
    "published": "2021-01-03T00:53:34Z",
    "updated": "2024-05-01T12:00:00Z",
}

VERSIONS_RESPONSE = [
    {
        "id": "rAfhHfow",
        "project_id": "AANobbMI",
        "name": "Sodium 0.5.8",
        "version_number": "mc1.20.1-0.5.8",
        "version_type": "release",
        "game_versions": ["1.20.1"],
        "loaders": ["fabric"],
        "downloads": 100_000,
        "date_published": "2024-01-15T10:00:00Z",
    }
]

GAME_VERSIONS_RESPONSE = [
    {"version": "1.21", "version_type": "release", "date": "2024-06-13T00:00:00Z", "major": True},
    {
        "version": "24w14a",
        "version_type": "snapshot",
        "date": "2024-04-02T00:00:00Z",
        "major": False,
    },
]


@respx.mock
def test_search_parses_hits_and_sends_params() -> None:
    route = respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=SEARCH_RESPONSE)
    )
    sleeps: list[float] = []
    with ModrinthClient(sleep=sleeps.append) as client:
        result = client.search(facets=[["project_type:mod"]], limit=50, offset=100)

    assert result.total_hits == 1
    hit = result.hits[0]
    assert hit.slug == "sodium"
    assert hit.game_versions == ["1.20.1", "1.21"]
    assert hit.date_created == datetime(2021, 1, 3, 0, 53, 34, tzinfo=UTC)

    params = route.calls.last.request.url.params
    assert params["index"] == "downloads"
    assert params["limit"] == "50"
    assert params["offset"] == "100"
    assert json.loads(params["facets"]) == [["project_type:mod"]]


@respx.mock
def test_requests_send_descriptive_user_agent() -> None:
    route = respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=SEARCH_RESPONSE)
    )
    sleeps: list[float] = []
    with ModrinthClient(sleep=sleeps.append) as client:
        client.search()

    assert "modrinth-analytics" in route.calls.last.request.headers["User-Agent"]


@respx.mock
def test_get_project_parses_details() -> None:
    respx.get(f"{BASE_URL}/project/sodium").mock(
        return_value=httpx.Response(200, json=PROJECT_RESPONSE)
    )
    sleeps: list[float] = []
    with ModrinthClient(sleep=sleeps.append) as client:
        project = client.get_project("sodium")

    assert project.id == "AANobbMI"
    assert project.loaders == ["fabric", "quilt"]
    assert project.license_id == "LGPL-3.0-only"
    assert project.published == datetime(2021, 1, 3, 0, 53, 34, tzinfo=UTC)


@respx.mock
def test_get_project_versions_parses_list() -> None:
    respx.get(f"{BASE_URL}/project/sodium/version").mock(
        return_value=httpx.Response(200, json=VERSIONS_RESPONSE)
    )
    sleeps: list[float] = []
    with ModrinthClient(sleep=sleeps.append) as client:
        versions = client.get_project_versions("sodium")

    assert len(versions) == 1
    assert versions[0].version_number == "mc1.20.1-0.5.8"
    assert versions[0].date_published == datetime(2024, 1, 15, 10, 0, tzinfo=UTC)


@respx.mock
def test_get_game_versions_parses_release_dates() -> None:
    respx.get(f"{BASE_URL}/tag/game_version").mock(
        return_value=httpx.Response(200, json=GAME_VERSIONS_RESPONSE)
    )
    sleeps: list[float] = []
    with ModrinthClient(sleep=sleeps.append) as client:
        versions = client.get_game_versions()

    assert [v.version for v in versions] == ["1.21", "24w14a"]
    assert versions[0].major is True
    assert versions[0].date == datetime(2024, 6, 13, tzinfo=UTC)


@respx.mock
def test_retries_server_errors_then_succeeds() -> None:
    route = respx.get(f"{BASE_URL}/project/sodium")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, json=PROJECT_RESPONSE),
    ]
    sleeps: list[float] = []
    with ModrinthClient(sleep=sleeps.append) as client:
        project = client.get_project("sodium")

    assert project.slug == "sodium"
    assert route.call_count == 2


@respx.mock
def test_429_waits_for_ratelimit_reset() -> None:
    route = respx.get(f"{BASE_URL}/project/sodium")
    route.side_effect = [
        httpx.Response(429, headers={"X-Ratelimit-Reset": "7"}),
        httpx.Response(200, json=PROJECT_RESPONSE),
    ]
    sleeps: list[float] = []
    with ModrinthClient(sleep=sleeps.append) as client:
        client.get_project("sodium")

    assert 7.0 in sleeps
    assert route.call_count == 2


@respx.mock
def test_client_error_raises_without_retry() -> None:
    route = respx.get(f"{BASE_URL}/project/missing").mock(return_value=httpx.Response(404))
    sleeps: list[float] = []
    with (
        ModrinthClient(sleep=sleeps.append) as client,
        pytest.raises(ModrinthAPIError) as excinfo,
    ):
        client.get_project("missing")

    assert excinfo.value.status_code == 404
    assert route.call_count == 1


@respx.mock
def test_gives_up_after_max_retries() -> None:
    route = respx.get(f"{BASE_URL}/project/sodium").mock(return_value=httpx.Response(503))
    sleeps: list[float] = []
    with (
        ModrinthClient(sleep=sleeps.append, max_retries=2) as client,
        pytest.raises(ModrinthAPIError) as excinfo,
    ):
        client.get_project("sodium")

    assert excinfo.value.status_code == 503
    assert route.call_count == 3


@respx.mock
def test_throttles_between_requests() -> None:
    respx.get(f"{BASE_URL}/tag/game_version").mock(
        return_value=httpx.Response(200, json=GAME_VERSIONS_RESPONSE)
    )
    sleeps: list[float] = []
    with ModrinthClient(sleep=sleeps.append, requests_per_minute=60) as client:
        client.get_game_versions()
        client.get_game_versions()

    assert any(0 < wait <= 1.0 for wait in sleeps)


@respx.mock
def test_pauses_when_rate_limit_exhausted() -> None:
    respx.get(f"{BASE_URL}/tag/game_version").mock(
        return_value=httpx.Response(
            200,
            json=GAME_VERSIONS_RESPONSE,
            headers={"X-Ratelimit-Remaining": "0", "X-Ratelimit-Reset": "12"},
        )
    )
    sleeps: list[float] = []
    with ModrinthClient(sleep=sleeps.append) as client:
        client.get_game_versions()

    assert 12.0 in sleeps

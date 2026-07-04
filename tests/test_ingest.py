from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import respx

from modrinth_analytics.__main__ import main
from modrinth_analytics.api import BASE_URL, ModrinthClient
from modrinth_analytics.db import Database
from modrinth_analytics.ingest import ingest

FETCHED_AT = datetime(2026, 7, 3, 6, 0, tzinfo=UTC)


def hit_json(project_id: str, project_type: str = "mod") -> dict[str, Any]:
    return {
        "project_id": project_id,
        "slug": f"slug-{project_id}",
        "title": project_id.upper(),
        "project_type": project_type,
        "downloads": 1_000,
        "follows": 10,
        "categories": ["optimization"],
        "versions": ["1.21"],
        "date_created": "2021-01-03T00:00:00Z",
        "date_modified": "2024-05-01T00:00:00Z",
        "license": "MIT",
    }


def search_json(hits: list[dict[str, Any]], total_hits: int | None = None) -> dict[str, Any]:
    return {
        "hits": hits,
        "offset": 0,
        "limit": 100,
        "total_hits": total_hits if total_hits is not None else len(hits),
    }


def project_json(project_id: str, project_type: str = "mod") -> dict[str, Any]:
    return {
        "id": project_id,
        "slug": f"slug-{project_id}",
        "title": project_id.upper(),
        "project_type": project_type,
        "downloads": 1_000,
        "followers": 10,
        "categories": ["optimization"],
        "game_versions": ["1.21"],
        "loaders": ["fabric"],
        "license": {"id": "MIT"},
        "published": "2021-01-03T00:00:00Z",
        "updated": "2024-05-01T00:00:00Z",
    }


def versions_json(project_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"v-{project_id}",
            "project_id": project_id,
            "name": "1.0.0",
            "version_number": "1.0.0",
            "version_type": "release",
            "game_versions": ["1.21"],
            "loaders": ["fabric"],
            "downloads": 500,
            "date_published": "2024-01-15T10:00:00Z",
        }
    ]


GAME_VERSIONS_JSON = [
    {"version": "1.21", "version_type": "release", "date": "2024-06-13T00:00:00Z", "major": True},
]


def mock_game_versions() -> respx.Route:
    return respx.get(f"{BASE_URL}/tag/game_version").mock(
        return_value=httpx.Response(200, json=GAME_VERSIONS_JSON)
    )


def mock_search(project_type: str, hits: list[dict[str, Any]]) -> respx.Route:
    facets = json.dumps([[f"project_type:{project_type}"]])
    return respx.get(f"{BASE_URL}/search", params={"facets": facets}).mock(
        return_value=httpx.Response(200, json=search_json(hits))
    )


def mock_project_endpoints(*project_ids: str, project_type: str = "mod") -> None:
    for project_id in project_ids:
        respx.get(f"{BASE_URL}/project/{project_id}").mock(
            return_value=httpx.Response(200, json=project_json(project_id, project_type))
        )
        respx.get(f"{BASE_URL}/project/{project_id}/version").mock(
            return_value=httpx.Response(200, json=versions_json(project_id))
        )


@respx.mock
def test_ingest_writes_projects_snapshots_and_versions(tmp_path: Path) -> None:
    mock_game_versions()
    mock_search("mod", [hit_json("aaa"), hit_json("bbb")])
    mock_search("modpack", [hit_json("ccc", "modpack")])
    mock_project_endpoints("aaa", "bbb")
    mock_project_endpoints("ccc", project_type="modpack")

    sleeps: list[float] = []
    with (
        ModrinthClient(sleep=sleeps.append) as client,
        Database.open(tmp_path / "test.db") as db,
    ):
        stats = ingest(client, db, limit=10, fetched_at=FETCHED_AT)
        project_ids = {row["id"] for row in db.conn.execute("SELECT id FROM projects")}
        fetched = [row["fetched_at"] for row in db.conn.execute("SELECT fetched_at FROM snapshots")]
        versions = db.conn.execute("SELECT COUNT(*) AS n FROM versions").fetchone()["n"]
        game_versions = db.conn.execute("SELECT COUNT(*) AS n FROM game_versions").fetchone()["n"]

    assert stats.projects == 3
    assert stats.snapshots == 3
    assert stats.versions == 3
    assert stats.game_versions == 1
    assert game_versions == 1
    assert project_ids == {"aaa", "bbb", "ccc"}
    assert fetched == [FETCHED_AT.isoformat()] * 3
    assert versions == 3


@respx.mock
def test_ingest_paginates_search_until_limit(tmp_path: Path) -> None:
    mock_game_versions()
    search_route = respx.get(f"{BASE_URL}/search")
    search_route.side_effect = [
        httpx.Response(200, json=search_json([hit_json("aaa"), hit_json("bbb")], total_hits=5)),
        httpx.Response(200, json=search_json([hit_json("ccc")], total_hits=5)),
    ]
    mock_project_endpoints("aaa", "bbb", "ccc")

    sleeps: list[float] = []
    with (
        ModrinthClient(sleep=sleeps.append) as client,
        Database.open(tmp_path / "test.db") as db,
    ):
        stats = ingest(
            client, db, limit=3, project_types=("mod",), fetched_at=FETCHED_AT, page_size=2
        )

    assert stats.projects == 3
    requested = [
        (call.request.url.params["offset"], call.request.url.params["limit"])
        for call in search_route.calls
    ]
    assert requested == [("0", "2"), ("2", "1")]


@respx.mock
def test_ingest_deduplicates_projects_across_types(tmp_path: Path) -> None:
    mock_game_versions()
    mock_search("mod", [hit_json("aaa")])
    mock_search("modpack", [hit_json("aaa")])
    mock_project_endpoints("aaa")

    sleeps: list[float] = []
    with (
        ModrinthClient(sleep=sleeps.append) as client,
        Database.open(tmp_path / "test.db") as db,
    ):
        stats = ingest(client, db, limit=10, fetched_at=FETCHED_AT)
        snapshots = db.conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]

    assert stats.projects == 1
    assert snapshots == 1


@respx.mock
def test_ingest_skips_projects_that_fail_to_fetch(tmp_path: Path) -> None:
    mock_game_versions()
    mock_search("mod", [hit_json("broken"), hit_json("bbb")])
    respx.get(f"{BASE_URL}/project/broken").mock(return_value=httpx.Response(404))
    mock_project_endpoints("bbb")

    sleeps: list[float] = []
    with (
        ModrinthClient(sleep=sleeps.append) as client,
        Database.open(tmp_path / "test.db") as db,
    ):
        stats = ingest(client, db, limit=10, project_types=("mod",), fetched_at=FETCHED_AT)
        project_ids = {row["id"] for row in db.conn.execute("SELECT id FROM projects")}

    assert stats.projects == 1
    assert project_ids == {"bbb"}


@respx.mock
def test_cli_ingest_creates_database(tmp_path: Path) -> None:
    mock_game_versions()
    respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=search_json([hit_json("aaa")]))
    )
    mock_project_endpoints("aaa")
    db_path = tmp_path / "data" / "modrinth.db"

    exit_code = main(["ingest", "--limit", "1", "--db", str(db_path)])

    assert exit_code == 0
    with Database.open(db_path) as db:
        snapshots = db.conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
    assert snapshots == 1

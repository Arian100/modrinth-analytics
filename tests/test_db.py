from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from modrinth_analytics.api import GameVersion, Project, Version
from modrinth_analytics.db import Database

FETCHED_AT = datetime(2026, 7, 3, 6, 0, tzinfo=UTC)


def test_open_creates_schema_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    Database.open(path).close()
    with Database.open(path) as database:
        rows = database.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = {row["name"] for row in rows}
    assert {"projects", "snapshots", "versions", "game_versions"} <= tables


def test_upsert_project_inserts_then_updates(
    db: Database, make_project: Callable[..., Project]
) -> None:
    db.upsert_project(make_project())
    db.upsert_project(make_project(title="Sodium Reloaded", loaders=["fabric", "quilt"]))

    rows = db.conn.execute("SELECT * FROM projects").fetchall()
    assert len(rows) == 1
    assert rows[0]["title"] == "Sodium Reloaded"
    assert json.loads(rows[0]["loaders"]) == ["fabric", "quilt"]
    assert rows[0]["license"] == "LGPL-3.0-only"


def test_snapshots_are_append_only(db: Database, make_project: Callable[..., Project]) -> None:
    db.upsert_project(make_project())
    db.insert_snapshot("AANobbMI", downloads=100, followers=5, fetched_at=FETCHED_AT)
    db.insert_snapshot(
        "AANobbMI", downloads=150, followers=6, fetched_at=FETCHED_AT + timedelta(days=1)
    )

    rows = db.conn.execute("SELECT downloads FROM snapshots ORDER BY fetched_at").fetchall()
    assert [row["downloads"] for row in rows] == [100, 150]


def test_snapshot_requires_known_project(db: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_snapshot("unknown", downloads=1, followers=1, fetched_at=FETCHED_AT)


def test_snapshot_timestamps_are_normalized_to_utc(
    db: Database, make_project: Callable[..., Project]
) -> None:
    db.upsert_project(make_project())
    berlin_time = datetime(2026, 7, 3, 8, 0, tzinfo=timezone(timedelta(hours=2)))
    db.insert_snapshot("AANobbMI", downloads=1, followers=1, fetched_at=berlin_time)

    row = db.conn.execute("SELECT fetched_at FROM snapshots").fetchone()
    assert row["fetched_at"] == "2026-07-03T06:00:00+00:00"


def test_naive_timestamps_are_rejected(db: Database) -> None:
    naive = datetime(2026, 7, 3)
    with pytest.raises(ValueError, match="timezone-aware"):
        db.insert_snapshot("AANobbMI", downloads=1, followers=1, fetched_at=naive)


def test_upsert_versions_is_idempotent(
    db: Database,
    make_project: Callable[..., Project],
    make_version: Callable[..., Version],
) -> None:
    db.upsert_project(make_project())
    assert db.upsert_versions([make_version()]) == 1
    db.upsert_versions([make_version(game_versions=["1.20.1", "1.20.4"])])

    rows = db.conn.execute("SELECT * FROM versions").fetchall()
    assert len(rows) == 1
    assert rows[0]["version"] == "mc1.20.1-0.5.8"
    assert json.loads(rows[0]["game_versions"]) == ["1.20.1", "1.20.4"]


def test_upsert_game_versions_is_idempotent(
    db: Database, make_game_version: Callable[..., GameVersion]
) -> None:
    assert db.upsert_game_versions([make_game_version()]) == 1
    db.upsert_game_versions([make_game_version(version_type="snapshot", major=False)])

    rows = db.conn.execute("SELECT * FROM game_versions").fetchall()
    assert len(rows) == 1
    assert rows[0]["version_type"] == "snapshot"
    assert rows[0]["release_date"] == "2024-06-13T00:00:00+00:00"
    assert rows[0]["major"] == 0


def test_read_df_returns_polars_frame(db: Database, make_project: Callable[..., Project]) -> None:
    db.upsert_project(make_project())
    frame = db.read_df("SELECT id, slug FROM projects")
    assert frame["slug"].to_list() == ["sodium"]

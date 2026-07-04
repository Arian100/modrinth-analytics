from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import polars as pl

from modrinth_analytics.api import GameVersion, Project, Version

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    project_type TEXT NOT NULL,
    categories TEXT NOT NULL DEFAULT '[]',
    loaders TEXT NOT NULL DEFAULT '[]',
    game_versions TEXT NOT NULL DEFAULT '[]',
    license TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    fetched_at TEXT NOT NULL,
    downloads INTEGER NOT NULL,
    followers INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_project_fetched
    ON snapshots (project_id, fetched_at);

CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    version TEXT NOT NULL,
    game_versions TEXT NOT NULL DEFAULT '[]',
    loaders TEXT NOT NULL DEFAULT '[]',
    date_published TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_project ON versions (project_id);

CREATE TABLE IF NOT EXISTS game_versions (
    version TEXT PRIMARY KEY,
    version_type TEXT NOT NULL,
    release_date TEXT NOT NULL,
    major INTEGER NOT NULL
);
"""


class Database:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @classmethod
    def open(cls, path: str | Path) -> Self:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA)
        return cls(conn)

    def upsert_project(self, project: Project) -> None:
        self.conn.execute(
            """
            INSERT INTO projects (id, slug, title, project_type, categories, loaders,
                                  game_versions, license)
            VALUES (:id, :slug, :title, :project_type, :categories, :loaders,
                    :game_versions, :license)
            ON CONFLICT (id) DO UPDATE SET
                slug = excluded.slug,
                title = excluded.title,
                project_type = excluded.project_type,
                categories = excluded.categories,
                loaders = excluded.loaders,
                game_versions = excluded.game_versions,
                license = excluded.license
            """,
            {
                "id": project.id,
                "slug": project.slug,
                "title": project.title,
                "project_type": project.project_type,
                "categories": json.dumps(project.categories),
                "loaders": json.dumps(project.loaders),
                "game_versions": json.dumps(project.game_versions),
                "license": project.license_id,
            },
        )
        self.conn.commit()

    def insert_snapshot(
        self,
        project_id: str,
        *,
        downloads: int,
        followers: int,
        fetched_at: datetime,
    ) -> None:
        self.conn.execute(
            "INSERT INTO snapshots (project_id, fetched_at, downloads, followers) "
            "VALUES (?, ?, ?, ?)",
            (project_id, _utc_iso(fetched_at), downloads, followers),
        )
        self.conn.commit()

    def upsert_versions(self, versions: Iterable[Version]) -> int:
        rows = [
            {
                "id": version.id,
                "project_id": version.project_id,
                "version": version.version_number,
                "game_versions": json.dumps(version.game_versions),
                "loaders": json.dumps(version.loaders),
                "date_published": _utc_iso(version.date_published),
            }
            for version in versions
        ]
        self.conn.executemany(
            """
            INSERT INTO versions (id, project_id, version, game_versions, loaders,
                                  date_published)
            VALUES (:id, :project_id, :version, :game_versions, :loaders, :date_published)
            ON CONFLICT (id) DO UPDATE SET
                version = excluded.version,
                game_versions = excluded.game_versions,
                loaders = excluded.loaders,
                date_published = excluded.date_published
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def upsert_game_versions(self, game_versions: Iterable[GameVersion]) -> int:
        rows = [
            {
                "version": game_version.version,
                "version_type": game_version.version_type,
                "release_date": _utc_iso(game_version.date),
                "major": int(game_version.major),
            }
            for game_version in game_versions
        ]
        self.conn.executemany(
            """
            INSERT INTO game_versions (version, version_type, release_date, major)
            VALUES (:version, :version_type, :release_date, :major)
            ON CONFLICT (version) DO UPDATE SET
                version_type = excluded.version_type,
                release_date = excluded.release_date,
                major = excluded.major
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def read_df(self, query: str) -> pl.DataFrame:
        cursor = self.conn.execute(query)
        cursor.row_factory = None
        columns = [description[0] for description in cursor.description]
        return pl.DataFrame(cursor.fetchall(), schema=columns, orient="row")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()

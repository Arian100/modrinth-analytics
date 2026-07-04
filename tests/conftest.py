from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from modrinth_analytics.api import GameVersion, Project, Version
from modrinth_analytics.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    with Database.open(tmp_path / "test.db") as database:
        yield database


@pytest.fixture
def make_project() -> Callable[..., Project]:

    def factory(**overrides: Any) -> Project:
        defaults: dict[str, Any] = {
            "id": "AANobbMI",
            "slug": "sodium",
            "title": "Sodium",
            "project_type": "mod",
            "downloads": 5_000_000,
            "followers": 12_000,
            "categories": ["optimization"],
            "game_versions": ["1.20.1", "1.21"],
            "loaders": ["fabric"],
            "license_id": "LGPL-3.0-only",
            "published": datetime(2021, 1, 3, tzinfo=UTC),
            "updated": datetime(2024, 5, 1, tzinfo=UTC),
        }
        return Project(**{**defaults, **overrides})

    return factory


@pytest.fixture
def make_version() -> Callable[..., Version]:

    def factory(**overrides: Any) -> Version:
        defaults: dict[str, Any] = {
            "id": "rAfhHfow",
            "project_id": "AANobbMI",
            "name": "Sodium 0.5.8",
            "version_number": "mc1.20.1-0.5.8",
            "version_type": "release",
            "game_versions": ["1.20.1"],
            "loaders": ["fabric"],
            "downloads": 100_000,
            "date_published": datetime(2024, 1, 15, 10, 0, tzinfo=UTC),
        }
        return Version(**{**defaults, **overrides})

    return factory


@pytest.fixture
def make_game_version() -> Callable[..., GameVersion]:

    def factory(**overrides: Any) -> GameVersion:
        defaults: dict[str, Any] = {
            "version": "1.21",
            "version_type": "release",
            "date": datetime(2024, 6, 13, tzinfo=UTC),
            "major": True,
        }
        return GameVersion(**{**defaults, **overrides})

    return factory


@pytest.fixture
def seed_database(
    make_project: Callable[..., Project],
    make_version: Callable[..., Version],
    make_game_version: Callable[..., GameVersion],
) -> Callable[[Path], None]:

    day1 = datetime(2026, 7, 1, 6, 0, tzinfo=UTC)
    day2 = datetime(2026, 7, 2, 6, 0, tzinfo=UTC)
    published = {
        "a": datetime(2024, 1, 1, tzinfo=UTC),
        "b": datetime(2024, 3, 1, tzinfo=UTC),
        "c": datetime(2024, 6, 20, tzinfo=UTC),
    }

    def seed(path: Path) -> None:
        with Database.open(path) as db:
            db.upsert_game_versions([make_game_version()])
            for count, (project_id, date_published) in enumerate(published.items(), start=1):
                downloads = count * 100
                db.upsert_project(
                    make_project(
                        id=project_id,
                        slug=project_id,
                        game_versions=[f"1.{i}" for i in range(count)],
                    )
                )
                db.insert_snapshot(
                    project_id, downloads=downloads, followers=downloads // 10, fetched_at=day1
                )
                db.insert_snapshot(
                    project_id, downloads=downloads * 2, followers=downloads // 5, fetched_at=day2
                )
                db.upsert_versions(
                    [
                        make_version(
                            id=f"v-{project_id}",
                            project_id=project_id,
                            game_versions=["1.21"],
                            date_published=date_published,
                        )
                    ]
                )

    return seed

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from modrinth_analytics.analysis import (
    adoption_curves,
    download_correlations,
    loader_share_over_time,
    project_features,
)
from modrinth_analytics.api import GameVersion, Project, Version
from modrinth_analytics.db import Database

DAY1 = datetime(2026, 7, 1, 6, 0, tzinfo=UTC)
DAY2 = datetime(2026, 7, 2, 6, 0, tzinfo=UTC)


def test_loader_share_over_time(db: Database, make_project: Callable[..., Project]) -> None:
    db.upsert_project(make_project(id="a", slug="a", loaders=["fabric"]))
    db.upsert_project(make_project(id="b", slug="b", loaders=["fabric", "forge"]))
    db.insert_snapshot("a", downloads=100, followers=1, fetched_at=DAY1)
    db.insert_snapshot("b", downloads=50, followers=1, fetched_at=DAY1)
    db.insert_snapshot("a", downloads=300, followers=1, fetched_at=DAY2)
    db.insert_snapshot("b", downloads=100, followers=1, fetched_at=DAY2)

    result = loader_share_over_time(db)

    day1_fabric = result.filter((pl.col("date") == DAY1.date()) & (pl.col("loader") == "fabric"))
    assert day1_fabric.row(0, named=True) == {
        "date": DAY1.date(),
        "loader": "fabric",
        "projects": 2,
        "downloads": 150,
        "download_share": 0.75,
    }
    day2_fabric = result.filter((pl.col("date") == DAY2.date()) & (pl.col("loader") == "fabric"))
    assert day2_fabric["downloads"].item() == 400
    assert day2_fabric["download_share"].item() == pytest.approx(0.8)


def test_loader_share_uses_latest_snapshot_per_day(
    db: Database, make_project: Callable[..., Project]
) -> None:
    db.upsert_project(make_project(id="a", slug="a", loaders=["fabric"]))
    db.insert_snapshot("a", downloads=100, followers=1, fetched_at=DAY1)
    db.insert_snapshot("a", downloads=120, followers=1, fetched_at=DAY1 + timedelta(hours=6))

    result = loader_share_over_time(db)

    assert result["downloads"].to_list() == [120]


def test_loader_share_on_empty_database(db: Database) -> None:
    result = loader_share_over_time(db)
    assert result.is_empty()
    assert result.columns == ["date", "loader", "projects", "downloads", "download_share"]


def test_adoption_curves(
    db: Database,
    make_project: Callable[..., Project],
    make_version: Callable[..., Version],
    make_game_version: Callable[..., GameVersion],
) -> None:
    db.upsert_game_versions(
        [
            make_game_version(version="1.21", date=datetime(2024, 6, 13, tzinfo=UTC)),
            make_game_version(
                version="24w14a",
                version_type="snapshot",
                date=datetime(2024, 4, 2, tzinfo=UTC),
                major=False,
            ),
        ]
    )
    for project_id in ("a", "b", "c"):
        db.upsert_project(make_project(id=project_id, slug=project_id))
    db.upsert_versions(
        [
            make_version(
                id="va1",
                project_id="a",
                game_versions=["1.21"],
                date_published=datetime(2024, 6, 20, tzinfo=UTC),
            ),
            make_version(
                id="va2",
                project_id="a",
                game_versions=["1.21"],
                date_published=datetime(2024, 7, 1, tzinfo=UTC),
            ),
            make_version(
                id="vb1",
                project_id="b",
                game_versions=["1.21", "24w14a"],
                date_published=datetime(2024, 6, 13, tzinfo=UTC),
            ),
        ]
    )

    result = adoption_curves(db)

    assert result["mc_version"].unique().to_list() == ["1.21"]
    assert result["project_id"].to_list() == ["b", "a"]
    assert result["days_to_support"].to_list() == [0, 7]
    assert result["projects_supporting"].to_list() == [1, 2]
    assert result["support_share"].to_list() == pytest.approx([1 / 3, 2 / 3])


def test_adoption_curves_on_empty_database(db: Database) -> None:
    result = adoption_curves(db)
    assert result.is_empty()
    assert "days_to_support" in result.columns


def test_project_features_derives_version_stats(
    db: Database,
    make_project: Callable[..., Project],
    make_version: Callable[..., Version],
) -> None:
    db.upsert_project(make_project(id="a", slug="a", categories=["x", "y"], loaders=["fabric"]))
    db.insert_snapshot("a", downloads=100, followers=10, fetched_at=DAY1)
    db.upsert_versions(
        [
            make_version(id="v1", project_id="a", date_published=datetime(2026, 3, 23, tzinfo=UTC)),
            make_version(id="v2", project_id="a", date_published=datetime(2026, 6, 21, tzinfo=UTC)),
        ]
    )

    row = project_features(db).row(0, named=True)

    assert row["n_categories"] == 2
    assert row["n_loaders"] == 1
    assert row["n_versions"] == 2
    assert row["age_days"] == 100
    assert row["days_since_update"] == 10
    assert row["versions_per_year"] == pytest.approx(2 * 365 / 100)


def test_project_features_uses_latest_snapshot(
    db: Database, make_project: Callable[..., Project]
) -> None:
    db.upsert_project(make_project(id="a", slug="a"))
    db.insert_snapshot("a", downloads=100, followers=10, fetched_at=DAY1)
    db.insert_snapshot("a", downloads=150, followers=12, fetched_at=DAY2)

    features = project_features(db)

    assert features.height == 1
    assert features["downloads"].item() == 150
    assert features["n_versions"].item() == 0


def test_project_features_on_empty_database(db: Database) -> None:
    features = project_features(db)
    assert features.is_empty()
    assert "versions_per_year" in features.columns


def test_download_correlations_find_monotonic_relation(
    db: Database, make_project: Callable[..., Project]
) -> None:
    specs = [("a", 1, 100), ("b", 2, 200), ("c", 3, 300), ("d", 4, 400)]
    for project_id, n_game_versions, downloads in specs:
        db.upsert_project(
            make_project(
                id=project_id,
                slug=project_id,
                game_versions=[f"1.{i}" for i in range(n_game_versions)],
            )
        )
        db.insert_snapshot(
            project_id, downloads=downloads, followers=downloads // 10, fetched_at=DAY1
        )

    result = download_correlations(db)

    row = result.filter(
        (pl.col("metric") == "downloads") & (pl.col("feature") == "n_game_versions")
    )
    assert row["spearman_r"].item() == pytest.approx(1.0)
    assert row["n_projects"].item() == 4


def test_download_correlations_with_insufficient_data(
    db: Database, make_project: Callable[..., Project]
) -> None:
    db.upsert_project(make_project(id="a", slug="a"))
    db.insert_snapshot("a", downloads=100, followers=10, fetched_at=DAY1)

    result = download_correlations(db)

    assert result["spearman_r"].null_count() == result.height

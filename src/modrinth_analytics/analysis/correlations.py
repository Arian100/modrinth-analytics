from __future__ import annotations

import polars as pl

from modrinth_analytics.db import Database

_LATEST_SNAPSHOT_QUERY = """
SELECT
    p.id AS project_id,
    p.slug,
    p.project_type,
    p.categories,
    p.loaders,
    p.game_versions,
    s.downloads,
    s.followers,
    s.fetched_at
FROM projects p
JOIN snapshots s ON s.project_id = p.id
WHERE s.fetched_at = (SELECT MAX(fetched_at) FROM snapshots WHERE project_id = p.id)
"""

_VERSION_STATS_QUERY = """
SELECT
    project_id,
    COUNT(*) AS n_versions,
    MIN(date_published) AS first_published,
    MAX(date_published) AS last_published
FROM versions
GROUP BY project_id
"""

_FEATURES = (
    "n_categories",
    "n_loaders",
    "n_game_versions",
    "n_versions",
    "age_days",
    "days_since_update",
    "versions_per_year",
)
_METRICS = ("downloads", "followers")

_FEATURES_SCHEMA = {
    "project_id": pl.String,
    "slug": pl.String,
    "project_type": pl.String,
    "downloads": pl.Int64,
    "followers": pl.Int64,
    "n_categories": pl.UInt32,
    "n_loaders": pl.UInt32,
    "n_game_versions": pl.UInt32,
    "n_versions": pl.Int64,
    "age_days": pl.Int64,
    "days_since_update": pl.Int64,
    "versions_per_year": pl.Float64,
}

_STATS_SCHEMA = {
    "project_id": pl.String,
    "n_versions": pl.Int64,
    "first_published": pl.String,
    "last_published": pl.String,
}


def project_features(db: Database) -> pl.DataFrame:
    latest = db.read_df(_LATEST_SNAPSHOT_QUERY)
    if latest.is_empty():
        return pl.DataFrame(schema=_FEATURES_SCHEMA)
    stats = db.read_df(_VERSION_STATS_QUERY)
    if stats.is_empty():
        stats = pl.DataFrame(schema=_STATS_SCHEMA)
    return (
        latest.unique(subset=["project_id"], keep="any")
        .join(stats, on="project_id", how="left")
        .with_columns(
            snapshot_date=pl.col("fetched_at").str.slice(0, 10).str.to_date(),
            first_published=pl.col("first_published").str.slice(0, 10).str.to_date(),
            last_published=pl.col("last_published").str.slice(0, 10).str.to_date(),
            n_versions=pl.col("n_versions").fill_null(0),
            n_categories=pl.col("categories").str.json_decode(pl.List(pl.String)).list.len(),
            n_loaders=pl.col("loaders").str.json_decode(pl.List(pl.String)).list.len(),
            n_game_versions=pl.col("game_versions").str.json_decode(pl.List(pl.String)).list.len(),
        )
        .with_columns(
            age_days=(pl.col("snapshot_date") - pl.col("first_published")).dt.total_days(),
            days_since_update=(pl.col("snapshot_date") - pl.col("last_published")).dt.total_days(),
        )
        .with_columns(
            versions_per_year=pl.col("n_versions") * 365.0 / pl.max_horizontal("age_days", 1)
        )
        .select(list(_FEATURES_SCHEMA))
    )


def download_correlations(db: Database) -> pl.DataFrame:
    features = project_features(db)
    rows: list[dict[str, object]] = []
    for metric in _METRICS:
        for feature in _FEATURES:
            pair = features.select(feature, metric).drop_nulls()
            coefficient = (
                pair.select(pl.corr(feature, metric, method="spearman")).item()
                if pair.height >= 3
                else None
            )
            rows.append(
                {
                    "metric": metric,
                    "feature": feature,
                    "spearman_r": coefficient,
                    "n_projects": pair.height,
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "metric": pl.String,
            "feature": pl.String,
            "spearman_r": pl.Float64,
            "n_projects": pl.Int64,
        },
    )

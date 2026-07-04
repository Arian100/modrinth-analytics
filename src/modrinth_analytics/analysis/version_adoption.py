from __future__ import annotations

import polars as pl

from modrinth_analytics.db import Database

_RELEASES_QUERY = """
SELECT version, release_date
FROM game_versions
WHERE version_type = 'release'
"""

_SUPPORT_QUERY = """
SELECT v.project_id, p.slug, v.date_published, v.game_versions
FROM versions v
JOIN projects p ON p.id = v.project_id
"""

_RESULT_SCHEMA = {
    "mc_version": pl.String,
    "release_date": pl.Date,
    "project_id": pl.String,
    "slug": pl.String,
    "first_support_at": pl.Date,
    "days_to_support": pl.Int64,
    "projects_supporting": pl.UInt32,
    "support_share": pl.Float64,
}


def adoption_curves(db: Database) -> pl.DataFrame:
    releases = db.read_df(_RELEASES_QUERY)
    support = db.read_df(_SUPPORT_QUERY)
    n_projects = db.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    if releases.is_empty() or support.is_empty() or n_projects == 0:
        return pl.DataFrame(schema=_RESULT_SCHEMA)

    releases = releases.rename({"version": "mc_version"}).with_columns(
        release_date=pl.col("release_date").str.slice(0, 10).str.to_date()
    )
    first_support = (
        support.with_columns(
            published=pl.col("date_published").str.slice(0, 10).str.to_date(),
            mc_version=pl.col("game_versions").str.json_decode(pl.List(pl.String)),
        )
        .explode("mc_version", empty_as_null=False)
        .drop_nulls("mc_version")
        .group_by(["mc_version", "project_id"])
        .agg(slug=pl.col("slug").first(), first_support_at=pl.col("published").min())
    )
    return (
        first_support.join(releases, on="mc_version", how="inner")
        .with_columns(
            days_to_support=(pl.col("first_support_at") - pl.col("release_date")).dt.total_days()
        )
        .sort(["release_date", "mc_version", "days_to_support", "first_support_at"])
        .with_columns(projects_supporting=pl.col("project_id").cum_count().over("mc_version"))
        .with_columns(support_share=pl.col("projects_supporting") / n_projects)
        .select(list(_RESULT_SCHEMA))
    )

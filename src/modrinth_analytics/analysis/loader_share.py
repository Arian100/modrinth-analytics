from __future__ import annotations

import polars as pl

from modrinth_analytics.db import Database

_QUERY = """
SELECT s.project_id, s.fetched_at, s.downloads, p.loaders
FROM snapshots s
JOIN projects p ON p.id = s.project_id
"""

_RESULT_SCHEMA = {
    "date": pl.Date,
    "loader": pl.String,
    "projects": pl.UInt32,
    "downloads": pl.Int64,
    "download_share": pl.Float64,
}


def loader_share_over_time(db: Database) -> pl.DataFrame:
    raw = db.read_df(_QUERY)
    if raw.is_empty():
        return pl.DataFrame(schema=_RESULT_SCHEMA)
    return (
        raw.sort("fetched_at")
        .with_columns(
            date=pl.col("fetched_at").str.slice(0, 10).str.to_date(),
            loaders=pl.col("loaders").str.json_decode(pl.List(pl.String)),
        )
        .group_by(["project_id", "date"], maintain_order=True)
        .agg(pl.col("downloads").last(), pl.col("loaders").last())
        .explode("loaders", empty_as_null=False)
        .rename({"loaders": "loader"})
        .drop_nulls("loader")
        .group_by(["date", "loader"])
        .agg(projects=pl.len(), downloads=pl.col("downloads").sum())
        .with_columns(download_share=pl.col("downloads") / pl.col("downloads").sum().over("date"))
        .sort(["date", "loader"])
    )

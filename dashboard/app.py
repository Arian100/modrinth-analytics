from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import streamlit as st

from modrinth_analytics import charts
from modrinth_analytics.analysis import (
    adoption_curves,
    download_correlations,
    loader_share_over_time,
    project_features,
)
from modrinth_analytics.db import Database

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "modrinth.db"


def _db_path() -> Path:
    override = os.environ.get("MODRINTH_DB")
    return Path(override) if override else _DEFAULT_DB


def require_data() -> str:
    path = _db_path()
    if not path.exists():
        st.warning(
            f"No database found at `{path}`. Run `python -m modrinth_analytics ingest` first."
        )
        st.stop()
    return str(path)


@st.cache_data(ttl=3600)
def load_loader_share(db_path: str) -> pl.DataFrame:
    with Database.open(db_path) as db:
        return loader_share_over_time(db)


@st.cache_data(ttl=3600)
def load_adoption(db_path: str) -> pl.DataFrame:
    with Database.open(db_path) as db:
        return adoption_curves(db)


@st.cache_data(ttl=3600)
def load_correlations(db_path: str) -> pl.DataFrame:
    with Database.open(db_path) as db:
        return download_correlations(db)


@st.cache_data(ttl=3600)
def load_features(db_path: str) -> pl.DataFrame:
    with Database.open(db_path) as db:
        return project_features(db)


def loader_share_page() -> None:
    st.title("Loader market share")
    data = load_loader_share(require_data())
    if data.is_empty():
        st.info("No snapshots yet — run the ingestion to collect data.")
        return

    dates = data["date"].unique().sort()
    latest = data.filter(pl.col("date") == dates[-1]).sort("download_share", descending=True)
    if len(dates) == 1:
        st.caption(
            "Only one snapshot day so far — the trend view appears once more days accumulate."
        )
    else:
        st.plotly_chart(charts.loader_share_area(data))

    col_share, col_projects = st.columns(2)
    with col_share:
        st.plotly_chart(charts.loader_download_share_bar(latest, dates[-1]))
    with col_projects:
        st.plotly_chart(charts.loader_projects_bar(latest, dates[-1]))
    st.caption("Multi-loader projects count towards each loader they support.")


def version_adoption_page() -> None:
    st.title("Minecraft version adoption")
    data = load_adoption(require_data())
    if data.is_empty():
        st.info("No version data yet — run the ingestion to collect data.")
        return

    releases = (
        data.select("mc_version", "release_date").unique().sort("release_date", descending=True)
    )
    selected = st.multiselect(
        "Minecraft releases",
        releases["mc_version"].to_list(),
        default=releases["mc_version"].head(5).to_list(),
    )
    if not selected:
        st.info("Select at least one release.")
        return

    st.plotly_chart(charts.adoption_lines(data.filter(pl.col("mc_version").is_in(selected))))
    st.caption(
        "Negative day values are real: support was published for snapshots or "
        "pre-releases before the official release date."
    )


def success_factors_page() -> None:
    st.title("Success factors")
    db_path = require_data()
    correlations = load_correlations(db_path)
    valid = correlations.filter(
        pl.col("spearman_r").is_not_null() & pl.col("spearman_r").is_not_nan()
    )
    if valid.is_empty():
        st.info("Not enough data for correlations yet — they need at least three projects.")
        return

    metric = st.radio("Popularity metric", ("downloads", "followers"), horizontal=True)
    st.plotly_chart(charts.correlation_bars(valid, metric))
    st.caption("Descriptive, not causal — project age in particular confounds lifetime totals.")

    features = load_features(db_path)
    skipped = ("project_id", "slug", "project_type", "downloads", "followers")
    feature = st.selectbox(
        "Explore a feature against downloads",
        [column for column in features.columns if column not in skipped],
    )
    st.plotly_chart(charts.downloads_scatter(features, feature))


def main() -> None:
    st.set_page_config(page_title="Modrinth Analytics", page_icon="📊", layout="wide")
    st.navigation(
        [
            st.Page(loader_share_page, title="Loader market share", icon="🧩", default=True),
            st.Page(version_adoption_page, title="Version adoption", icon="🚀"),
            st.Page(success_factors_page, title="Success factors", icon="📈"),
        ]
    ).run()


if __name__ == "__main__":
    main()

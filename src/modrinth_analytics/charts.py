from __future__ import annotations

from datetime import date

import plotly.express as px
import plotly.graph_objects as go
import polars as pl


def loader_share_area(data: pl.DataFrame) -> go.Figure:
    return px.area(
        data,
        x="date",
        y="download_share",
        color="loader",
        labels={"download_share": "share of downloads"},
        title="Share of loader-attributed downloads over time",
    )


def loader_download_share_bar(latest: pl.DataFrame, snapshot_date: date) -> go.Figure:
    return px.bar(
        latest,
        x="loader",
        y="download_share",
        labels={"download_share": "share of downloads"},
        title=f"Download share ({snapshot_date})",
    )


def loader_projects_bar(latest: pl.DataFrame, snapshot_date: date) -> go.Figure:
    return px.bar(latest, x="loader", y="projects", title=f"Projects per loader ({snapshot_date})")


def adoption_lines(data: pl.DataFrame) -> go.Figure:
    return px.line(
        data,
        x="days_to_support",
        y="support_share",
        color="mc_version",
        line_shape="hv",
        hover_name="slug",
        labels={
            "days_to_support": "days since release",
            "support_share": "share of tracked projects",
        },
        title="Cumulative share of projects supporting a release",
    )


def correlation_bars(correlations: pl.DataFrame, metric: str) -> go.Figure:
    return px.bar(
        correlations.filter(pl.col("metric") == metric),
        x="feature",
        y="spearman_r",
        range_y=[-1, 1],
        labels={"spearman_r": "Spearman correlation"},
        title=f"Feature correlation with {metric}",
    )


def downloads_scatter(features: pl.DataFrame, feature: str) -> go.Figure:
    return px.scatter(
        features,
        x=feature,
        y="downloads",
        log_y=True,
        color="project_type",
        hover_name="slug",
        title=f"{feature} vs downloads (log scale)",
    )

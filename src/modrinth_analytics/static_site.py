from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

import plotly.graph_objects as go
import polars as pl
from plotly.offline import get_plotlyjs_version

from modrinth_analytics import charts
from modrinth_analytics.analysis import (
    adoption_curves,
    download_correlations,
    loader_share_over_time,
    project_features,
)
from modrinth_analytics.db import Database

logger = logging.getLogger(__name__)

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Modrinth Ecosystem Analytics</title>
<script src="https://cdn.plot.ly/plotly-{plotlyjs_version}.min.js"></script>
<style>
body {{
  font-family: system-ui, sans-serif;
  margin: 0 auto;
  max-width: 1100px;
  padding: 0 1.5rem 3rem;
  color: #1f2933;
}}
header {{ padding: 2rem 0 0.5rem; }}
h1 {{ margin-bottom: 0.25rem; }}
section {{ margin-top: 2.5rem; }}
.status, .note, footer {{ color: #616e7c; font-size: 0.9rem; }}
footer {{ margin-top: 3rem; border-top: 1px solid #d3dce6; padding-top: 1rem; }}
</style>
</head>
<body>
<header>
<h1>Modrinth Ecosystem Analytics</h1>
<p class="status">{status}</p>
</header>
{sections}
<footer>
<p>Data: public <a href="https://docs.modrinth.com/api/">Modrinth API</a> —
not affiliated with Modrinth. Generated {generated} ·
<a href="https://github.com/Arian100/modrinth-analytics">Source on GitHub</a></p>
</footer>
</body>
</html>
"""


def run(args: argparse.Namespace) -> int:
    target = build_site(args.db, args.out)
    logger.info("Wrote %s", target)
    return 0


def build_site(db_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "index.html"

    if not db_path.exists():
        status = "No data yet — the first ingestion has not run."
        sections = ""
    else:
        with Database.open(db_path) as db:
            status = _status_line(db)
            sections = "\n".join([_loader_section(db), _adoption_section(db), _success_section(db)])

    target.write_text(
        _PAGE.format(
            plotlyjs_version=get_plotlyjs_version(),
            status=status,
            sections=sections,
            generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        ),
        encoding="utf-8",
    )
    return target


def _status_line(db: Database) -> str:
    projects = db.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    snapshots = db.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    latest = db.conn.execute("SELECT MAX(fetched_at) FROM snapshots").fetchone()[0]
    freshness = f", last snapshot {latest[:10]}" if latest else ""
    return f"{projects} tracked projects, {snapshots} snapshots{freshness}."


def _loader_section(db: Database) -> str:
    data = loader_share_over_time(db)
    if data.is_empty():
        return _section("Loader market share", "<p class='note'>No snapshots yet.</p>")
    dates = data["date"].unique().sort()
    latest = data.filter(pl.col("date") == dates[-1]).sort("download_share", descending=True)
    parts = []
    if len(dates) > 1:
        parts.append(_figure(charts.loader_share_area(data)))
    parts.append(_figure(charts.loader_download_share_bar(latest, dates[-1])))
    parts.append(_figure(charts.loader_projects_bar(latest, dates[-1])))
    parts.append(
        "<p class='note'>Multi-loader projects count towards each loader they support.</p>"
    )
    return _section("Loader market share", "\n".join(parts))


def _adoption_section(db: Database) -> str:
    data = adoption_curves(db)
    if data.is_empty():
        return _section("Minecraft version adoption", "<p class='note'>No version data yet.</p>")
    recent = (
        data.select("mc_version", "release_date")
        .unique()
        .sort("release_date", descending=True)["mc_version"]
        .head(5)
        .to_list()
    )
    body = "\n".join(
        [
            _figure(charts.adoption_lines(data.filter(pl.col("mc_version").is_in(recent)))),
            "<p class='note'>Five most recent releases. Negative day values mean support "
            "was published before the official release date.</p>",
        ]
    )
    return _section("Minecraft version adoption", body)


def _success_section(db: Database) -> str:
    correlations = download_correlations(db)
    valid = correlations.filter(
        pl.col("spearman_r").is_not_null() & pl.col("spearman_r").is_not_nan()
    )
    if valid.is_empty():
        return _section(
            "Success factors",
            "<p class='note'>Not enough data yet — correlations need at least three projects.</p>",
        )
    parts = [
        _figure(charts.correlation_bars(valid, metric)) for metric in ("downloads", "followers")
    ]
    parts.append(
        "<p class='note'>Spearman rank correlation — descriptive, not causal; project age "
        "in particular confounds lifetime totals.</p>"
    )
    parts.append(_figure(charts.downloads_scatter(project_features(db), "age_days")))
    return _section("Success factors", "\n".join(parts))


def _section(title: str, body: str) -> str:
    return f"<section>\n<h2>{title}</h2>\n{body}\n</section>"


def _figure(fig: go.Figure) -> str:
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from modrinth_analytics.api import ModrinthAPIError, ModrinthClient, SearchHit
from modrinth_analytics.db import Database

PAGE_SIZE = 100
PROJECT_TYPES: tuple[str, ...] = ("mod", "modpack")

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:

    projects: int = 0
    snapshots: int = 0
    versions: int = 0
    game_versions: int = 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="number of top projects to ingest per project type (default: 500)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/modrinth.db"),
        help="path to the SQLite database (default: data/modrinth.db)",
    )


def run(args: argparse.Namespace) -> int:
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with ModrinthClient() as client, Database.open(args.db) as db:
        stats = ingest(client, db, limit=args.limit)
    logger.info(
        "Finished: %d projects, %d snapshots, %d version rows, %d game versions",
        stats.projects,
        stats.snapshots,
        stats.versions,
        stats.game_versions,
    )
    return 0


def ingest(
    client: ModrinthClient,
    db: Database,
    *,
    limit: int,
    project_types: Sequence[str] = PROJECT_TYPES,
    fetched_at: datetime | None = None,
    page_size: int = PAGE_SIZE,
) -> IngestStats:

    timestamp = fetched_at if fetched_at is not None else datetime.now(UTC)
    stats = IngestStats()
    try:
        stats.game_versions = db.upsert_game_versions(client.get_game_versions())
    except ModrinthAPIError:
        logger.exception("Could not refresh game versions; keeping existing rows")
    seen: set[str] = set()
    for project_type in project_types:
        for hit in _iter_top_hits(client, project_type, limit, page_size):
            if hit.project_id in seen:
                continue
            seen.add(hit.project_id)
            try:
                _ingest_project(client, db, hit.project_id, timestamp, stats)
            except ModrinthAPIError:
                logger.exception("Skipping %s after API error", hit.slug)
    return stats


def _ingest_project(
    client: ModrinthClient,
    db: Database,
    project_id: str,
    fetched_at: datetime,
    stats: IngestStats,
) -> None:
    project = client.get_project(project_id)
    db.upsert_project(project)
    stats.projects += 1
    db.insert_snapshot(
        project.id,
        downloads=project.downloads,
        followers=project.followers,
        fetched_at=fetched_at,
    )
    stats.snapshots += 1
    stats.versions += db.upsert_versions(client.get_project_versions(project_id))
    logger.info("Ingested %s (%s)", project.slug, project.project_type)


def _iter_top_hits(
    client: ModrinthClient, project_type: str, limit: int, page_size: int
) -> Iterator[SearchHit]:
    fetched = 0
    while fetched < limit:
        page = client.search(
            facets=[[f"project_type:{project_type}"]],
            index="downloads",
            limit=min(page_size, limit - fetched),
            offset=fetched,
        )
        if not page.hits:
            return
        yield from page.hits
        fetched += len(page.hits)
        if fetched >= page.total_hits:
            return

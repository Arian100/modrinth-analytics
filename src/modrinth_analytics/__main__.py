from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from modrinth_analytics import ingest


def _run_build_site(args: argparse.Namespace) -> int:
    try:
        from modrinth_analytics import static_site
    except ModuleNotFoundError as exc:
        raise SystemExit(
            'build-site needs the dashboard extra: pip install -e ".[dashboard]"'
        ) from exc
    return static_site.run(args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m modrinth_analytics",
        description="Modrinth ecosystem analytics pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser(
        "ingest", help="snapshot the top Modrinth projects into SQLite"
    )
    ingest.add_arguments(ingest_parser)
    ingest_parser.set_defaults(run=ingest.run)

    site_parser = subparsers.add_parser(
        "build-site", help="export the static HTML dashboard (requires the dashboard extra)"
    )
    site_parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/modrinth.db"),
        help="path to the SQLite database (default: data/modrinth.db)",
    )
    site_parser.add_argument(
        "--out",
        type=Path,
        default=Path("site"),
        help="output directory for the generated site (default: site)",
    )
    site_parser.set_defaults(run=_run_build_site)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())

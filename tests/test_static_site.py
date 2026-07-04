from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from modrinth_analytics.__main__ import main
from modrinth_analytics.static_site import build_site


def test_build_site_writes_index_with_charts(
    tmp_path: Path, seed_database: Callable[[Path], None]
) -> None:
    db_path = tmp_path / "modrinth.db"
    seed_database(db_path)

    target = build_site(db_path, tmp_path / "site")
    html = target.read_text(encoding="utf-8")

    assert target.name == "index.html"
    assert "cdn.plot.ly" in html
    assert "Loader market share" in html
    assert "Minecraft version adoption" in html
    assert "Success factors" in html
    assert "fabric" in html
    assert "1.21" in html
    assert "3 tracked projects, 6 snapshots" in html


def test_build_site_without_database_writes_placeholder(tmp_path: Path) -> None:
    target = build_site(tmp_path / "missing.db", tmp_path / "site")
    html = target.read_text(encoding="utf-8")
    assert "No data yet" in html


def test_cli_build_site(tmp_path: Path, seed_database: Callable[[Path], None]) -> None:
    db_path = tmp_path / "modrinth.db"
    seed_database(db_path)
    out = tmp_path / "site"

    exit_code = main(["build-site", "--db", str(db_path), "--out", str(out)])

    assert exit_code == 0
    assert (out / "index.html").exists()

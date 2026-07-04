from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_APP_PATH = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"


def _page_script(app_path: str, page_name: str) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("dashboard_app", app_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    getattr(module, page_name)()


def _run_page(page_name: str) -> AppTest:
    app_test = AppTest.from_function(_page_script, args=(str(_APP_PATH), page_name))
    app_test.run(timeout=30)
    return app_test


@pytest.fixture
def seeded_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seed_database: Callable[[Path], None]
) -> Path:
    path = tmp_path / "dashboard.db"
    seed_database(path)
    monkeypatch.setenv("MODRINTH_DB", str(path))
    return path


def test_loader_share_page_renders(seeded_db: Path) -> None:
    result = _run_page("loader_share_page")
    assert not result.exception


def test_version_adoption_page_renders(seeded_db: Path) -> None:
    result = _run_page("version_adoption_page")
    assert not result.exception


def test_success_factors_page_renders(seeded_db: Path) -> None:
    result = _run_page("success_factors_page")
    assert not result.exception


def test_pages_warn_without_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODRINTH_DB", str(tmp_path / "missing.db"))
    result = _run_page("loader_share_page")
    assert not result.exception
    assert len(result.warning) == 1

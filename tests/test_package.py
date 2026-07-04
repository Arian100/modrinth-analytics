from __future__ import annotations

import modrinth_analytics


def test_version() -> None:
    assert modrinth_analytics.__version__ == "0.1.0"

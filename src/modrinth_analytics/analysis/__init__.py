from __future__ import annotations

from modrinth_analytics.analysis.correlations import download_correlations, project_features
from modrinth_analytics.analysis.loader_share import loader_share_over_time
from modrinth_analytics.analysis.version_adoption import adoption_curves

__all__ = [
    "adoption_curves",
    "download_correlations",
    "loader_share_over_time",
    "project_features",
]

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self

import httpx

BASE_URL = "https://api.modrinth.com/v2"
USER_AGENT = "Arian100/modrinth-analytics"

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 30.0


class ModrinthAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class SearchHit:
    project_id: str
    slug: str
    title: str
    project_type: str
    downloads: int
    follows: int
    categories: list[str]
    game_versions: list[str]
    date_created: datetime
    date_modified: datetime
    license: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls(
            project_id=data["project_id"],
            slug=data["slug"],
            title=data["title"],
            project_type=data["project_type"],
            downloads=data["downloads"],
            follows=data["follows"],
            categories=list(data.get("categories") or []),
            game_versions=list(data.get("versions") or []),
            date_created=datetime.fromisoformat(data["date_created"]),
            date_modified=datetime.fromisoformat(data["date_modified"]),
            license=data.get("license") or "",
        )


@dataclass(frozen=True, slots=True)
class SearchResponse:
    hits: list[SearchHit]
    offset: int
    limit: int
    total_hits: int

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls(
            hits=[SearchHit.from_json(hit) for hit in data["hits"]],
            offset=data["offset"],
            limit=data["limit"],
            total_hits=data["total_hits"],
        )


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    slug: str
    title: str
    project_type: str
    downloads: int
    followers: int
    categories: list[str]
    game_versions: list[str]
    loaders: list[str]
    license_id: str | None
    published: datetime
    updated: datetime

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        license_data = data.get("license")
        return cls(
            id=data["id"],
            slug=data["slug"],
            title=data["title"],
            project_type=data["project_type"],
            downloads=data["downloads"],
            followers=data["followers"],
            categories=list(data.get("categories") or []),
            game_versions=list(data.get("game_versions") or []),
            loaders=list(data.get("loaders") or []),
            license_id=license_data["id"] if license_data else None,
            published=datetime.fromisoformat(data["published"]),
            updated=datetime.fromisoformat(data["updated"]),
        )


@dataclass(frozen=True, slots=True)
class Version:
    id: str
    project_id: str
    name: str
    version_number: str
    version_type: str
    game_versions: list[str]
    loaders: list[str]
    downloads: int
    date_published: datetime

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls(
            id=data["id"],
            project_id=data["project_id"],
            name=data.get("name") or "",
            version_number=data["version_number"],
            version_type=data["version_type"],
            game_versions=list(data.get("game_versions") or []),
            loaders=list(data.get("loaders") or []),
            downloads=data["downloads"],
            date_published=datetime.fromisoformat(data["date_published"]),
        )


@dataclass(frozen=True, slots=True)
class GameVersion:
    version: str
    version_type: str
    date: datetime
    major: bool

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        return cls(
            version=data["version"],
            version_type=data["version_type"],
            date=datetime.fromisoformat(data["date"]),
            major=data["major"],
        )


class ModrinthClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        user_agent: str = USER_AGENT,
        requests_per_minute: int = 240,
        max_retries: int = 3,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = 60.0 / requests_per_minute
        self._max_retries = max_retries
        self._sleep = sleep
        self._last_request_at = 0.0
        self._client = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": user_agent},
            timeout=timeout,
        )

    def search(
        self,
        *,
        query: str | None = None,
        facets: Sequence[Sequence[str]] | None = None,
        index: str = "downloads",
        limit: int = 100,
        offset: int = 0,
    ) -> SearchResponse:

        params: dict[str, Any] = {"index": index, "limit": limit, "offset": offset}
        if query is not None:
            params["query"] = query
        if facets is not None:
            params["facets"] = json.dumps([list(group) for group in facets])
        return SearchResponse.from_json(self._request("/search", params=params))

    def get_project(self, id_or_slug: str) -> Project:
        return Project.from_json(self._request(f"/project/{id_or_slug}"))

    def get_project_versions(self, id_or_slug: str) -> list[Version]:
        data = self._request(f"/project/{id_or_slug}/version")
        return [Version.from_json(item) for item in data]

    def get_game_versions(self) -> list[GameVersion]:
        return [GameVersion.from_json(item) for item in self._request("/tag/game_version")]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error = ""
        last_status: int | None = None
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                response = self._client.get(path, params=params)
            except httpx.TransportError as exc:
                last_error, last_status = str(exc), None
                if attempt < self._max_retries:
                    self._sleep(_backoff(attempt))
                continue
            if response.status_code in _RETRYABLE_STATUS_CODES:
                last_error, last_status = f"HTTP {response.status_code}", response.status_code
                if attempt < self._max_retries:
                    self._sleep(self._retry_delay(response, attempt))
                continue
            if response.is_error:
                raise ModrinthAPIError(
                    f"GET {path} failed with HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            self._pause_if_exhausted(response)
            return response.json()
        raise ModrinthAPIError(
            f"GET {path} still failing after {self._max_retries + 1} attempts: {last_error}",
            status_code=last_status,
        )

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            self._sleep(wait)
        self._last_request_at = time.monotonic()

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        reset = _int_header(response, "X-Ratelimit-Reset")
        if response.status_code == 429 and reset is not None:
            return max(float(reset), 1.0)
        return _backoff(attempt)

    def _pause_if_exhausted(self, response: httpx.Response) -> None:
        remaining = _int_header(response, "X-Ratelimit-Remaining")
        reset = _int_header(response, "X-Ratelimit-Reset")
        if remaining is not None and remaining <= 0 and reset is not None and reset > 0:
            self._sleep(float(reset))


def _backoff(attempt: int) -> float:
    return min(2.0**attempt, _MAX_BACKOFF_SECONDS)


def _int_header(response: httpx.Response, name: str) -> int | None:
    value = response.headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None

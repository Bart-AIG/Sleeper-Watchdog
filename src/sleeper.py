"""Read-only client for the public Sleeper API.

No auth, no writes. Methods return raw JSON dicts/lists as Sleeper sends them.
The players catalog is cached on disk because it is ~10MB.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

BASE_URL = "https://api.sleeper.app/v1"
PLAYER_CACHE_TTL_SEC = 24 * 60 * 60


class SleeperClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        player_cache_path: Path | None = None,
    ) -> None:
        self._client = client or httpx.Client(timeout=15.0, base_url=BASE_URL)
        self._owns_client = client is None
        self._player_cache_path = player_cache_path or Path("data/players.json")

    def __enter__(self) -> SleeperClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._owns_client:
            self._client.close()

    def _get(self, path: str) -> Any:
        response = self._client.get(path)
        response.raise_for_status()
        return response.json()

    def get_nfl_state(self) -> dict[str, Any]:
        return self._get("/state/nfl")

    def get_league(self, league_id: str) -> dict[str, Any]:
        return self._get(f"/league/{league_id}")

    def get_users(self, league_id: str) -> list[dict[str, Any]]:
        return self._get(f"/league/{league_id}/users")

    def get_rosters(self, league_id: str) -> list[dict[str, Any]]:
        return self._get(f"/league/{league_id}/rosters")

    def get_transactions(self, league_id: str, week: int) -> list[dict[str, Any]]:
        return self._get(f"/league/{league_id}/transactions/{week}")

    def get_traded_picks(self, league_id: str) -> list[dict[str, Any]]:
        return self._get(f"/league/{league_id}/traded_picks")

    def get_drafts(self, league_id: str) -> list[dict[str, Any]]:
        return self._get(f"/league/{league_id}/drafts")

    def get_draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
        return self._get(f"/draft/{draft_id}/picks")

    def get_players(self) -> dict[str, dict[str, Any]]:
        """Return a slim {player_id: {name, team, position}} map, cached 24h on disk."""
        if self._cache_is_fresh():
            log.info("players.cache.hit", path=str(self._player_cache_path))
            with self._player_cache_path.open(encoding="utf-8") as f:
                return json.load(f)

        log.info("players.cache.miss", path=str(self._player_cache_path))
        raw = self._get("/players/nfl")
        slim = {
            pid: {
                "name": _player_name(p),
                "team": p.get("team"),
                "position": p.get("position"),
            }
            for pid, p in raw.items()
        }
        self._player_cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._player_cache_path.open("w", encoding="utf-8") as f:
            json.dump(slim, f, indent=0, sort_keys=True)
        return slim

    def _cache_is_fresh(self) -> bool:
        if not self._player_cache_path.exists():
            return False
        age = time.time() - self._player_cache_path.stat().st_mtime
        return age < PLAYER_CACHE_TTL_SEC


def _player_name(p: dict[str, Any]) -> str:
    full = p.get("full_name")
    if full:
        return full
    first = p.get("first_name") or ""
    last = p.get("last_name") or ""
    combined = f"{first} {last}".strip()
    return combined or p.get("player_id") or "Unknown"


def effective_transaction_week(nfl_state: dict[str, Any]) -> int:
    """During offseason/preseason the NFL week is 0 but transactions are bucketed at week 1."""
    return max(int(nfl_state.get("week", 0)), 1)

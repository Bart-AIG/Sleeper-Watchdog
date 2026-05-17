"""FantasyCalc value lookup.

Public API, no auth required. We fetch the dynasty-SF 12-team values once per
day and cache to `data/fantasycalc.json` (committed to the repo for
reproducibility). Players are keyed by Sleeper player id; draft picks are
estimated by season + round using the median pick of that round.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from statistics import median
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

VALUES_URL = "https://api.fantasycalc.com/values/current"
CACHE_TTL_SEC = 24 * 60 * 60
PICK_NAME_RE = re.compile(r"^(\d{4})\s+Pick\s+(\d+)\.(\d+)$")


class FantasyCalcClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        cache_path: Path | None = None,
        is_dynasty: bool = True,
        num_qbs: int = 2,
        num_teams: int = 12,
        ppr: float = 1.0,
    ) -> None:
        self._client = client or httpx.Client(timeout=15.0)
        self._owns_client = client is None
        self._cache_path = cache_path or Path("data/fantasycalc.json")
        self._params = {
            "isDynasty": str(is_dynasty).lower(),
            "numQbs": str(num_qbs),
            "numTeams": str(num_teams),
            "ppr": str(ppr),
        }
        self._values: dict[str, int] | None = None
        self._pick_round_medians: dict[tuple[str, int], int] | None = None

    def __enter__(self) -> FantasyCalcClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._owns_client:
            self._client.close()

    def _load(self) -> dict[str, Any]:
        if self._cache_is_fresh():
            log.info("fantasycalc.cache.hit", path=str(self._cache_path))
            with self._cache_path.open(encoding="utf-8") as f:
                return json.load(f)

        log.info("fantasycalc.cache.miss", path=str(self._cache_path))
        response = self._client.get(VALUES_URL, params=self._params)
        response.raise_for_status()
        raw = response.json()
        slim = {"params": self._params, "values_by_sleeper_id": {}, "pick_round_medians": {}}

        picks_by_round: dict[tuple[str, int], list[int]] = {}
        for entry in raw:
            player = entry.get("player") or {}
            value = int(entry.get("value", 0))
            sleeper_id = player.get("sleeperId")
            if sleeper_id:
                slim["values_by_sleeper_id"][str(sleeper_id)] = value
            if player.get("position") == "PICK":
                m = PICK_NAME_RE.match(player.get("name", ""))
                if m:
                    season, round_no, _slot = m.group(1), int(m.group(2)), int(m.group(3))
                    picks_by_round.setdefault((season, round_no), []).append(value)

        slim["pick_round_medians"] = {
            f"{season}:{round_no}": int(median(vals))
            for (season, round_no), vals in picks_by_round.items()
        }

        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._cache_path.open("w", encoding="utf-8") as f:
            json.dump(slim, f, indent=0, sort_keys=True)
        return slim

    def _cache_is_fresh(self) -> bool:
        if not self._cache_path.exists():
            return False
        age = time.time() - self._cache_path.stat().st_mtime
        return age < CACHE_TTL_SEC

    def player_value(self, sleeper_id: str | None) -> int:
        if not sleeper_id:
            return 0
        if self._values is None:
            data = self._load()
            self._values = data["values_by_sleeper_id"]
            self._pick_round_medians = {
                tuple(k.split(":")): v for k, v in data["pick_round_medians"].items()
            }
        return int(self._values.get(str(sleeper_id), 0))

    def pick_value(self, season: str | int, round_no: int) -> int:
        if self._pick_round_medians is None:
            self.player_value(None)  # force load
        assert self._pick_round_medians is not None
        return int(self._pick_round_medians.get((str(season), int(round_no)), 0))


def grade_trade(
    transaction: dict[str, Any], values: "ValueLookup"
) -> dict[int, dict[str, Any]]:
    """Compute per-roster value sent vs received for one completed trade.

    Returns {roster_id: {"sent": int, "received": int, "net": int}}.
    """
    roster_ids = [int(r) for r in (transaction.get("roster_ids") or [])]
    totals = {rid: {"sent": 0, "received": 0} for rid in roster_ids}

    for player_id, roster_id in (transaction.get("adds") or {}).items():
        v = values.player_value(player_id)
        rid = int(roster_id)
        if rid in totals:
            totals[rid]["received"] += v

    for player_id, roster_id in (transaction.get("drops") or {}).items():
        v = values.player_value(player_id)
        rid = int(roster_id)
        if rid in totals:
            totals[rid]["sent"] += v

    for pick in transaction.get("draft_picks") or []:
        season = pick.get("season")
        round_no = pick.get("round")
        if season is None or round_no is None:
            continue
        v = values.pick_value(season, round_no)
        new_owner = int(pick.get("owner_id", 0))
        prev_owner = int(pick.get("previous_owner_id", 0))
        if new_owner in totals:
            totals[new_owner]["received"] += v
        if prev_owner in totals:
            totals[prev_owner]["sent"] += v

    return {rid: {**t, "net": t["received"] - t["sent"]} for rid, t in totals.items()}


def trade_imbalance_percent(grades: dict[int, dict[str, Any]]) -> float:
    """Largest |net| divided by half the total value exchanged, as a percent.

    0% means perfectly even. 100% means one side received everything for nothing.
    """
    total_moved = sum(g["sent"] for g in grades.values())
    if total_moved == 0:
        return 0.0
    half = total_moved
    max_abs_net = max(abs(g["net"]) for g in grades.values())
    return round((max_abs_net / half) * 100, 1)


def letter_grade(percent_received_vs_sent: float) -> str:
    """Letter grade given (received - sent) / sent as a signed percentage.

    Positive => you received more than you gave (good for you).
    """
    if percent_received_vs_sent >= 15:
        return "A"
    if percent_received_vs_sent >= 5:
        return "B"
    if percent_received_vs_sent >= -5:
        return "C"
    if percent_received_vs_sent >= -15:
        return "D"
    return "F"


class ValueLookup:
    """Anything with .player_value(sleeper_id) and .pick_value(season, round).

    Production: FantasyCalcClient. Tests inject a stub with hardcoded values.
    """

    def player_value(self, sleeper_id: str | None) -> int: ...
    def pick_value(self, season: str | int, round_no: int) -> int: ...

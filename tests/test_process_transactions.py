"""process_transactions end to end with stubbed Sleeper, Discord, and values."""

from __future__ import annotations

from typing import Any

import structlog

from src.main import fetch_recent_transactions, process_transactions
from src.state import LeagueState


class _Sleeper:
    def get_players(self) -> dict[str, dict[str, Any]]:
        return {}


class _Notifier:
    def __init__(self) -> None:
        self.posted: list[dict[str, Any]] = []

    def post(self, embed: dict[str, Any]) -> None:
        self.posted.append(embed)


class _Lookup:
    def get(self) -> dict[int, str]:
        return {1: "Team A", 2: "Team B"}


class _Values:
    """Knows only player 'known'; everything else is unvalued."""

    def player_value(self, sleeper_id: str | None) -> int:
        return 5000 if sleeper_id == "known" else 0

    def pick_value(self, season: str | int, round_no: int) -> int:
        return 0


def _trade(tx_id: str, other: str) -> dict[str, Any]:
    return {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "roster_ids": [1, 2],
        "adds": {"known": 1, other: 2},
        "drops": {"known": 2, other: 1},
    }


def _run(txs: list[dict[str, Any]], state: LeagueState, notifier: _Notifier) -> int:
    return process_transactions(
        {"id": "L1", "name": "Test"},
        state,
        _Sleeper(),
        notifier,
        _Lookup(),
        txs,
        _Values(),
        structlog.get_logger("test"),
    )


def test_ungradable_trade_still_posts() -> None:
    # A trade with an asset FantasyCalc has no value for used to crash every
    # run until the NFL week rolled over (Sep 30 - Oct 6 2026 outage).
    state = LeagueState()
    notifier = _Notifier()

    assert _run([_trade("t1", "unvalued")], state, notifier) == 1

    assert len(notifier.posted) == 1
    field_names = [f["name"] for f in notifier.posted[0]["fields"]]
    assert "Trade values" not in field_names
    assert state.seen_transaction_ids == ["t1"]


def test_ungradable_trade_does_not_block_later_transactions() -> None:
    state = LeagueState()
    notifier = _Notifier()

    _run([_trade("t1", "unvalued"), _trade("t2", "known")], state, notifier)

    assert state.seen_transaction_ids == ["t1", "t2"]
    graded = [f["name"] for f in notifier.posted[1]["fields"]]
    assert "Trade values" in graded


class _WeeklySleeper:
    def __init__(self, by_week: dict[int, list[dict[str, Any]]]) -> None:
        self.by_week = by_week
        self.weeks_fetched: list[int] = []

    def get_transactions(self, league_id: str, week: int) -> list[dict[str, Any]]:
        self.weeks_fetched.append(week)
        return self.by_week.get(week, [])


def test_fetch_recent_includes_previous_week_oldest_first() -> None:
    sleeper = _WeeklySleeper({4: [{"transaction_id": "w4"}], 5: [{"transaction_id": "w5"}]})
    txs = fetch_recent_transactions(sleeper, "L1", 5)
    assert sleeper.weeks_fetched == [4, 5]
    assert [t["transaction_id"] for t in txs] == ["w4", "w5"]


def test_fetch_recent_week_one_fetches_once() -> None:
    sleeper = _WeeklySleeper({1: [{"transaction_id": "w1"}]})
    assert [t["transaction_id"] for t in fetch_recent_transactions(sleeper, "L1", 1)] == ["w1"]
    assert sleeper.weeks_fetched == [1]


def test_missed_last_week_tx_posts_once_after_rollover() -> None:
    state = LeagueState(seen_transaction_ids=["w5-old"])
    notifier = _Notifier()
    sleeper = _WeeklySleeper({4: [_trade("w4-missed", "known")], 5: [_trade("w5-old", "known")]})

    txs = fetch_recent_transactions(sleeper, "L1", 5)
    _run(txs, state, notifier)
    _run(txs, state, notifier)

    assert len(notifier.posted) == 1
    assert state.seen_transaction_ids == ["w5-old", "w4-missed"]

"""Trade grading: per-roster value math + imbalance percent + lopsided rule."""

from __future__ import annotations

from typing import Any

from src.fantasycalc import grade_trade, letter_grade, trade_imbalance_percent
from src.rules.checks.lopsided_trade import LopsidedTrade
from src.rules.engine import RuleContext
from src.rules.result import Severity


class StubValues:
    """In-memory ValueLookup for tests."""

    def __init__(
        self,
        players: dict[str, int] | None = None,
        picks: dict[tuple[str, int], int] | None = None,
    ) -> None:
        self._players = players or {}
        self._picks = picks or {}

    def player_value(self, sleeper_id: str | None) -> int:
        return int(self._players.get(str(sleeper_id), 0))

    def pick_value(self, season: str | int, round_no: int) -> int:
        return int(self._picks.get((str(season), int(round_no)), 0))


def test_even_player_swap_nets_zero() -> None:
    tx = {
        "type": "trade",
        "status": "complete",
        "roster_ids": [1, 2],
        "adds": {"a": 2, "b": 1},
        "drops": {"a": 1, "b": 2},
        "draft_picks": [],
    }
    values = StubValues(players={"a": 5000, "b": 5000})
    grades = grade_trade(tx, values)
    assert grades[1]["net"] == 0
    assert grades[2]["net"] == 0
    assert trade_imbalance_percent(grades) == 0


def test_lopsided_player_swap_reports_correct_net() -> None:
    tx = {
        "type": "trade",
        "status": "complete",
        "roster_ids": [1, 2],
        "adds": {"premium": 2, "scrub": 1},
        "drops": {"premium": 1, "scrub": 2},
        "draft_picks": [],
    }
    values = StubValues(players={"premium": 10000, "scrub": 2000})
    grades = grade_trade(tx, values)
    assert grades[1]["sent"] == 10000  # roster 1 sent premium
    assert grades[1]["received"] == 2000
    assert grades[1]["net"] == -8000
    assert grades[2]["net"] == 8000


def test_pick_swap_uses_pick_values() -> None:
    tx = {
        "type": "trade",
        "status": "complete",
        "roster_ids": [1, 2],
        "adds": {},
        "drops": {},
        "draft_picks": [
            {"round": 1, "season": "2027", "owner_id": 2, "previous_owner_id": 1},
        ],
    }
    values = StubValues(picks={("2027", 1): 7000})
    grades = grade_trade(tx, values)
    assert grades[1]["sent"] == 7000
    assert grades[2]["received"] == 7000


def test_imbalance_percent_handles_zero_total() -> None:
    grades = {1: {"sent": 0, "received": 0, "net": 0}, 2: {"sent": 0, "received": 0, "net": 0}}
    assert trade_imbalance_percent(grades) == 0


def test_letter_grade_ranges() -> None:
    assert letter_grade(20) == "A"
    assert letter_grade(10) == "B"
    assert letter_grade(0) == "C"
    assert letter_grade(-10) == "D"
    assert letter_grade(-20) == "F"


def test_lopsided_rule_fires_when_threshold_exceeded() -> None:
    tx = {
        "transaction_id": "t1",
        "type": "trade",
        "status": "complete",
        "roster_ids": [1, 2],
        "adds": {"big": 2},
        "drops": {"big": 1},
        "draft_picks": [],
    }
    ctx = RuleContext(
        league_id="L1",
        league_name="Test",
        transactions=[tx],
        roster_to_team={1: "Team A", 2: "Team B"},
        fantasycalc=StubValues(players={"big": 10000}),
    )
    results = LopsidedTrade().evaluate(ctx, {"value_diff_threshold_pct": 35})
    assert len(results) == 1
    assert results[0].severity is Severity.FLAG
    assert "imbalance" in results[0].title.lower()


def test_grade_trade_returns_none_when_player_value_missing() -> None:
    tx = {
        "type": "trade",
        "status": "complete",
        "roster_ids": [1, 2],
        "adds": {"a": 2, "unknown": 1},
        "drops": {"a": 1, "unknown": 2},
        "draft_picks": [],
    }
    values = StubValues(players={"a": 5000})  # "unknown" missing
    assert grade_trade(tx, values) is None


def test_grade_trade_returns_none_when_pick_value_missing() -> None:
    tx = {
        "type": "trade",
        "status": "complete",
        "roster_ids": [1, 2],
        "adds": {},
        "drops": {},
        "draft_picks": [{"round": 7, "season": "2099", "owner_id": 2, "previous_owner_id": 1}],
    }
    assert grade_trade(tx, StubValues()) is None


def test_lopsided_rule_skips_ungradeable_trades() -> None:
    tx = {
        "transaction_id": "t1",
        "type": "trade",
        "status": "complete",
        "roster_ids": [1, 2],
        "adds": {"unknown_player": 2},
        "drops": {"unknown_player": 1},
    }
    ctx = RuleContext(
        league_id="L1",
        league_name="Test",
        transactions=[tx],
        roster_to_team={1: "Team A", 2: "Team B"},
        fantasycalc=StubValues(),
    )
    assert LopsidedTrade().evaluate(ctx, {"value_diff_threshold_pct": 35}) == []


def test_lopsided_rule_silent_when_no_fantasycalc() -> None:
    tx = {"transaction_id": "t1", "type": "trade", "status": "complete", "roster_ids": [1, 2]}
    ctx = RuleContext(league_id="L1", league_name="Test", transactions=[tx], fantasycalc=None)
    assert LopsidedTrade().evaluate(ctx, {}) == []


def test_lopsided_rule_silent_for_even_trade() -> None:
    tx = {
        "transaction_id": "t1",
        "type": "trade",
        "status": "complete",
        "roster_ids": [1, 2],
        "adds": {"a": 2, "b": 1},
        "drops": {"a": 1, "b": 2},
    }
    ctx = RuleContext(
        league_id="L1",
        league_name="Test",
        transactions=[tx],
        roster_to_team={1: "Team A", 2: "Team B"},
        fantasycalc=StubValues(players={"a": 5000, "b": 5000}),
    )
    assert LopsidedTrade().evaluate(ctx, {"value_diff_threshold_pct": 35}) == []

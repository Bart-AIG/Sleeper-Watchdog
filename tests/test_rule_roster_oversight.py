"""roster_oversight rule + Article XIV strike tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.rules.checks.roster_oversight import RosterOversight
from src.rules.engine import RuleContext
from src.rules.result import Severity
from src.state import LeagueState


def _player(pid: str, pos: str, injury: str = "", name: str | None = None) -> dict:
    return {
        "name": name or f"P{pid}",
        "team": "BUF",
        "position": pos,
        "fantasy_positions": [pos],
        "injury_status": injury,
        "years_exp": 5,
        "status": "Active",
    }


def _ctx(
    *,
    rosters: list[dict],
    players: dict[str, dict],
    in_season: bool = True,
    state: LeagueState | None = None,
    week: int = 5,
) -> RuleContext:
    return RuleContext(
        league_id="L1",
        league_name="Test",
        league={
            "status": "in_season" if in_season else "drafting",
            "roster_positions": ["QB", "RB", "RB", "WR", "FLEX", "BN", "BN"],
        },
        nfl_state={"season": "2026", "week": week},
        rosters=rosters,
        players=players,
        roster_to_team={1: "Team A", 2: "Team B"},
        league_state=state or LeagueState(),
        now=datetime.now(timezone.utc),
    )


def test_skipped_pre_season() -> None:
    rosters = [{"roster_id": 1, "owner_id": "u1", "starters": ["0", "0", "0", "0", "0"], "players": ["p1"]}]
    players = {"p1": _player("p1", "QB")}
    ctx = _ctx(rosters=rosters, players=players, in_season=False)
    assert RosterOversight().evaluate(ctx, {}) == []


def test_no_alert_when_all_starting_slots_filled() -> None:
    rosters = [{
        "roster_id": 1,
        "owner_id": "u1",
        "starters": ["p1", "p2", "p3", "p4", "p5"],
        "players": ["p1", "p2", "p3", "p4", "p5"],
    }]
    players = {pid: _player(pid, "RB") for pid in ["p1", "p2", "p3", "p4", "p5"]}
    assert RosterOversight().evaluate(_ctx(rosters=rosters, players=players), {}) == []


def test_empty_slot_with_eligible_bench_fires_flag() -> None:
    rosters = [{
        "roster_id": 1,
        "owner_id": "u1",
        "starters": ["p1", "p2", "p3", "p4", "0"],  # FLEX empty
        "players": ["p1", "p2", "p3", "p4", "p5", "p6"],
    }]
    players = {
        "p1": _player("p1", "QB"),
        "p2": _player("p2", "RB"),
        "p3": _player("p3", "RB"),
        "p4": _player("p4", "WR"),
        "p5": _player("p5", "RB", name="bench_rb"),  # eligible for FLEX
        "p6": _player("p6", "QB"),  # not FLEX-eligible
    }
    state = LeagueState()
    results = RosterOversight().evaluate(_ctx(rosters=rosters, players=players, state=state), {})
    assert len(results) == 1
    assert results[0].severity is Severity.FLAG
    assert "FLEX" in results[0].title
    repl_field = next(f for f in results[0].fields if "replacement" in f["name"].lower())
    assert "bench_rb" in repl_field["value"]


def test_empty_slot_but_only_injured_bench_does_not_fire() -> None:
    rosters = [{
        "roster_id": 1,
        "owner_id": "u1",
        "starters": ["0", "p2", "p3", "p4", "p5"],
        "players": ["p2", "p3", "p4", "p5", "hurt"],
    }]
    players = {
        "p2": _player("p2", "RB"),
        "p3": _player("p3", "RB"),
        "p4": _player("p4", "WR"),
        "p5": _player("p5", "RB"),
        "hurt": _player("hurt", "QB", injury="Out"),
    }
    assert RosterOversight().evaluate(_ctx(rosters=rosters, players=players), {}) == []


def test_strike_count_increments_per_distinct_oversight() -> None:
    state = LeagueState()
    rosters = [{
        "roster_id": 1,
        "owner_id": "u1",
        "starters": ["0", "p2", "p3", "p4", "p5"],  # QB empty
        "players": ["p2", "p3", "p4", "p5", "bench_qb"],
    }]
    players = {
        "p2": _player("p2", "RB"),
        "p3": _player("p3", "RB"),
        "p4": _player("p4", "WR"),
        "p5": _player("p5", "RB"),
        "bench_qb": _player("bench_qb", "QB"),
    }
    # Week 5 oversight
    RosterOversight().evaluate(_ctx(rosters=rosters, players=players, state=state, week=5), {})
    assert len(state.strikes_by_user["u1"].strikes) == 1
    # Same week, re-evaluation should NOT double-count
    RosterOversight().evaluate(_ctx(rosters=rosters, players=players, state=state, week=5), {})
    assert len(state.strikes_by_user["u1"].strikes) == 1
    # Week 6 same oversight: new strike
    RosterOversight().evaluate(_ctx(rosters=rosters, players=players, state=state, week=6), {})
    assert len(state.strikes_by_user["u1"].strikes) == 2


def test_third_strike_escalates_to_block() -> None:
    state = LeagueState()
    rosters = [{
        "roster_id": 1,
        "owner_id": "u1",
        "starters": ["0", "p2", "p3", "p4", "p5"],
        "players": ["p2", "p3", "p4", "p5", "bench_qb"],
    }]
    players = {
        "p2": _player("p2", "RB"),
        "p3": _player("p3", "RB"),
        "p4": _player("p4", "WR"),
        "p5": _player("p5", "RB"),
        "bench_qb": _player("bench_qb", "QB"),
    }
    for w in (1, 2):
        RosterOversight().evaluate(_ctx(rosters=rosters, players=players, state=state, week=w), {})
    results = RosterOversight().evaluate(_ctx(rosters=rosters, players=players, state=state, week=3), {})
    assert results[0].severity is Severity.BLOCK
    assert "removal recommended" in results[0].title


def test_strike_tracking_disabled_does_not_persist() -> None:
    state = LeagueState()
    rosters = [{
        "roster_id": 1,
        "owner_id": "u1",
        "starters": ["0", "p2", "p3", "p4", "p5"],
        "players": ["p2", "p3", "p4", "p5", "bench_qb"],
    }]
    players = {
        "p2": _player("p2", "RB"),
        "p3": _player("p3", "RB"),
        "p4": _player("p4", "WR"),
        "p5": _player("p5", "RB"),
        "bench_qb": _player("bench_qb", "QB"),
    }
    RosterOversight().evaluate(
        _ctx(rosters=rosters, players=players, state=state),
        {"strike_tracking": {"enabled": False}},
    )
    assert state.strikes_by_user == {}


def test_taxi_and_ir_excluded_from_bench_pool() -> None:
    state = LeagueState()
    rosters = [{
        "roster_id": 1,
        "owner_id": "u1",
        "starters": ["0", "p2", "p3", "p4", "p5"],
        "players": ["p2", "p3", "p4", "p5"],
        "reserve": ["ir_qb"],
        "taxi": ["taxi_qb"],
    }]
    players = {
        "p2": _player("p2", "RB"),
        "p3": _player("p3", "RB"),
        "p4": _player("p4", "WR"),
        "p5": _player("p5", "RB"),
        "ir_qb": _player("ir_qb", "QB"),
        "taxi_qb": _player("taxi_qb", "QB"),
    }
    assert RosterOversight().evaluate(_ctx(rosters=rosters, players=players, state=state), {}) == []

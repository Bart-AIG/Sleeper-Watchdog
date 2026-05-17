"""roster_size rule."""

from __future__ import annotations

from src.rules.checks.roster_size import RosterSize
from src.rules.engine import RuleContext


def _ctx_with_rosters(rosters: list[dict]) -> RuleContext:
    return RuleContext(
        league_id="L1",
        league_name="Test",
        rosters=rosters,
        roster_to_team={1: "Team A", 2: "Team B"},
    )


def test_oversized_active_roster_fires() -> None:
    rosters = [
        {"roster_id": 1, "players": [str(i) for i in range(30)], "reserve": [], "taxi": []},
    ]
    results = RosterSize().evaluate(_ctx_with_rosters(rosters), {"max_active": 28})
    assert len(results) == 1
    assert "active 30 > 28" in results[0].message
    assert "Team A" in results[0].title


def test_normal_roster_passes() -> None:
    rosters = [
        {"roster_id": 1, "players": [str(i) for i in range(28)], "reserve": [], "taxi": []},
    ]
    assert RosterSize().evaluate(_ctx_with_rosters(rosters), {}) == []


def test_each_oversized_dimension_reports_separately() -> None:
    rosters = [
        {
            "roster_id": 1,
            "players": [str(i) for i in range(30)],
            "reserve": [str(i) for i in range(5)],
            "taxi": [str(i) for i in range(4)],
        }
    ]
    result = RosterSize().evaluate(_ctx_with_rosters(rosters), {})[0]
    assert "active" in result.message
    assert "IR" in result.message
    assert "taxi" in result.message


def test_null_reserve_and_taxi_treated_as_empty() -> None:
    rosters = [
        {"roster_id": 1, "players": [str(i) for i in range(10)], "reserve": None, "taxi": None},
    ]
    assert RosterSize().evaluate(_ctx_with_rosters(rosters), {}) == []


def test_alert_key_changes_when_counts_change() -> None:
    rosters_a = [{"roster_id": 1, "players": [str(i) for i in range(30)], "reserve": [], "taxi": []}]
    rosters_b = [{"roster_id": 1, "players": [str(i) for i in range(31)], "reserve": [], "taxi": []}]
    key_a = RosterSize().evaluate(_ctx_with_rosters(rosters_a), {})[0].alert_key
    key_b = RosterSize().evaluate(_ctx_with_rosters(rosters_b), {})[0].alert_key
    assert key_a != key_b

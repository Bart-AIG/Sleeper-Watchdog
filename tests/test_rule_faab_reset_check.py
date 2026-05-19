"""faab_reset_check rule: fires only on specified dates, only when some roster
has non-zero waiver_budget_used."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.rules.checks.faab_reset_check import FaabResetCheck
from src.rules.engine import RuleContext


def _ctx(now_iso: str, rosters: list[dict[str, Any]]) -> RuleContext:
    return RuleContext(
        league_id="L1",
        league_name="Test",
        rosters=rosters,
        roster_to_team={1: "Team A", 2: "Team B"},
        now=datetime.fromisoformat(now_iso).replace(tzinfo=timezone.utc),
    )


def test_silent_when_not_on_check_date() -> None:
    rosters = [{"roster_id": 1, "settings": {"waiver_budget_used": 50}}]
    ctx = _ctx("2026-08-15T12:00:00", rosters)
    assert FaabResetCheck().evaluate(ctx, {"check_dates": ["2026-09-01", "2026-09-02"]}) == []


def test_silent_on_check_date_when_all_zero() -> None:
    rosters = [
        {"roster_id": 1, "settings": {"waiver_budget_used": 0}},
        {"roster_id": 2, "settings": {"waiver_budget_used": 0}},
    ]
    ctx = _ctx("2026-09-01T08:00:00", rosters)
    assert FaabResetCheck().evaluate(ctx, {"check_dates": ["2026-09-01"]}) == []


def test_fires_on_check_date_with_dirty_roster() -> None:
    rosters = [
        {"roster_id": 1, "settings": {"waiver_budget_used": 0}},
        {"roster_id": 2, "settings": {"waiver_budget_used": 35}},
    ]
    ctx = _ctx("2026-09-01T08:00:00", rosters)
    results = FaabResetCheck().evaluate(ctx, {"check_dates": ["2026-09-01"]})
    assert len(results) == 1
    assert "2026-09-01" in results[0].title
    detail = next(f for f in results[0].fields if f["name"] == "Detail")
    assert "Team B" in detail["value"]
    assert "35" in detail["value"]
    assert "Team A" not in detail["value"]  # only the dirty roster listed


def test_alert_key_per_date_so_two_days_fire_separately() -> None:
    rosters = [{"roster_id": 1, "settings": {"waiver_budget_used": 10}}]
    day1 = _ctx("2026-09-01T08:00:00", rosters)
    day2 = _ctx("2026-09-02T08:00:00", rosters)
    key1 = FaabResetCheck().evaluate(day1, {"check_dates": ["2026-09-01", "2026-09-02"]})[0].alert_key
    key2 = FaabResetCheck().evaluate(day2, {"check_dates": ["2026-09-01", "2026-09-02"]})[0].alert_key
    assert key1 != key2
    assert "2026-09-01" in key1
    assert "2026-09-02" in key2


def test_no_check_dates_returns_empty() -> None:
    rosters = [{"roster_id": 1, "settings": {"waiver_budget_used": 100}}]
    assert FaabResetCheck().evaluate(_ctx("2026-09-01T08:00:00", rosters), {}) == []


def test_custom_field_and_expected_value() -> None:
    rosters = [{"roster_id": 1, "settings": {"waiver_position": 7}}]
    ctx = _ctx("2026-09-01T08:00:00", rosters)
    results = FaabResetCheck().evaluate(
        ctx,
        {"check_dates": ["2026-09-01"], "field": "settings.waiver_position", "expected_value": 1},
    )
    assert len(results) == 1

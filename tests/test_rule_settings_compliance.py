"""settings_compliance rule across all drift categories."""

from __future__ import annotations

from typing import Any

from src.rules.checks.settings_compliance import SettingsCompliance
from src.rules.engine import RuleContext


def _ctx(
    *,
    league: dict[str, Any] | None = None,
    users: list[dict[str, Any]] | None = None,
    rosters: list[dict[str, Any]] | None = None,
) -> RuleContext:
    return RuleContext(
        league_id="L1",
        league_name="Test",
        league=league or {},
        users=users or [],
        rosters=rosters or [],
    )


def test_no_drift_emits_no_results() -> None:
    ctx = _ctx(
        league={"name": "X", "settings": {"waiver_budget": 200}, "scoring_settings": {"rec": 0.5}},
    )
    params = {
        "expected_league": {"name": "X"},
        "expected_settings": {"waiver_budget": 200},
        "expected_scoring_settings": {"rec": 0.5},
    }
    assert SettingsCompliance().evaluate(ctx, params) == []


def test_top_level_league_drift_fires_one_alert() -> None:
    ctx = _ctx(league={"name": "Bart's League", "num_teams": 10})
    params = {"expected_league": {"name": "512 Dynasty League", "num_teams": 12}}
    results = SettingsCompliance().evaluate(ctx, params)
    assert len(results) == 1
    assert "league" in results[0].title
    assert "name" in results[0].fields[2]["value"]
    assert "num_teams" in results[0].fields[2]["value"]


def test_settings_drift_separates_from_scoring_drift() -> None:
    ctx = _ctx(
        league={
            "settings": {"waiver_budget": 100},
            "scoring_settings": {"pass_td": 6.0},
        }
    )
    params = {
        "expected_settings": {"waiver_budget": 200},
        "expected_scoring_settings": {"pass_td": 4.0},
    }
    results = SettingsCompliance().evaluate(ctx, params)
    assert len(results) == 2
    categories = sorted(r.fields[0]["value"] for r in results)
    assert categories == ["`scoring_settings`", "`settings`"]


def test_default_ignore_keys_suppress_volatile_settings() -> None:
    ctx = _ctx(league={"settings": {"leg": 5, "waiver_budget": 200, "daily_waivers_last_ran": 1}})
    params = {"expected_settings": {"leg": 0, "waiver_budget": 200, "daily_waivers_last_ran": 0}}
    assert SettingsCompliance().evaluate(ctx, params) == []


def test_custom_ignore_keys_param() -> None:
    ctx = _ctx(league={"settings": {"trade_deadline": 14, "veto_votes_needed": 6}})
    params = {
        "expected_settings": {"trade_deadline": 13, "veto_votes_needed": 6},
        "ignore_settings_keys": ["trade_deadline"],
    }
    assert SettingsCompliance().evaluate(ctx, params) == []


def test_status_change_ignored_by_default() -> None:
    ctx = _ctx(league={"name": "X", "status": "in_season"})
    params = {"expected_league": {"name": "X", "status": "drafting"}}
    assert SettingsCompliance().evaluate(ctx, params) == []


def test_roster_positions_drift_compares_ordered_list() -> None:
    ctx = _ctx(league={"roster_positions": ["QB", "RB", "WR", "TE"]})
    params = {"expected_roster_positions": ["QB", "RB", "RB", "WR", "TE"]}
    results = SettingsCompliance().evaluate(ctx, params)
    assert len(results) == 1
    assert "roster_positions" in results[0].title


def test_users_drift_reports_added_and_removed() -> None:
    ctx = _ctx(users=[
        {"user_id": "u1", "display_name": "alice"},
        {"user_id": "u4", "display_name": "newcomer"},
    ])
    params = {"expected_user_ids": ["u1", "u2", "u3"]}
    results = SettingsCompliance().evaluate(ctx, params)
    assert len(results) == 1
    msg = results[0].fields[2]["value"]
    assert "u4" in msg
    assert "newcomer" in msg
    assert "u2" in msg
    assert "u3" in msg


def test_orphan_rosters_detected() -> None:
    ctx = _ctx(rosters=[
        {"roster_id": 1, "owner_id": "u1"},
        {"roster_id": 2, "owner_id": None},
        {"roster_id": 3, "owner_id": ""},
    ])
    results = SettingsCompliance().evaluate(ctx, {})
    assert len(results) == 1
    assert "orphan" in results[0].title
    assert "2" in results[0].fields[2]["value"]
    assert "3" in results[0].fields[2]["value"]


def test_roster_owner_changes_detected() -> None:
    ctx = _ctx(rosters=[
        {"roster_id": 1, "owner_id": "u1"},
        {"roster_id": 2, "owner_id": "u_new"},
    ])
    params = {"expected_roster_owners": {"1": "u1", "2": "u2"}}
    results = SettingsCompliance().evaluate(ctx, params)
    assert len(results) == 1
    assert "roster_owners" in results[0].title


def test_alert_key_changes_when_drift_changes() -> None:
    base_params = {"expected_settings": {"waiver_budget": 200}}
    ctx_a = _ctx(league={"settings": {"waiver_budget": 100}})
    ctx_b = _ctx(league={"settings": {"waiver_budget": 150}})
    key_a = SettingsCompliance().evaluate(ctx_a, base_params)[0].alert_key
    key_b = SettingsCompliance().evaluate(ctx_b, base_params)[0].alert_key
    assert key_a != key_b

"""settings_changed rule: first-run snapshot + change detection + window."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.rules.checks.settings_changed import SettingsChanged
from src.rules.engine import RuleContext
from src.rules.result import Severity
from src.state import LeagueState


def _ctx(
    *,
    settings: dict[str, Any],
    state: LeagueState | None = None,
    now_iso: str = "2026-05-17T12:00:00",
    calendar: dict | None = None,
) -> RuleContext:
    return RuleContext(
        league_id="L1",
        league_name="Test",
        calendar=calendar or {},
        league={"settings": settings},
        now=datetime.fromisoformat(now_iso).replace(tzinfo=timezone.utc),
        league_state=state or LeagueState(),
    )


def test_first_run_snapshots_and_stays_quiet() -> None:
    state = LeagueState()
    ctx = _ctx(settings={"waiver_budget": 200}, state=state)
    assert SettingsChanged().evaluate(ctx, {}) == []
    assert state.last_settings_hash != ""
    assert state.last_settings_snapshot == {"waiver_budget": 200}


def test_no_change_emits_no_alert() -> None:
    state = LeagueState()
    settings = {"waiver_budget": 200, "trade_deadline": 13}
    SettingsChanged().evaluate(_ctx(settings=settings, state=state), {})
    assert SettingsChanged().evaluate(_ctx(settings=settings, state=state), {}) == []


def test_change_outside_window_fires_block() -> None:
    state = LeagueState()
    SettingsChanged().evaluate(_ctx(settings={"trade_deadline": 13}, state=state), {})
    calendar = {"offseason_period_1_start": "2026-01-06", "offseason_period_1_end": "2026-04-30"}
    ctx = _ctx(
        settings={"trade_deadline": 99},
        state=state,
        now_iso="2026-07-01T12:00:00",
        calendar=calendar,
    )
    results = SettingsChanged().evaluate(ctx, {})
    assert len(results) == 1
    assert results[0].severity is Severity.BLOCK
    assert "OUTSIDE" in results[0].title


def test_change_inside_window_downgrades_to_flag() -> None:
    state = LeagueState()
    SettingsChanged().evaluate(_ctx(settings={"trade_deadline": 13}, state=state), {})
    calendar = {"offseason_period_1_start": "2026-01-06", "offseason_period_1_end": "2026-04-30"}
    ctx = _ctx(
        settings={"trade_deadline": 99},
        state=state,
        now_iso="2026-02-15T12:00:00",
        calendar=calendar,
    )
    results = SettingsChanged().evaluate(ctx, {})
    assert len(results) == 1
    assert results[0].severity is Severity.FLAG
    assert "within" in results[0].title


def test_ignored_key_change_does_not_alert() -> None:
    state = LeagueState()
    SettingsChanged().evaluate(_ctx(settings={"leg": 1, "waiver_budget": 200}, state=state), {})
    # leg ticks naturally; should not fire.
    results = SettingsChanged().evaluate(
        _ctx(settings={"leg": 5, "waiver_budget": 200}, state=state), {}
    )
    assert results == []


def test_diff_field_lists_each_changed_key() -> None:
    state = LeagueState()
    SettingsChanged().evaluate(_ctx(settings={"a": 1, "b": 2}, state=state), {})
    ctx = _ctx(settings={"a": 99, "b": 2}, state=state, now_iso="2026-07-01T12:00:00")
    results = SettingsChanged().evaluate(ctx, {})
    diff_field = next(f for f in results[0].fields if f["name"] == "Diff")
    assert "`a`" in diff_field["value"]
    assert "1" in diff_field["value"] and "99" in diff_field["value"]


def test_state_updates_so_second_change_re_alerts() -> None:
    state = LeagueState()
    SettingsChanged().evaluate(_ctx(settings={"x": 1}, state=state), {})
    first = SettingsChanged().evaluate(_ctx(settings={"x": 2}, state=state, now_iso="2026-07-01T12:00:00"), {})
    second = SettingsChanged().evaluate(_ctx(settings={"x": 2}, state=state, now_iso="2026-07-01T13:00:00"), {})
    third = SettingsChanged().evaluate(_ctx(settings={"x": 3}, state=state, now_iso="2026-07-01T14:00:00"), {})
    assert len(first) == 1
    assert second == []  # no further change
    assert len(third) == 1  # new change re-fires


def test_no_state_returns_empty() -> None:
    ctx = RuleContext(league_id="L1", league_name="Test", league={"settings": {"x": 1}})
    assert SettingsChanged().evaluate(ctx, {}) == []

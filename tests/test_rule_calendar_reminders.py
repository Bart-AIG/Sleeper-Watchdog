"""calendar_reminders rule across each reminder type."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.rules.checks.calendar_reminders import CalendarReminders
from src.rules.engine import RuleContext
from src.rules.result import Severity


def _ctx(
    *,
    now_iso: str = "2026-05-17T12:00:00",
    week: int = 0,
    league: dict[str, Any] | None = None,
) -> RuleContext:
    now = datetime.fromisoformat(now_iso).replace(tzinfo=timezone.utc)
    return RuleContext(
        league_id="L1",
        league_name="Test",
        league=league or {},
        nfl_state={"week": week, "season": "2026"},
        now=now,
    )


def test_no_reminders_returns_empty() -> None:
    assert CalendarReminders().evaluate(_ctx(), {"reminders": []}) == []


def test_date_reached_fires_when_date_passes() -> None:
    ctx = _ctx(now_iso="2026-05-01T00:00:00")
    params = {"reminders": [{"id": "amendments_closed", "type": "date_reached", "date": "2026-04-30", "message": "x"}]}
    results = CalendarReminders().evaluate(ctx, params)
    assert len(results) == 1
    assert "amendments_closed" in results[0].title
    assert results[0].alert_key.endswith("amendments_closed:2026")


def test_date_reached_silent_before_date() -> None:
    ctx = _ctx(now_iso="2026-04-29T00:00:00")
    params = {"reminders": [{"id": "x", "type": "date_reached", "date": "2026-04-30", "message": "x"}]}
    assert CalendarReminders().evaluate(ctx, params) == []


def test_days_before_fires_inside_window() -> None:
    ctx = _ctx(now_iso="2026-08-30T00:00:00")
    params = {
        "reminders": [
            {"id": "season_soon", "type": "days_before_date", "date": "2026-09-03", "days": 7, "message": "x"}
        ]
    }
    results = CalendarReminders().evaluate(ctx, params)
    assert len(results) == 1
    days_field = next(f for f in results[0].fields if f["name"] == "days_remaining")
    assert days_field["value"] == "4"


def test_days_before_silent_outside_window() -> None:
    ctx = _ctx(now_iso="2026-08-01T00:00:00")
    params = {
        "reminders": [
            {"id": "x", "type": "days_before_date", "date": "2026-09-03", "days": 7, "message": "x"}
        ]
    }
    assert CalendarReminders().evaluate(ctx, params) == []


def test_days_before_silent_after_target_date() -> None:
    ctx = _ctx(now_iso="2026-09-10T00:00:00")
    params = {
        "reminders": [
            {"id": "x", "type": "days_before_date", "date": "2026-09-03", "days": 7, "message": "x"}
        ]
    }
    assert CalendarReminders().evaluate(ctx, params) == []


def test_nfl_week_reached_fires_at_or_past_week() -> None:
    ctx = _ctx(week=13)
    params = {"reminders": [{"id": "deadline", "type": "nfl_week_reached", "week": 13, "message": "x"}]}
    results = CalendarReminders().evaluate(ctx, params)
    assert len(results) == 1
    week_field = next(f for f in results[0].fields if f["name"] == "current_week")
    assert week_field["value"] == "13"


def test_nfl_week_reached_silent_before_week() -> None:
    ctx = _ctx(week=12)
    params = {"reminders": [{"id": "x", "type": "nfl_week_reached", "week": 13, "message": "x"}]}
    assert CalendarReminders().evaluate(ctx, params) == []


def test_date_passed_and_setting_not_fires_when_mismatch() -> None:
    ctx = _ctx(
        now_iso="2026-06-15T00:00:00",
        league={"settings": {"disable_adds": 1}},
    )
    params = {
        "reminders": [
            {
                "id": "fa_open",
                "type": "date_passed_and_setting_not",
                "after_date": "2026-06-01",
                "setting_path": "disable_adds",
                "expected_value": 0,
                "message": "x",
            }
        ]
    }
    results = CalendarReminders().evaluate(ctx, params)
    assert len(results) == 1
    live_field = next(f for f in results[0].fields if f["name"] == "live")
    assert live_field["value"] == "1"


def test_date_passed_and_setting_not_silent_when_setting_matches() -> None:
    ctx = _ctx(
        now_iso="2026-06-15T00:00:00",
        league={"settings": {"disable_adds": 0}},
    )
    params = {
        "reminders": [
            {
                "id": "x",
                "type": "date_passed_and_setting_not",
                "after_date": "2026-06-01",
                "setting_path": "disable_adds",
                "expected_value": 0,
                "message": "x",
            }
        ]
    }
    assert CalendarReminders().evaluate(ctx, params) == []


def test_date_passed_and_setting_not_silent_before_after_date() -> None:
    ctx = _ctx(
        now_iso="2026-05-15T00:00:00",
        league={"settings": {"disable_adds": 1}},
    )
    params = {
        "reminders": [
            {
                "id": "x",
                "type": "date_passed_and_setting_not",
                "after_date": "2026-06-01",
                "setting_path": "disable_adds",
                "expected_value": 0,
                "message": "x",
            }
        ]
    }
    assert CalendarReminders().evaluate(ctx, params) == []


def test_per_reminder_severity_overrides_default() -> None:
    ctx = _ctx(week=13)
    params = {
        "severity": "FLAG",
        "reminders": [
            {"id": "x", "type": "nfl_week_reached", "week": 13, "severity": "BLOCK", "message": "x"}
        ],
    }
    results = CalendarReminders().evaluate(ctx, params)
    assert results[0].severity is Severity.BLOCK


def test_unknown_reminder_type_skipped() -> None:
    ctx = _ctx()
    params = {"reminders": [{"id": "x", "type": "made_up_type", "message": "x"}]}
    assert CalendarReminders().evaluate(ctx, params) == []


def test_alert_key_includes_season_and_id() -> None:
    ctx = _ctx(week=13)
    params = {"reminders": [{"id": "deadline", "type": "nfl_week_reached", "week": 13, "message": "x"}]}
    key = CalendarReminders().evaluate(ctx, params)[0].alert_key
    assert key == "L1:calendar_reminders:deadline:2026"

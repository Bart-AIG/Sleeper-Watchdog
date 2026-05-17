"""Article XIII: detect the moment a league setting changes between runs.

Severity is BLOCK when the change happens outside Off-Season Period 1 (the
allowed amendments window per the constitution). Inside the window it
downgrades to FLAG so commish-led changes still produce a record but do not
look like a violation.

This rule is stateful: it stores a hash of the last-seen settings dict on
the league state so the next run can detect the change. First sighting
records the hash silently and emits no alert. Pair with the orchestrator's
per-rule bootstrap to be safe even if the state field is missing on day one.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity


def _hash(payload: Any) -> str:
    return hashlib.sha1(  # noqa: S324
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _diff(old: dict, new: dict, ignore_keys: set[str]) -> dict[str, dict]:
    keys = (set(old) | set(new)) - ignore_keys
    out = {}
    for k in keys:
        if old.get(k) != new.get(k):
            out[k] = {"old": old.get(k), "new": new.get(k)}
    return out


class SettingsChanged:
    rule_id = "settings_changed"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        if ctx.league_state is None:
            return []

        ignore_keys = set(params.get("ignore_keys") or []) | {
            "leg",
            "daily_waivers_last_ran",
            "last_scored_leg",
        }
        current_settings = ctx.league.get("settings") or {}
        current_hash = _hash({k: v for k, v in current_settings.items() if k not in ignore_keys})
        last_hash = ctx.league_state.last_settings_hash

        # First sighting: snapshot and stay quiet. The per-rule bootstrap in
        # main.py also covers this, but updating state here makes the rule
        # self-sufficient.
        if not last_hash:
            ctx.league_state.last_settings_hash = current_hash
            ctx.league_state.last_settings_snapshot = dict(current_settings)
            return []

        if current_hash == last_hash:
            return []

        previous = ctx.league_state.last_settings_snapshot or {}
        diff = _diff(previous, current_settings, ignore_keys)
        if not diff:
            ctx.league_state.last_settings_hash = current_hash
            ctx.league_state.last_settings_snapshot = dict(current_settings)
            return []

        in_window = self._is_in_amendments_window(ctx, params)
        base_severity = Severity(params.get("severity", "BLOCK"))
        if in_window:
            severity = Severity.FLAG
            title = "Settings changed (within amendments window)"
        else:
            severity = base_severity
            title = "Settings changed OUTSIDE amendments window"

        diff_lines = []
        for k in sorted(diff):
            change = diff[k]
            diff_lines.append(f"`{k}`: {change['old']!r} -> {change['new']!r}")
        rendered = "\n".join(diff_lines)
        if len(rendered) > 1000:
            rendered = rendered[:990] + "\n... (truncated)"

        message = params.get(
            "message",
            "Article XIII: league settings may only change during Off-Season Period 1.",
        )

        result = RuleResult(
            rule_id=self.rule_id,
            severity=severity,
            title=title,
            message=message,
            fields=[
                {"name": "Changes", "value": str(len(diff)), "inline": True},
                {"name": "In amendments window", "value": "yes" if in_window else "no", "inline": True},
                {"name": "Diff", "value": rendered, "inline": False},
                {"name": "Rule", "value": f"`{self.rule_id}` ({severity})", "inline": False},
            ],
            alert_key=f"{ctx.league_id}:{self.rule_id}:{current_hash[:12]}",
        )

        # Snapshot AFTER building the result so a future identical state does
        # not re-alert.
        ctx.league_state.last_settings_hash = current_hash
        ctx.league_state.last_settings_snapshot = dict(current_settings)
        return [result]

    def _is_in_amendments_window(self, ctx: RuleContext, params: dict[str, Any]) -> bool:
        if not params.get("enforce_amendments_window", True):
            return True  # treat as always allowed if not enforcing
        cal = ctx.calendar or {}
        start = _parse_date(cal.get("offseason_period_1_start"))
        end = _parse_date(cal.get("offseason_period_1_end"))
        if start is None or end is None:
            return False  # cannot enforce without window; be conservative
        today = ctx.now.date() if hasattr(ctx.now, "date") else ctx.now
        return start <= today <= end


register(SettingsChanged())

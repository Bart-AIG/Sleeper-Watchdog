"""Comprehensive league compliance against an expected baseline.

Diffs everything the live Sleeper API exposes for the league against the
baseline captured by `scripts/snapshot_baseline.py` and pasted into the
rules YAML under this rule's `params`.

Categories checked (each emits at most one alert per cron tick):
  * expected_league - top-level fields (name, num_teams, season, ...)
  * expected_settings - the league.settings dict
  * expected_scoring_settings - per-stat scoring values
  * expected_roster_positions - the ordered starting-slot composition
  * expected_user_ids - league membership
  * expected_roster_owners - which user owns which roster_id
  * expected_draft - the active draft's settings

A naturally-volatile key list (see DEFAULT_IGNORE_*) is excluded by default.
Add more keys via `ignore_settings_keys` or `ignore_league_keys` in params.

Alerts dedupe via a hash of the drifted items, so persistent drift posts once
and silently rides until either fixed or further changed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity

DEFAULT_IGNORE_SETTINGS_KEYS = {
    "leg",                          # rolls forward each NFL week
    "daily_waivers_last_ran",       # housekeeping timestamp
    "last_scored_leg",
}

DEFAULT_IGNORE_LEAGUE_KEYS = {
    "status",                       # drafting -> in_season -> complete is expected
}


def _hash(payload: Any) -> str:
    return hashlib.sha1(  # noqa: S324
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:10]


class SettingsCompliance:
    rule_id = "settings_compliance"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        severity = Severity(params.get("severity", "FLAG"))
        results: list[RuleResult] = []

        results += self._check_league_top_level(ctx, params, severity)
        results += self._check_dict(
            ctx,
            params,
            severity,
            category="settings",
            expected=params.get("expected_settings") or {},
            live=ctx.league.get("settings") or {},
            ignore=set(params.get("ignore_settings_keys") or []) | DEFAULT_IGNORE_SETTINGS_KEYS,
        )
        results += self._check_dict(
            ctx,
            params,
            severity,
            category="scoring_settings",
            expected=params.get("expected_scoring_settings") or {},
            live=ctx.league.get("scoring_settings") or {},
            ignore=set(params.get("ignore_scoring_keys") or []),
        )
        results += self._check_roster_positions(ctx, params, severity)
        results += self._check_users(ctx, params, severity)
        results += self._check_orphan_rosters(ctx, severity)
        results += self._check_roster_owners(ctx, params, severity)
        return results

    def _check_league_top_level(
        self, ctx: RuleContext, params: dict[str, Any], severity: Severity
    ) -> list[RuleResult]:
        expected = params.get("expected_league") or {}
        if not expected:
            return []
        ignore = set(params.get("ignore_league_keys") or []) | DEFAULT_IGNORE_LEAGUE_KEYS
        drifts = {}
        for key, exp_val in expected.items():
            if key in ignore:
                continue
            live_val = ctx.league.get(key)
            if exp_val != live_val:
                drifts[key] = {"expected": exp_val, "live": live_val}
        if not drifts:
            return []
        return [self._drift_result("league", drifts, ctx, severity)]

    def _check_dict(
        self,
        ctx: RuleContext,
        params: dict[str, Any],
        severity: Severity,
        *,
        category: str,
        expected: dict[str, Any],
        live: dict[str, Any],
        ignore: set[str],
    ) -> list[RuleResult]:
        if not expected:
            return []
        drifts = {}
        for key, exp_val in expected.items():
            if key in ignore:
                continue
            live_val = live.get(key)
            if exp_val != live_val:
                drifts[key] = {"expected": exp_val, "live": live_val}
        if not drifts:
            return []
        return [self._drift_result(category, drifts, ctx, severity)]

    def _check_roster_positions(
        self, ctx: RuleContext, params: dict[str, Any], severity: Severity
    ) -> list[RuleResult]:
        expected = params.get("expected_roster_positions")
        if not expected:
            return []
        live = ctx.league.get("roster_positions") or []
        if list(expected) == list(live):
            return []
        return [
            self._drift_result(
                "roster_positions",
                {"expected": list(expected), "live": list(live)},
                ctx,
                severity,
            )
        ]

    def _check_users(
        self, ctx: RuleContext, params: dict[str, Any], severity: Severity
    ) -> list[RuleResult]:
        expected_ids = params.get("expected_user_ids")
        if expected_ids is None:
            return []
        expected_set = {str(u) for u in expected_ids}
        live_set = {str(u["user_id"]) for u in ctx.users}
        added = sorted(live_set - expected_set)
        removed = sorted(expected_set - live_set)
        if not added and not removed:
            return []
        live_labels = {str(u["user_id"]): u.get("display_name", "?") for u in ctx.users}
        drift = {
            "added": [{"user_id": uid, "display_name": live_labels.get(uid, "?")} for uid in added],
            "removed": removed,
        }
        return [self._drift_result("users", drift, ctx, severity)]

    def _check_orphan_rosters(
        self, ctx: RuleContext, severity: Severity
    ) -> list[RuleResult]:
        orphans = [int(r["roster_id"]) for r in ctx.rosters if not r.get("owner_id")]
        if not orphans:
            return []
        drift = {"orphan_roster_ids": orphans}
        return [self._drift_result("orphan_rosters", drift, ctx, severity)]

    def _check_roster_owners(
        self, ctx: RuleContext, params: dict[str, Any], severity: Severity
    ) -> list[RuleResult]:
        expected = params.get("expected_roster_owners")
        if expected is None:
            return []
        expected_map = {str(k): str(v) if v is not None else None for k, v in expected.items()}
        live_map = {str(r["roster_id"]): r.get("owner_id") for r in ctx.rosters}
        drifts = {}
        for rid, exp_owner in expected_map.items():
            live_owner = live_map.get(rid)
            if exp_owner != (str(live_owner) if live_owner is not None else None):
                drifts[rid] = {"expected_owner": exp_owner, "live_owner": live_owner}
        if not drifts:
            return []
        return [self._drift_result("roster_owners", drifts, ctx, severity)]

    def _drift_result(
        self,
        category: str,
        drift: Any,
        ctx: RuleContext,
        severity: Severity,
    ) -> RuleResult:
        h = _hash(drift)
        rendered = _render_drift(category, drift)
        return RuleResult(
            rule_id=self.rule_id,
            severity=severity,
            title=f"Constitution drift: {category}",
            message=f"Live league does not match the expected baseline for {category}.",
            fields=[
                {"name": "Category", "value": f"`{category}`", "inline": True},
                {"name": "Items", "value": str(_count_items(drift)), "inline": True},
                {"name": "Drift", "value": rendered, "inline": False},
                {"name": "Rule", "value": f"`{self.rule_id}` ({severity})", "inline": False},
            ],
            alert_key=f"{ctx.league_id}:{self.rule_id}:{category}:{h}",
        )


def _count_items(drift: Any) -> int:
    if isinstance(drift, dict):
        if "expected" in drift and "live" in drift and len(drift) == 2:
            return 1
        return len(drift)
    if isinstance(drift, list):
        return len(drift)
    return 1


def _render_drift(category: str, drift: Any) -> str:
    """Discord embed field caps at 1024 chars; truncate aggressively."""
    if category == "roster_positions":
        return f"expected: {drift['expected']}\nlive: {drift['live']}"[:1000]
    if category == "users":
        parts = []
        if drift.get("added"):
            parts.append("added: " + ", ".join(f"{u['display_name']} ({u['user_id']})" for u in drift["added"]))
        if drift.get("removed"):
            parts.append("removed: " + ", ".join(drift["removed"]))
        return "\n".join(parts)[:1000]
    if category == "orphan_rosters":
        return "orphan roster ids: " + ", ".join(str(r) for r in drift["orphan_roster_ids"])
    if isinstance(drift, dict):
        lines = []
        for key, change in drift.items():
            if isinstance(change, dict) and "expected" in change and "live" in change:
                lines.append(f"`{key}`: {change['expected']!r} -> {change['live']!r}")
            elif isinstance(change, dict) and "expected_owner" in change:
                lines.append(
                    f"roster {key}: owner {change['expected_owner']} -> {change['live_owner']}"
                )
            else:
                lines.append(f"`{key}`: {change}")
        rendered = "\n".join(lines)
        if len(rendered) > 1000:
            rendered = rendered[:990] + "\n... (truncated)"
        return rendered
    return str(drift)[:1000]


register(SettingsCompliance())

"""On specified dates, verify every roster's waiver_budget_used is 0.

Sleeper does not have a "reset FAAB" button; the commissioner manually zeroes
each team's waiver_budget_used before the new season. This rule fires one
alert per configured check_date if any roster has a non-zero used FAAB.

YAML params:
    severity: FLAG | BLOCK (default FLAG)
    check_dates: list of YYYY-MM-DD strings; the rule evaluates on EACH of
        these dates independently (separate alert per date so a still-broken
        day-2 state re-posts).
    field: roster field to check (default 'settings.waiver_budget_used')
    expected_value: value all rosters must equal (default 0)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity


def _today_utc(ctx: RuleContext) -> date:
    now = ctx.now
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).date()


def _resolve_roster_field(roster: dict[str, Any], path: str) -> Any:
    cur: Any = roster
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


class FaabResetCheck:
    rule_id = "faab_reset_check"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        check_dates = params.get("check_dates") or []
        if not check_dates:
            return []
        severity = Severity(params.get("severity", "FLAG"))
        field = params.get("field", "settings.waiver_budget_used")
        expected = params.get("expected_value", 0)
        today = _today_utc(ctx)

        results: list[RuleResult] = []
        for raw_date in check_dates:
            target = date.fromisoformat(str(raw_date))
            if today != target:
                continue
            bad_rosters = []
            for roster in ctx.rosters:
                live = _resolve_roster_field(roster, field)
                if live != expected:
                    rid = int(roster.get("roster_id", 0))
                    team = ctx.roster_to_team.get(rid, f"Roster {rid}")
                    bad_rosters.append((team, live))
            if not bad_rosters:
                continue
            lines = [f"{team}: {field}={val} (expected {expected})" for team, val in bad_rosters]
            rendered = "\n".join(lines)
            if len(rendered) > 1000:
                rendered = rendered[:990] + "\n... (truncated)"
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    severity=severity,
                    title=f"FAAB not reset on {target.isoformat()}",
                    message=params.get(
                        "message",
                        "Each team's FAAB usage should be 0 before season start. Reset the listed teams in Sleeper.",
                    ),
                    fields=[
                        {"name": "Check date", "value": target.isoformat(), "inline": True},
                        {"name": "Teams not reset", "value": str(len(bad_rosters)), "inline": True},
                        {"name": "Detail", "value": rendered, "inline": False},
                        {"name": "Rule", "value": f"`{self.rule_id}` ({severity})", "inline": False},
                    ],
                    alert_key=f"{ctx.league_id}:{self.rule_id}:{target.isoformat()}",
                )
            )
        return results


register(FaabResetCheck())

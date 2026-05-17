"""Article XV: detect commissioner (or co-commish) additions/removals.

Sleeper marks commissioners with `is_owner: true` on the /users response.
Comparing the current set against last-seen detects any add or removal.
First sighting snapshots silently. Optional `expected_commissioners` param
adds a second check: anyone with is_owner=true who is NOT in the expected
list, or anyone in the expected list who is missing, also fires.
"""

from __future__ import annotations

from typing import Any

from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity


class CommishChange:
    rule_id = "commish_change"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        if ctx.league_state is None:
            return []

        severity = Severity(params.get("severity", "FLAG"))
        current_owners = sorted(
            str(u["user_id"]) for u in ctx.users if u.get("is_owner") is True
        )

        last_seen = list(ctx.league_state.last_commish_user_ids)
        if not last_seen:
            ctx.league_state.last_commish_user_ids = current_owners
            return []

        if current_owners == last_seen:
            return self._check_expected_list(ctx, params, current_owners, severity)

        added = sorted(set(current_owners) - set(last_seen))
        removed = sorted(set(last_seen) - set(current_owners))
        label_for = {str(u["user_id"]): _label(u) for u in ctx.users}

        message = params.get(
            "message", "Article XV: commissioner role assignments changed in Sleeper."
        )

        result = RuleResult(
            rule_id=self.rule_id,
            severity=severity,
            title="Commissioner change",
            message=message,
            fields=[
                {
                    "name": "Added",
                    "value": ", ".join(f"{label_for.get(u, u)} ({u})" for u in added) or "(none)",
                    "inline": False,
                },
                {
                    "name": "Removed",
                    "value": ", ".join(removed) or "(none)",
                    "inline": False,
                },
                {"name": "Now", "value": ", ".join(current_owners) or "(none)", "inline": False},
                {"name": "Rule", "value": f"`{self.rule_id}` ({severity})", "inline": False},
            ],
            alert_key=f"{ctx.league_id}:{self.rule_id}:{'-'.join(current_owners)}",
        )
        ctx.league_state.last_commish_user_ids = current_owners
        return [result]

    def _check_expected_list(
        self,
        ctx: RuleContext,
        params: dict[str, Any],
        current_owners: list[str],
        severity: Severity,
    ) -> list[RuleResult]:
        expected = params.get("expected_commissioners")
        if not expected:
            return []
        expected_set = {str(u) for u in expected if str(u) and "REPLACE" not in str(u).upper()}
        if not expected_set:
            return []
        current_set = set(current_owners)
        unexpected = sorted(current_set - expected_set)
        missing = sorted(expected_set - current_set)
        if not unexpected and not missing:
            return []
        label_for = {str(u["user_id"]): _label(u) for u in ctx.users}
        return [
            RuleResult(
                rule_id=self.rule_id,
                severity=severity,
                title="Commissioner list does not match expected",
                message="Per constitution, only the expected commissioner(s) should hold the role.",
                fields=[
                    {
                        "name": "Unexpected",
                        "value": ", ".join(f"{label_for.get(u, u)} ({u})" for u in unexpected) or "(none)",
                        "inline": False,
                    },
                    {"name": "Missing", "value": ", ".join(missing) or "(none)", "inline": False},
                    {"name": "Rule", "value": f"`{self.rule_id}` ({severity})", "inline": False},
                ],
                alert_key=f"{ctx.league_id}:{self.rule_id}:expected:{'-'.join(sorted(current_owners))}",
            )
        ]


def _label(user: dict[str, Any]) -> str:
    md = user.get("metadata") or {}
    team_name = md.get("team_name")
    display = user.get("display_name")
    return team_name or display or user.get("user_id", "?")


register(CommishChange())

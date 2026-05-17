"""Article VII: roster size limits.

Sleeper enforces position composition; we belt-and-suspenders the total counts:
  - active players (starters + bench): max_active (default 28 = 11 + 17)
  - IR slots (reserve list): max_ir (default 4)
  - taxi squad: max_taxi (default 3)

One alert per roster that violates any limit. The alert key includes a hash of
the violated counts so a roster that gets fixed and re-broken triggers again.
"""

from __future__ import annotations

import hashlib
from typing import Any

from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity


class RosterSize:
    rule_id = "roster_size"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        max_active = int(params.get("max_active", 28))
        max_ir = int(params.get("max_ir", 4))
        max_taxi = int(params.get("max_taxi", 3))
        severity = Severity(params.get("severity", "FLAG"))

        results: list[RuleResult] = []
        for roster in ctx.rosters:
            active = len(roster.get("players") or [])
            ir = len(roster.get("reserve") or [])
            taxi = len(roster.get("taxi") or [])
            issues: list[str] = []
            if active > max_active:
                issues.append(f"active {active} > {max_active}")
            if ir > max_ir:
                issues.append(f"IR {ir} > {max_ir}")
            if taxi > max_taxi:
                issues.append(f"taxi {taxi} > {max_taxi}")
            if not issues:
                continue

            roster_id = int(roster["roster_id"])
            team = ctx.roster_to_team.get(roster_id, f"Roster {roster_id}")
            counts_hash = hashlib.sha1(  # noqa: S324  not security-sensitive
                f"{active}-{ir}-{taxi}".encode()
            ).hexdigest()[:8]

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    severity=severity,
                    title=f"Roster size violation: {team}",
                    message="; ".join(issues),
                    fields=[
                        {"name": "Team", "value": team, "inline": True},
                        {"name": "Active", "value": f"{active} / {max_active}", "inline": True},
                        {"name": "IR", "value": f"{ir} / {max_ir}", "inline": True},
                        {"name": "Taxi", "value": f"{taxi} / {max_taxi}", "inline": True},
                        {"name": "Rule", "value": f"`{self.rule_id}` ({severity})", "inline": False},
                    ],
                    alert_key=f"{ctx.league_id}:{self.rule_id}:{roster_id}:{counts_hash}",
                )
            )
        return results


register(RosterSize())

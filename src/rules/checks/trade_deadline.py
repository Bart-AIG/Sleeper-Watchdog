"""Article XI: trades suspended starting Week N (default 13).

Looks at every transaction of type=trade with status=complete. Sleeper's
transaction object includes a `leg` field which equals the NFL week the trade
was filed under. A trade whose leg >= deadline_week is in violation.
"""

from __future__ import annotations

from typing import Any

from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity


class TradeDeadline:
    rule_id = "trade_deadline"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        deadline_week = int(params.get("deadline_week", 13))
        severity = Severity(params.get("severity", "BLOCK"))
        message = params.get("message", f"Trade after Week {deadline_week} deadline.")

        results: list[RuleResult] = []
        for tx in ctx.transactions:
            if tx.get("type") != "trade" or tx.get("status") != "complete":
                continue
            tx_week = int(tx.get("leg", 0))
            if tx_week < deadline_week:
                continue

            tx_id = str(tx.get("transaction_id", ""))
            roster_labels = ", ".join(
                ctx.roster_to_team.get(int(r), f"Roster {r}")
                for r in (tx.get("roster_ids") or [])
            )
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    severity=severity,
                    title=f"Trade after Week {deadline_week} deadline",
                    message=message,
                    fields=[
                        {"name": "Transaction", "value": f"`{tx_id}`", "inline": True},
                        {"name": "Filed in week", "value": str(tx_week), "inline": True},
                        {"name": "Teams", "value": roster_labels or "?", "inline": False},
                        {"name": "Rule", "value": f"`{self.rule_id}` ({severity})", "inline": False},
                    ],
                    alert_key=f"{ctx.league_id}:{tx_id}:{self.rule_id}",
                )
            )
        return results


register(TradeDeadline())

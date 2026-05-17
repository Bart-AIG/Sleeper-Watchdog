"""Article XI: flag trades whose value imbalance exceeds a threshold.

Uses FantasyCalc dynasty values via ctx.fantasycalc. Implementation note: the
informational grade card on every trade is built in src/main.py during the
transaction post; this rule is the separate threshold-based warning.
"""

from __future__ import annotations

from typing import Any

from src.fantasycalc import grade_trade, trade_imbalance_percent
from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity


class LopsidedTrade:
    rule_id = "lopsided_trade"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        if ctx.fantasycalc is None:
            return []
        threshold_pct = float(params.get("value_diff_threshold_pct", 35))
        severity = Severity(params.get("severity", "FLAG"))
        message = params.get(
            "message", f"Trade value imbalance > {threshold_pct}% per FantasyCalc dynasty values."
        )

        results: list[RuleResult] = []
        for tx in ctx.transactions:
            if tx.get("type") != "trade" or tx.get("status") != "complete":
                continue
            grades = grade_trade(tx, ctx.fantasycalc)
            imbalance = trade_imbalance_percent(grades)
            if imbalance < threshold_pct:
                continue

            tx_id = str(tx.get("transaction_id", ""))
            grade_lines = [
                f"{ctx.roster_to_team.get(rid, f'Roster {rid}')}: sent {g['sent']:,}, "
                f"received {g['received']:,}, net {g['net']:+,}"
                for rid, g in grades.items()
            ]
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    severity=severity,
                    title=f"Lopsided trade ({imbalance:.0f}% imbalance)",
                    message=message,
                    fields=[
                        {"name": "Transaction", "value": f"`{tx_id}`", "inline": False},
                        {"name": "Imbalance", "value": f"{imbalance:.1f}%", "inline": True},
                        {"name": "Threshold", "value": f"{threshold_pct:.0f}%", "inline": True},
                        {"name": "Per-team", "value": "\n".join(grade_lines), "inline": False},
                        {"name": "Rule", "value": f"`{self.rule_id}` ({severity})", "inline": False},
                    ],
                    alert_key=f"{ctx.league_id}:{tx_id}:{self.rule_id}",
                )
            )
        return results


register(LopsidedTrade())

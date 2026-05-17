"""Article V: pick trades only allowed inside a configured calendar window.

Disabled in the 512 Dynasty constitution (no restrictions on pick trades). The
implementation is here so leagues with restrictions can enable it by setting
`enabled: true` plus `params.window_start` and `params.window_end`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


class PickTradeWindow:
    rule_id = "pick_trade_window"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        window_start = _parse_date(params.get("window_start"))
        window_end = _parse_date(params.get("window_end"))
        if window_start is None or window_end is None:
            return []

        severity = Severity(params.get("severity", "FLAG"))
        message = params.get(
            "message",
            f"Pick trade outside allowed window {window_start} to {window_end}.",
        )

        results: list[RuleResult] = []
        for tx in ctx.transactions:
            if tx.get("type") != "trade" or tx.get("status") != "complete":
                continue
            if not tx.get("draft_picks"):
                continue

            created_ms = tx.get("created")
            if created_ms is None:
                continue
            tx_date = datetime.fromtimestamp(int(created_ms) / 1000, tz=timezone.utc).date()
            if window_start <= tx_date <= window_end:
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
                    title="Pick trade outside allowed window",
                    message=message,
                    fields=[
                        {"name": "Transaction", "value": f"`{tx_id}`", "inline": True},
                        {"name": "Date", "value": tx_date.isoformat(), "inline": True},
                        {"name": "Window", "value": f"{window_start} - {window_end}", "inline": False},
                        {"name": "Teams", "value": roster_labels or "?", "inline": False},
                        {"name": "Rule", "value": f"`{self.rule_id}` ({severity})", "inline": False},
                    ],
                    alert_key=f"{ctx.league_id}:{tx_id}:{self.rule_id}",
                )
            )
        return results


register(PickTradeWindow())

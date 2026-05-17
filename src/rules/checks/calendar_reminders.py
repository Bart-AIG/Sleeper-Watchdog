"""Calendar-driven reminders: alert when a date passes, an NFL week arrives,
or a date passed and an expected setting still does not match.

Configured in the rules YAML under this rule's `params.reminders` as a list
of reminder definitions. Each fires at most once per occurrence; dedup via
alert_key includes the reminder id and the season year so a reminder reset
the next season fires again.

Supported reminder types:

    date_reached
      Fires once when current UTC date >= `date` (YYYY-MM-DD).
      Use for: "Off-Season Period 1 has ended."

    days_before_date
      Fires once when current UTC date is within `days` of `date`.
      Use for: "Trade deadline is 7 days away."

    nfl_week_reached
      Fires once when ctx.nfl_state.week >= `week`.
      Use for: "Trade deadline starts next week (Week 13)."

    date_passed_and_setting_not
      Fires when current date >= `after_date` AND the live league setting at
      `setting_path` (dotted: "settings.disable_adds" or just "disable_adds"
      which defaults to settings.<key>) does NOT equal `expected_value`.
      Use for: "Free agency should be open by 2026-05-20 but disable_adds=1."
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity


def _today_utc(ctx: RuleContext) -> date:
    now = ctx.now
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).date()


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _resolve_setting(ctx: RuleContext, path: str) -> Any:
    """Look up a dotted path on the league dict; bare keys default to settings.<key>."""
    if "." in path:
        head, _, tail = path.partition(".")
        node = ctx.league.get(head)
        if not isinstance(node, dict):
            return None
        return _resolve_dotted(node, tail)
    return (ctx.league.get("settings") or {}).get(path)


def _resolve_dotted(node: dict[str, Any], path: str) -> Any:
    cur: Any = node
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


class CalendarReminders:
    rule_id = "calendar_reminders"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        reminders = params.get("reminders") or []
        if not reminders:
            return []

        default_severity = Severity(params.get("severity", "FLAG"))
        season = str(ctx.nfl_state.get("season") or (ctx.calendar or {}).get("current_nfl_season") or _today_utc(ctx).year)
        today = _today_utc(ctx)

        results: list[RuleResult] = []
        for rem in reminders:
            rid = rem.get("id")
            if not rid:
                continue
            rtype = rem.get("type")
            severity = Severity(rem.get("severity", default_severity))
            message = rem.get("message") or rid

            result = self._dispatch(rtype, rem, ctx, today, season, severity, message)
            if result is not None:
                results.append(result)
        return results

    def _dispatch(
        self,
        rtype: str | None,
        rem: dict[str, Any],
        ctx: RuleContext,
        today: date,
        season: str,
        severity: Severity,
        message: str,
    ) -> RuleResult | None:
        rid = rem["id"]

        if rtype == "date_reached":
            target = _parse_date(rem["date"])
            if today < target:
                return None
            return self._make(rid, severity, message, season, ctx, extra={"target_date": target.isoformat()})

        if rtype == "days_before_date":
            target = _parse_date(rem["date"])
            days = int(rem.get("days", 7))
            window_start = target - timedelta(days=days)
            if today < window_start or today > target:
                return None
            return self._make(
                rid,
                severity,
                message,
                season,
                ctx,
                extra={"target_date": target.isoformat(), "days_remaining": (target - today).days},
            )

        if rtype == "nfl_week_reached":
            target_week = int(rem["week"])
            current_week = int(ctx.nfl_state.get("week", 0))
            if current_week < target_week:
                return None
            return self._make(
                rid,
                severity,
                message,
                season,
                ctx,
                extra={"target_week": target_week, "current_week": current_week},
            )

        if rtype == "date_passed_and_setting_not":
            after_date = _parse_date(rem["after_date"])
            if today < after_date:
                return None
            setting_path = rem["setting_path"]
            expected_value = rem["expected_value"]
            live_value = _resolve_setting(ctx, setting_path)
            if live_value == expected_value:
                return None
            return self._make(
                rid,
                severity,
                message,
                season,
                ctx,
                extra={
                    "after_date": after_date.isoformat(),
                    "setting_path": setting_path,
                    "expected": expected_value,
                    "live": live_value,
                },
            )

        return None

    def _make(
        self,
        rid: str,
        severity: Severity,
        message: str,
        season: str,
        ctx: RuleContext,
        extra: dict[str, Any],
    ) -> RuleResult:
        fields = [{"name": k, "value": str(v), "inline": True} for k, v in extra.items()]
        fields.append({"name": "Reminder", "value": f"`{rid}` ({season})", "inline": False})
        return RuleResult(
            rule_id=self.rule_id,
            severity=severity,
            title=f"Calendar reminder: {rid}",
            message=message,
            fields=fields,
            alert_key=f"{ctx.league_id}:{self.rule_id}:{rid}:{season}",
        )


register(CalendarReminders())

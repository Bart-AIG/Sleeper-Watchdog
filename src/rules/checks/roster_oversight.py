"""Article XIV: detect empty starting slots when an eligible bench replacement
exists.

This is the high-value check the constitution explicitly assigns to the
commissioner. Sleeper does not do this for you. Only fires when the league
is in_season; pre-season there are no lineups to compare.

For each roster:
  walk positional starting slots (the slot is empty if the entry is '0')
  for each empty slot, look at the bench (active roster minus starters)
  if any bench player is at a matching position and not in an excluded
    injury status, FLAG and accrue a strike against the manager

Strike tracking lives on LeagueState.strikes_by_user. The rule appends a new
Strike record per oversight occurrence. A second alert escalates to BLOCK
when the user crosses max_strikes_before_removal (default 3) for the season.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.rules.engine import RuleContext, register
from src.rules.result import RuleResult, Severity
from src.state import Strike, StrikeRecord

DEFAULT_EXCLUDED_INJURY = {"Out", "IR", "Doubtful", "PUP", "Suspended"}
FLEX_SLOTS = {
    "FLEX": {"RB", "WR", "TE"},
    "REC_FLEX": {"WR", "TE"},
    "WRRB_FLEX": {"WR", "RB"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "IDP_FLEX": {"DL", "LB", "DB"},
}


def _slot_matches(slot: str, fantasy_positions: list[str]) -> bool:
    if slot in FLEX_SLOTS:
        return any(p in FLEX_SLOTS[slot] for p in fantasy_positions)
    return slot in fantasy_positions


def _is_starting_slot(slot: str) -> bool:
    return slot not in {"BN", "IR", "TAXI"}


class RosterOversight:
    rule_id = "roster_oversight"

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]:
        if ctx.league_state is None:
            return []
        if ctx.league.get("status") != "in_season":
            return []

        excluded = set(
            (params.get("eligible_replacement_filters") or {}).get(
                "exclude_injury_statuses", DEFAULT_EXCLUDED_INJURY
            )
        )
        max_strikes = int(
            (params.get("strike_tracking") or {}).get("max_strikes_before_removal", 3)
        )
        strike_tracking_enabled = bool(
            (params.get("strike_tracking") or {}).get("enabled", True)
        )

        roster_positions = ctx.league.get("roster_positions") or []
        season = int(ctx.nfl_state.get("season") or ctx.now.year)
        week = int(ctx.nfl_state.get("week") or 0)
        results: list[RuleResult] = []

        for roster in ctx.rosters:
            roster_id = int(roster["roster_id"])
            owner_id = str(roster.get("owner_id") or "")
            team = ctx.roster_to_team.get(roster_id, f"Roster {roster_id}")
            starters = roster.get("starters") or []
            all_players = set(str(p) for p in (roster.get("players") or []))
            bench = all_players - {str(s) for s in starters} - set(roster.get("reserve") or []) - set(roster.get("taxi") or [])

            for idx, starter_id in enumerate(starters):
                if str(starter_id) != "0":
                    continue
                if idx >= len(roster_positions):
                    continue
                slot = roster_positions[idx]
                if not _is_starting_slot(slot):
                    continue

                replacement_ids = []
                for bench_pid in bench:
                    player = ctx.players.get(str(bench_pid)) or {}
                    if player.get("injury_status") in excluded:
                        continue
                    fps = player.get("fantasy_positions") or [player.get("position")]
                    fps = [p for p in fps if p]
                    if _slot_matches(slot, fps):
                        replacement_ids.append((bench_pid, player.get("name") or bench_pid))

                if not replacement_ids:
                    continue

                strike_no = self._record_strike(
                    ctx, owner_id, season, week, roster_id, slot, strike_tracking_enabled
                )
                severity = Severity.BLOCK if strike_no >= max_strikes else Severity.FLAG
                summary = ", ".join(name for _, name in replacement_ids[:5])
                if len(replacement_ids) > 5:
                    summary += f" (+{len(replacement_ids) - 5} more)"

                title = f"Open {slot} for {team}"
                if strike_no >= max_strikes:
                    title += f" - strike {strike_no} of {max_strikes} (removal recommended)"
                else:
                    title += f" - strike {strike_no} of {max_strikes}"

                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        severity=severity,
                        title=title,
                        message=params.get(
                            "message",
                            "Article XIV: open starting slot detected with eligible bench replacement.",
                        ),
                        fields=[
                            {"name": "Team", "value": team, "inline": True},
                            {"name": "Slot", "value": slot, "inline": True},
                            {"name": "Week", "value": str(week), "inline": True},
                            {
                                "name": "Eligible bench replacements",
                                "value": summary,
                                "inline": False,
                            },
                            {
                                "name": "Strike total this season",
                                "value": f"{strike_no} of {max_strikes}",
                                "inline": False,
                            },
                            {
                                "name": "Rule",
                                "value": f"`{self.rule_id}` ({severity})",
                                "inline": False,
                            },
                        ],
                        # Dedup by season+week+roster+slot so the same oversight
                        # in the same week does not double-post on the next tick.
                        alert_key=f"{ctx.league_id}:{self.rule_id}:{season}:wk{week}:r{roster_id}:{slot}",
                    )
                )

        return results

    def _record_strike(
        self,
        ctx: RuleContext,
        user_id: str,
        season: int,
        week: int,
        roster_id: int,
        slot: str,
        enabled: bool,
    ) -> int:
        if not enabled or not user_id or ctx.league_state is None:
            return 1
        record = ctx.league_state.strikes_by_user.get(user_id)
        if record is None or record.season != season:
            record = StrikeRecord(season=season)
            ctx.league_state.strikes_by_user[user_id] = record
        # De-dup: only one strike per (season, week, roster, slot).
        already = any(
            s.week == week and s.roster_id == roster_id and s.position == slot
            for s in record.strikes
        )
        if not already:
            record.strikes.append(
                Strike(
                    season=season,
                    week=week,
                    roster_id=roster_id,
                    position=slot,
                    occurred_at=datetime.now(timezone.utc),
                )
            )
        return len(record.strikes)


register(RosterOversight())

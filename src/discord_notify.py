"""Post embeds to a Discord webhook.

Stateless: callers construct an embed dict and hand it to `DiscordNotifier.post`.
The notifier owns the HTTP client and the webhook URL, nothing else.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

COLOR_GREEN = 0x57F287
COLOR_BLUE = 0x3498DB
COLOR_YELLOW = 0xF1C40F
COLOR_RED = 0xE74C3C


class DiscordNotifier:
    """Thin wrapper around a single Discord webhook URL."""

    def __init__(self, webhook_url: str, client: httpx.Client | None = None) -> None:
        self._webhook_url = webhook_url
        self._client = client or httpx.Client(timeout=10.0)
        self._owns_client = client is None

    def __enter__(self) -> DiscordNotifier:
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._owns_client:
            self._client.close()

    def post(self, embed: dict[str, Any], username: str = "Sleeper Watchdog") -> None:
        """POST one embed. Raises httpx.HTTPStatusError on 4xx/5xx."""
        payload = {"username": username, "embeds": [embed]}
        response = self._client.post(self._webhook_url, json=payload)
        response.raise_for_status()
        log.info("discord.posted", title=embed.get("title"), status=response.status_code)


def build_draft_complete_embed(
    draft: dict[str, Any],
    league_id: str,
    league_name: str,
    waivers_target_date: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One-off embed when a draft transitions to status == complete."""
    ts = now or datetime.now(timezone.utc)
    season = draft.get("season", "")
    draft_id = str(draft.get("draft_id", ""))
    rounds = (draft.get("settings") or {}).get("rounds")
    return {
        "title": f"{season} draft complete - {league_name}",
        "description": f"All picks are in for the {season} draft ({rounds} rounds).",
        "color": COLOR_GREEN,
        "fields": [
            {"name": "Waivers should open", "value": waivers_target_date, "inline": True},
            {"name": "Draft", "value": f"[Open in Sleeper](https://sleeper.com/draft/nfl/{draft_id})", "inline": True},
        ],
        "footer": {"text": f"Sleeper Watchdog · {ts.strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def build_hello_embed(now: datetime | None = None) -> dict[str, Any]:
    """Phase 1 'watchdog online' heartbeat. Kept for manual testing."""
    ts = now or datetime.now(timezone.utc)
    return {
        "title": "Watchdog online",
        "description": "Heartbeat from the GitHub Actions cron job.",
        "color": COLOR_GREEN,
        "footer": {"text": f"Sleeper Watchdog · {ts.strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def build_transaction_embed(
    tx: dict[str, Any],
    league_id: str,
    league_name: str,
    roster_to_team: dict[int, str],
    players: dict[str, dict[str, Any]],
    trade_grade: dict[int, dict[str, Any]] | None = None,
    imbalance_percent: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a Discord embed describing one Sleeper transaction.

    Phase 2: descriptive only, no rule verdicts. The shape stays consistent so
    Phase 3 can layer severity colors and rule fields on top.
    """
    ts = now or datetime.now(timezone.utc)
    tx_type = tx.get("type", "transaction")
    tx_id = str(tx.get("transaction_id", ""))
    status = tx.get("status", "")
    color = COLOR_BLUE if status == "complete" else COLOR_YELLOW

    teams_field = _format_teams(tx, roster_to_team)
    fields: list[dict[str, Any]] = [
        {"name": "Type", "value": tx_type, "inline": True},
        {"name": "Status", "value": status or "?", "inline": True},
        {"name": "Teams", "value": teams_field or "?", "inline": False},
    ]

    adds_lines = _format_player_moves(tx.get("adds") or {}, players, roster_to_team, "+")
    drops_lines = _format_player_moves(tx.get("drops") or {}, players, roster_to_team, "-")
    if adds_lines:
        fields.append({"name": "Adds", "value": "\n".join(adds_lines), "inline": False})
    if drops_lines:
        fields.append({"name": "Drops", "value": "\n".join(drops_lines), "inline": False})

    picks_lines = _format_picks(tx.get("draft_picks") or [], roster_to_team)
    if picks_lines:
        fields.append({"name": "Draft picks", "value": "\n".join(picks_lines), "inline": False})

    faab_lines = _format_waiver_budget(tx.get("waiver_budget") or [], roster_to_team)
    if faab_lines:
        fields.append({"name": "FAAB", "value": "\n".join(faab_lines), "inline": False})

    if trade_grade:
        grade_lines = []
        for rid, g in trade_grade.items():
            team = roster_to_team.get(int(rid), f"Roster {rid}")
            grade_lines.append(
                f"**{team}**: sent {g['sent']:,}, received {g['received']:,}, net {g['net']:+,}"
            )
        if imbalance_percent is not None:
            grade_lines.append(f"\nImbalance: **{imbalance_percent:.1f}%** (FantasyCalc dynasty SF)")
        fields.append({"name": "Trade values", "value": "\n".join(grade_lines), "inline": False})

    fields.append(
        {
            "name": "Link",
            "value": f"[Open in Sleeper](https://sleeper.com/leagues/{league_id}/transactions)",
            "inline": False,
        }
    )

    return {
        "title": f"{tx_type.title()} in {league_name}",
        "description": f"Transaction `{tx_id}`",
        "color": color,
        "fields": fields,
        "footer": {"text": f"Sleeper Watchdog · {ts.strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def _team_label(roster_id: int, roster_to_team: dict[int, str]) -> str:
    return roster_to_team.get(roster_id, f"Roster {roster_id}")


def _format_teams(tx: dict[str, Any], roster_to_team: dict[int, str]) -> str:
    roster_ids = tx.get("roster_ids") or []
    return ", ".join(_team_label(int(r), roster_to_team) for r in roster_ids)


def _player_label(player_id: str, players: dict[str, dict[str, Any]]) -> str:
    p = players.get(player_id) or {}
    name = p.get("name") or player_id
    pos = p.get("position")
    team = p.get("team")
    suffix_parts = [x for x in (pos, team) if x]
    return f"{name} ({', '.join(suffix_parts)})" if suffix_parts else name


def _format_player_moves(
    moves: dict[str, int],
    players: dict[str, dict[str, Any]],
    roster_to_team: dict[int, str],
    prefix: str,
) -> list[str]:
    return [
        f"{prefix} {_player_label(pid, players)} -> {_team_label(int(rid), roster_to_team)}"
        for pid, rid in moves.items()
    ]


def _format_picks(picks: list[dict[str, Any]], roster_to_team: dict[int, str]) -> list[str]:
    lines = []
    for pick in picks:
        season = pick.get("season")
        rnd = pick.get("round")
        new_owner = _team_label(int(pick.get("owner_id", 0)), roster_to_team)
        prev_owner = _team_label(int(pick.get("previous_owner_id", 0)), roster_to_team)
        lines.append(f"{season} round {rnd}: {prev_owner} -> {new_owner}")
    return lines


def build_rule_alert_embed(
    rule_result: Any,
    league_id: str,
    league_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Embed for a rule violation. Color is driven by severity."""
    ts = now or datetime.now(timezone.utc)
    severity = str(rule_result.severity).upper()
    color = {
        "BLOCK": COLOR_RED,
        "FLAG": COLOR_YELLOW,
        "PASS": COLOR_GREEN,
    }.get(severity, COLOR_BLUE)

    fields = list(rule_result.fields)
    fields.append(
        {
            "name": "League",
            "value": f"[{league_name}](https://sleeper.com/leagues/{league_id})",
            "inline": False,
        }
    )

    return {
        "title": f"[{severity}] {rule_result.title}",
        "description": rule_result.message,
        "color": color,
        "fields": fields,
        "footer": {"text": f"Sleeper Watchdog · {ts.strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def build_draft_pick_embed(
    pick: dict[str, Any],
    draft: dict[str, Any],
    league_id: str,
    league_name: str,
    roster_to_team: dict[int, str],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a Discord embed describing one draft pick.

    Pick metadata already includes player name/team/position so we do not need
    the players cache here.
    """
    ts = now or datetime.now(timezone.utc)
    overall = pick.get("pick_no")
    rnd = pick.get("round")
    slot = pick.get("draft_slot")
    roster_id = pick.get("roster_id")
    team_label = (
        roster_to_team.get(int(roster_id), f"Roster {roster_id}")
        if roster_id is not None
        else "?"
    )

    md = pick.get("metadata") or {}
    player_name = f"{md.get('first_name', '')} {md.get('last_name', '')}".strip() or pick.get(
        "player_id", "?"
    )
    position = md.get("position") or "?"
    nfl_team = md.get("team") or "FA"

    is_keeper = bool(pick.get("is_keeper"))
    keeper_suffix = " (keeper)" if is_keeper else ""

    draft_id = str(pick.get("draft_id") or draft.get("draft_id", ""))
    season = draft.get("season", "")

    fields: list[dict[str, Any]] = [
        {"name": "Team", "value": team_label, "inline": True},
        {"name": "Player", "value": f"{player_name} ({position}, {nfl_team}){keeper_suffix}", "inline": True},
        {"name": "Pick", "value": f"Round {rnd}, slot {slot} (overall #{overall})", "inline": False},
        {
            "name": "Link",
            "value": f"[Open draft in Sleeper](https://sleeper.com/draft/nfl/{draft_id})",
            "inline": False,
        },
    ]

    return {
        "title": f"{season} Pick {rnd}.{int(slot):02d} - {league_name}",
        "description": f"Overall #{overall}: {team_label} selects {player_name}",
        "color": COLOR_BLUE,
        "fields": fields,
        "footer": {"text": f"Sleeper Watchdog · {ts.strftime('%Y-%m-%d %H:%M UTC')}"},
    }


def _format_waiver_budget(
    moves: list[dict[str, Any]], roster_to_team: dict[int, str]
) -> list[str]:
    lines = []
    for m in moves:
        sender = _team_label(int(m.get("sender", 0)), roster_to_team)
        receiver = _team_label(int(m.get("receiver", 0)), roster_to_team)
        amount = m.get("amount", 0)
        lines.append(f"${amount} FAAB: {sender} -> {receiver}")
    return lines

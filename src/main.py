"""Sleeper Watchdog entry point.

Phase 2 scope: poll the configured leagues for new transactions and draft picks
and post each to Discord. First sighting of a league or a draft bootstraps
silently (records current ids without posting) so we do not spam the channel
on day one.

Run with: python -m src.main
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.discord_notify import (
    DiscordNotifier,
    build_draft_pick_embed,
    build_transaction_embed,
)
from src.sleeper import SleeperClient, effective_transaction_week
from src.state import LeagueState, WatchdogState, load_state, now_utc, save_state

CONFIG_PATH = Path("config/leagues.yaml")


class Settings(BaseSettings):
    """Runtime config loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_webhook_url: str = Field(..., alias="DISCORD_WEBHOOK_URL")


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def load_league_configs(path: Path = CONFIG_PATH) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [lg for lg in data.get("leagues", []) if lg.get("active", True)]


def build_roster_to_team(
    rosters: list[dict[str, Any]], users: list[dict[str, Any]]
) -> dict[int, str]:
    user_label = {u["user_id"]: _user_label(u) for u in users}
    return {
        int(r["roster_id"]): user_label.get(r.get("owner_id") or "", f"Roster {r['roster_id']}")
        for r in rosters
    }


def _user_label(user: dict[str, Any]) -> str:
    team_name = (user.get("metadata") or {}).get("team_name")
    display = user.get("display_name")
    if team_name and display:
        return f"{team_name} ({display})"
    return team_name or display or user.get("user_id", "?")


class RosterLookup:
    """Lazily fetch users/rosters and cache the roster_id -> team-name map."""

    def __init__(self, sleeper: SleeperClient, league_id: str) -> None:
        self._sleeper = sleeper
        self._league_id = league_id
        self._map: dict[int, str] | None = None

    def get(self) -> dict[int, str]:
        if self._map is None:
            users = self._sleeper.get_users(self._league_id)
            rosters = self._sleeper.get_rosters(self._league_id)
            self._map = build_roster_to_team(rosters, users)
        return self._map


def process_transactions(
    league_cfg: dict[str, Any],
    league_state: LeagueState,
    sleeper: SleeperClient,
    notifier: DiscordNotifier,
    roster_lookup: RosterLookup,
    week: int,
    log: structlog.BoundLogger,
) -> int:
    league_id = str(league_cfg["id"])
    league_name = league_cfg.get("name") or league_id
    transactions = sleeper.get_transactions(league_id, week)

    seen = set(league_state.seen_transaction_ids)
    new_txs = [tx for tx in transactions if str(tx["transaction_id"]) not in seen]

    if new_txs:
        players = sleeper.get_players()
        for tx in new_txs:
            embed = build_transaction_embed(
                tx=tx,
                league_id=league_id,
                league_name=league_name,
                roster_to_team=roster_lookup.get(),
                players=players,
            )
            notifier.post(embed)
            league_state.seen_transaction_ids.append(str(tx["transaction_id"]))

    log.info("transactions.processed", total=len(transactions), new=len(new_txs))
    return len(new_txs)


def process_drafts(
    league_cfg: dict[str, Any],
    league_state: LeagueState,
    sleeper: SleeperClient,
    notifier: DiscordNotifier,
    roster_lookup: RosterLookup,
    log: structlog.BoundLogger,
) -> int:
    league_id = str(league_cfg["id"])
    league_name = league_cfg.get("name") or league_id
    drafts = sleeper.get_drafts(league_id)
    total_new = 0

    for draft in drafts:
        draft_id = str(draft["draft_id"])
        picks = sleeper.get_draft_picks(draft_id)

        if draft_id not in league_state.seen_draft_ids:
            league_state.seen_draft_ids.append(draft_id)
            league_state.seen_draft_pick_keys.extend(
                f"{draft_id}:{p['pick_no']}" for p in picks
            )
            log.info("draft.bootstrapped", draft_id=draft_id, recorded=len(picks))
            continue

        seen = set(league_state.seen_draft_pick_keys)
        new_picks = [p for p in picks if f"{draft_id}:{p['pick_no']}" not in seen]

        for pick in new_picks:
            embed = build_draft_pick_embed(
                pick=pick,
                draft=draft,
                league_id=league_id,
                league_name=league_name,
                roster_to_team=roster_lookup.get(),
            )
            notifier.post(embed)
            league_state.seen_draft_pick_keys.append(f"{draft_id}:{pick['pick_no']}")

        if new_picks:
            log.info("draft.processed", draft_id=draft_id, new=len(new_picks))
        total_new += len(new_picks)

    return total_new


def process_league(
    league_cfg: dict[str, Any],
    state: WatchdogState,
    sleeper: SleeperClient,
    notifier: DiscordNotifier,
    log: structlog.BoundLogger,
) -> None:
    league_id = str(league_cfg["id"])
    league_name = league_cfg.get("name") or league_id
    league_state = state.league(league_id)

    nfl_state = sleeper.get_nfl_state()
    week = effective_transaction_week(nfl_state)
    log = log.bind(league_id=league_id, league=league_name, week=week)

    if not league_state.is_bootstrapped():
        transactions = sleeper.get_transactions(league_id, week)
        league_state.bootstrapped_at = now_utc()
        league_state.last_run_at = now_utc()
        league_state.current_nfl_week = int(nfl_state.get("week", 0))
        league_state.seen_transaction_ids = [str(tx["transaction_id"]) for tx in transactions]

        for draft in sleeper.get_drafts(league_id):
            draft_id = str(draft["draft_id"])
            picks = sleeper.get_draft_picks(draft_id)
            league_state.seen_draft_ids.append(draft_id)
            league_state.seen_draft_pick_keys.extend(
                f"{draft_id}:{p['pick_no']}" for p in picks
            )

        log.info(
            "league.bootstrapped",
            tx_recorded=len(league_state.seen_transaction_ids),
            drafts_recorded=len(league_state.seen_draft_ids),
            picks_recorded=len(league_state.seen_draft_pick_keys),
        )
        return

    roster_lookup = RosterLookup(sleeper, league_id)
    new_tx = process_transactions(
        league_cfg, league_state, sleeper, notifier, roster_lookup, week, log
    )
    new_picks = process_drafts(
        league_cfg, league_state, sleeper, notifier, roster_lookup, log
    )

    league_state.last_run_at = now_utc()
    league_state.current_nfl_week = int(nfl_state.get("week", 0))
    log.info("league.processed", new_tx=new_tx, new_picks=new_picks)


def run(settings: Settings) -> int:
    log = structlog.get_logger("watchdog")
    log.info("watchdog.start", phase=2)

    leagues = load_league_configs()
    if not leagues:
        log.warning("no_active_leagues")
        return 0

    state = load_state()
    with SleeperClient() as sleeper, DiscordNotifier(settings.discord_webhook_url) as notifier:
        for league_cfg in leagues:
            try:
                process_league(league_cfg, state, sleeper, notifier, log)
            except Exception:
                log.exception("league.failed", league_id=league_cfg.get("id"))
                raise
    save_state(state)

    log.info("watchdog.done")
    return 0


def main() -> int:
    configure_logging()
    settings = Settings()  # type: ignore[call-arg]
    return run(settings)


if __name__ == "__main__":
    sys.exit(main())

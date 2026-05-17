"""Sleeper Watchdog entry point.

Phase 2 scope: poll the configured leagues for new transactions and post each
to Discord. First run for any league bootstraps silently (records current
transaction IDs without posting) so we do not spam the channel on day one.

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

from src.discord_notify import DiscordNotifier, build_transaction_embed
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
    transactions = sleeper.get_transactions(league_id, week)
    current_tx_ids = [str(tx["transaction_id"]) for tx in transactions]

    log = log.bind(league_id=league_id, league=league_name, week=week, tx_count=len(transactions))

    if not league_state.is_bootstrapped():
        league_state.bootstrapped_at = now_utc()
        league_state.last_run_at = now_utc()
        league_state.current_nfl_week = int(nfl_state.get("week", 0))
        league_state.seen_transaction_ids = current_tx_ids
        log.info("league.bootstrapped", recorded=len(current_tx_ids))
        return

    seen = set(league_state.seen_transaction_ids)
    new_txs = [tx for tx in transactions if str(tx["transaction_id"]) not in seen]

    if new_txs:
        users = sleeper.get_users(league_id)
        rosters = sleeper.get_rosters(league_id)
        players = sleeper.get_players()
        roster_to_team = build_roster_to_team(rosters, users)

        for tx in new_txs:
            embed = build_transaction_embed(
                tx=tx,
                league_id=league_id,
                league_name=league_name,
                roster_to_team=roster_to_team,
                players=players,
            )
            notifier.post(embed)
            league_state.seen_transaction_ids.append(str(tx["transaction_id"]))

    league_state.last_run_at = now_utc()
    league_state.current_nfl_week = int(nfl_state.get("week", 0))
    log.info("league.processed", new_alerts=len(new_txs))


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

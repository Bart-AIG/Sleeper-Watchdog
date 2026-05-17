"""Sleeper Watchdog entry point.

- Phase 2: poll transactions and draft picks, post each new one to Discord
- Phase 3: load each league's constitution YAML, run the rules engine against
  current state, post a severity-colored embed for every new violation

First sighting of a league or a draft bootstraps silently (records current ids
without posting) so adding a new league or a new draft mid-stream does not
spam the channel.

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

import src.rules.checks  # noqa: F401  triggers rule self-registration
from src.discord_notify import (
    DiscordNotifier,
    build_draft_pick_embed,
    build_rule_alert_embed,
    build_transaction_embed,
)
from src.fantasycalc import FantasyCalcClient, grade_trade, trade_imbalance_percent
from src.rules.engine import RuleContext, evaluate_all
from src.sleeper import SleeperClient, effective_transaction_week
from src.state import AlertRecord, LeagueState, WatchdogState, load_state, now_utc, save_state

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


def load_rules_yaml(rules_path: Path) -> dict[str, Any]:
    with rules_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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
        self._users: list[dict[str, Any]] | None = None
        self._rosters: list[dict[str, Any]] | None = None
        self._map: dict[int, str] | None = None

    def users(self) -> list[dict[str, Any]]:
        if self._users is None:
            self._users = self._sleeper.get_users(self._league_id)
        return self._users

    def rosters(self) -> list[dict[str, Any]]:
        if self._rosters is None:
            self._rosters = self._sleeper.get_rosters(self._league_id)
        return self._rosters

    def get(self) -> dict[int, str]:
        if self._map is None:
            self._map = build_roster_to_team(self.rosters(), self.users())
        return self._map


def process_transactions(
    league_cfg: dict[str, Any],
    league_state: LeagueState,
    sleeper: SleeperClient,
    notifier: DiscordNotifier,
    roster_lookup: RosterLookup,
    transactions: list[dict[str, Any]],
    fantasycalc: FantasyCalcClient | None,
    log: structlog.BoundLogger,
) -> int:
    league_id = str(league_cfg["id"])
    league_name = league_cfg.get("name") or league_id

    seen = set(league_state.seen_transaction_ids)
    new_txs = [tx for tx in transactions if str(tx["transaction_id"]) not in seen]

    if new_txs:
        players = sleeper.get_players()
        for tx in new_txs:
            trade_grade_data = None
            imbalance = None
            if fantasycalc is not None and tx.get("type") == "trade" and tx.get("status") == "complete":
                trade_grade_data = grade_trade(tx, fantasycalc)
                imbalance = trade_imbalance_percent(trade_grade_data)

            embed = build_transaction_embed(
                tx=tx,
                league_id=league_id,
                league_name=league_name,
                roster_to_team=roster_lookup.get(),
                players=players,
                trade_grade=trade_grade_data,
                imbalance_percent=imbalance,
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


def process_rules(
    league_cfg: dict[str, Any],
    league_state: LeagueState,
    sleeper: SleeperClient,
    notifier: DiscordNotifier,
    roster_lookup: RosterLookup,
    nfl_state: dict[str, Any],
    transactions: list[dict[str, Any]],
    fantasycalc: FantasyCalcClient | None,
    log: structlog.BoundLogger,
) -> int:
    league_id = str(league_cfg["id"])
    league_name = league_cfg.get("name") or league_id

    rules_file = league_cfg.get("rules_file")
    if not rules_file:
        log.info("rules.skipped.no_rules_file")
        return 0
    rules_yaml = load_rules_yaml(Path(rules_file))

    ctx = RuleContext(
        league_id=league_id,
        league_name=league_name,
        calendar=rules_yaml.get("calendar") or {},
        nfl_state=nfl_state,
        league=sleeper.get_league(league_id),
        users=roster_lookup.users(),
        rosters=roster_lookup.rosters(),
        transactions=transactions,
        roster_to_team=roster_lookup.get(),
        fantasycalc=fantasycalc,
    )

    posted_keys = {ar.key for ar in league_state.alerts_posted}
    new_alerts = 0
    for result in evaluate_all(ctx, rules_yaml):
        if result.alert_key and result.alert_key in posted_keys:
            continue
        embed = build_rule_alert_embed(result, league_id, league_name)
        notifier.post(embed)
        league_state.alerts_posted.append(
            AlertRecord(
                key=result.alert_key,
                posted_at=now_utc(),
                severity=str(result.severity),
            )
        )
        new_alerts += 1

    log.info("rules.processed", new_alerts=new_alerts)
    return new_alerts


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

    transactions = sleeper.get_transactions(league_id, week)

    if not league_state.is_bootstrapped():
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
    fantasycalc = FantasyCalcClient()
    new_tx = process_transactions(
        league_cfg, league_state, sleeper, notifier, roster_lookup, transactions, fantasycalc, log
    )
    new_picks = process_drafts(
        league_cfg, league_state, sleeper, notifier, roster_lookup, log
    )
    new_alerts = process_rules(
        league_cfg,
        league_state,
        sleeper,
        notifier,
        roster_lookup,
        nfl_state,
        transactions,
        fantasycalc,
        log,
    )

    league_state.last_run_at = now_utc()
    league_state.current_nfl_week = int(nfl_state.get("week", 0))
    log.info("league.processed", new_tx=new_tx, new_picks=new_picks, new_alerts=new_alerts)


def run(settings: Settings) -> int:
    log = structlog.get_logger("watchdog")
    log.info("watchdog.start", phase=3)

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

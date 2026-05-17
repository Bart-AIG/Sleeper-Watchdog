"""Persisted state for the watchdog.

One JSON file at data/state.json holds per-league state, committed every run.
Pydantic models give us typed access plus validation on load.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_STATE_PATH = Path("data/state.json")


class AlertRecord(BaseModel):
    """One entry in the alerts_posted ledger, keyed for idempotency."""

    key: str
    posted_at: datetime
    severity: str = "INFO"


class LeagueState(BaseModel):
    bootstrapped_at: datetime | None = None
    last_run_at: datetime | None = None
    current_nfl_week: int = 0
    seen_transaction_ids: list[str] = Field(default_factory=list)
    seen_draft_ids: list[str] = Field(default_factory=list)
    seen_draft_pick_keys: list[str] = Field(default_factory=list)
    alerts_posted: list[AlertRecord] = Field(default_factory=list)

    def is_bootstrapped(self) -> bool:
        return self.bootstrapped_at is not None


class WatchdogState(BaseModel):
    schema_version: int = 1
    leagues: dict[str, LeagueState] = Field(default_factory=dict)

    def league(self, league_id: str) -> LeagueState:
        if league_id not in self.leagues:
            self.leagues[league_id] = LeagueState()
        return self.leagues[league_id]


def load_state(path: Path = DEFAULT_STATE_PATH) -> WatchdogState:
    if not path.exists():
        return WatchdogState()
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return WatchdogState()
    return WatchdogState.model_validate_json(raw)


def save_state(state: WatchdogState, path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = state.model_dump_json(indent=2)
    path.write_text(payload + "\n", encoding="utf-8")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

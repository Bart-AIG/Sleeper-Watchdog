"""State load/save round-trip and bootstrap helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.state import LeagueState, WatchdogState, load_state, save_state


def test_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    state = load_state(tmp_path / "no_such.json")
    assert state.schema_version == 1
    assert state.leagues == {}


def test_load_returns_empty_when_file_blank(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("   \n", encoding="utf-8")
    assert load_state(path).leagues == {}


def test_round_trip_preserves_league_data(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = WatchdogState()
    lg = original.league("123")
    lg.bootstrapped_at = datetime(2026, 5, 17, 14, 0, tzinfo=timezone.utc)
    lg.current_nfl_week = 3
    lg.seen_transaction_ids = ["tx1", "tx2"]

    save_state(original, path)
    reloaded = load_state(path)

    assert "123" in reloaded.leagues
    rlg = reloaded.leagues["123"]
    assert rlg.bootstrapped_at == lg.bootstrapped_at
    assert rlg.current_nfl_week == 3
    assert rlg.seen_transaction_ids == ["tx1", "tx2"]


def test_league_accessor_creates_lazily() -> None:
    state = WatchdogState()
    assert "999" not in state.leagues
    lg = state.league("999")
    assert isinstance(lg, LeagueState)
    assert not lg.is_bootstrapped()
    assert "999" in state.leagues


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested" / "state.json"
    save_state(WatchdogState(), nested)
    assert nested.exists()

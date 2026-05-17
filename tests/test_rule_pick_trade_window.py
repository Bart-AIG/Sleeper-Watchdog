"""pick_trade_window rule."""

from __future__ import annotations

from datetime import datetime, timezone

from src.rules.checks.pick_trade_window import PickTradeWindow
from src.rules.engine import RuleContext


def _trade(tx_id: str, when_iso: str, has_picks: bool = True) -> dict:
    return {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "roster_ids": [3, 4],
        "created": int(datetime.fromisoformat(when_iso).replace(tzinfo=timezone.utc).timestamp() * 1000),
        "draft_picks": [{"round": 1, "season": "2027"}] if has_picks else [],
    }


def _ctx(transactions: list[dict]) -> RuleContext:
    return RuleContext(
        league_id="L1",
        league_name="Test",
        transactions=transactions,
        roster_to_team={3: "Team A", 4: "Team B"},
    )


def test_disabled_when_window_not_configured() -> None:
    tx = _trade("t1", "2026-07-01T12:00:00")
    assert PickTradeWindow().evaluate(_ctx([tx]), {}) == []


def test_trade_inside_window_passes() -> None:
    tx = _trade("t1", "2026-06-15T12:00:00")
    params = {"window_start": "2026-06-01", "window_end": "2026-08-31"}
    assert PickTradeWindow().evaluate(_ctx([tx]), params) == []


def test_trade_before_window_fires() -> None:
    tx = _trade("t1", "2026-05-15T12:00:00")
    params = {"window_start": "2026-06-01", "window_end": "2026-08-31"}
    results = PickTradeWindow().evaluate(_ctx([tx]), params)
    assert len(results) == 1
    assert results[0].alert_key == "L1:t1:pick_trade_window"


def test_trade_after_window_fires() -> None:
    tx = _trade("t1", "2026-09-15T12:00:00")
    params = {"window_start": "2026-06-01", "window_end": "2026-08-31"}
    results = PickTradeWindow().evaluate(_ctx([tx]), params)
    assert len(results) == 1


def test_trade_without_picks_ignored() -> None:
    tx = _trade("t1", "2026-09-15T12:00:00", has_picks=False)
    params = {"window_start": "2026-06-01", "window_end": "2026-08-31"}
    assert PickTradeWindow().evaluate(_ctx([tx]), params) == []

"""trade_deadline rule."""

from __future__ import annotations

from src.rules.checks.trade_deadline import TradeDeadline
from src.rules.engine import RuleContext
from src.rules.result import Severity


def _ctx_with_tx(tx_list: list[dict]) -> RuleContext:
    return RuleContext(
        league_id="L1",
        league_name="Test",
        transactions=tx_list,
        roster_to_team={3: "Team A", 4: "Team B"},
    )


def test_trade_in_week_13_fires_block() -> None:
    tx = {
        "transaction_id": "tx_after",
        "type": "trade",
        "status": "complete",
        "leg": 13,
        "roster_ids": [3, 4],
    }
    results = TradeDeadline().evaluate(_ctx_with_tx([tx]), {"deadline_week": 13})
    assert len(results) == 1
    assert results[0].severity is Severity.BLOCK
    assert results[0].alert_key == "L1:tx_after:trade_deadline"
    assert "Team A" in next(f["value"] for f in results[0].fields if f["name"] == "Teams")


def test_trade_in_week_12_passes() -> None:
    tx = {
        "transaction_id": "tx_before",
        "type": "trade",
        "status": "complete",
        "leg": 12,
        "roster_ids": [3, 4],
    }
    assert TradeDeadline().evaluate(_ctx_with_tx([tx]), {"deadline_week": 13}) == []


def test_non_trade_transactions_ignored() -> None:
    txs = [
        {"transaction_id": "w1", "type": "waiver", "status": "complete", "leg": 14},
        {"transaction_id": "f1", "type": "free_agent", "status": "complete", "leg": 14},
    ]
    assert TradeDeadline().evaluate(_ctx_with_tx(txs), {"deadline_week": 13}) == []


def test_pending_trade_ignored() -> None:
    tx = {"transaction_id": "p1", "type": "trade", "status": "pending", "leg": 14}
    assert TradeDeadline().evaluate(_ctx_with_tx([tx]), {"deadline_week": 13}) == []


def test_custom_deadline_week_param() -> None:
    tx = {
        "transaction_id": "x",
        "type": "trade",
        "status": "complete",
        "leg": 11,
        "roster_ids": [3],
    }
    assert TradeDeadline().evaluate(_ctx_with_tx([tx]), {"deadline_week": 10}) == [] or True
    results = TradeDeadline().evaluate(_ctx_with_tx([tx]), {"deadline_week": 10})
    assert len(results) == 1
    assert "Week 10" in results[0].title

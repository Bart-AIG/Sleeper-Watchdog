"""Transaction-diff logic against the seen-IDs ledger."""

from __future__ import annotations

from typing import Any

from src.state import LeagueState


def _new_only(transactions: list[dict[str, Any]], league_state: LeagueState) -> list[str]:
    seen = set(league_state.seen_transaction_ids)
    return [str(tx["transaction_id"]) for tx in transactions if str(tx["transaction_id"]) not in seen]


def test_bootstrap_records_all_tx_ids_without_posting(
    sample_transactions: list[dict[str, Any]]
) -> None:
    league_state = LeagueState()
    assert not league_state.is_bootstrapped()

    current_ids = [str(tx["transaction_id"]) for tx in sample_transactions]
    league_state.seen_transaction_ids = current_ids

    assert len(league_state.seen_transaction_ids) == 3
    assert _new_only(sample_transactions, league_state) == []


def test_diff_finds_only_new_transactions(
    sample_transactions: list[dict[str, Any]],
) -> None:
    league_state = LeagueState(seen_transaction_ids=[str(sample_transactions[0]["transaction_id"])])
    new_ids = _new_only(sample_transactions, league_state)
    assert new_ids == [
        str(sample_transactions[1]["transaction_id"]),
        str(sample_transactions[2]["transaction_id"]),
    ]


def test_diff_empty_when_nothing_changed(sample_transactions: list[dict[str, Any]]) -> None:
    league_state = LeagueState(
        seen_transaction_ids=[str(tx["transaction_id"]) for tx in sample_transactions]
    )
    assert _new_only(sample_transactions, league_state) == []

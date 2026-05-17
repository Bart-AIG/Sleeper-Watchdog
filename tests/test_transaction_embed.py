"""Transaction embed builder shape + content checks."""

from __future__ import annotations

from typing import Any

from src.discord_notify import build_transaction_embed
from src.main import build_roster_to_team


def test_trade_embed_has_all_expected_sections(
    sample_transactions: list[dict[str, Any]],
    sample_users: list[dict[str, Any]],
    sample_rosters: list[dict[str, Any]],
    sample_players: dict[str, dict[str, Any]],
) -> None:
    roster_to_team = build_roster_to_team(sample_rosters, sample_users)
    trade = sample_transactions[0]

    embed = build_transaction_embed(
        tx=trade,
        league_id="123",
        league_name="Test League",
        roster_to_team=roster_to_team,
        players=sample_players,
    )

    assert embed["title"] == "Trade in Test League"
    assert "1361763263972409344" in embed["description"]

    field_names = [f["name"] for f in embed["fields"]]
    assert "Type" in field_names
    assert "Status" in field_names
    assert "Teams" in field_names
    assert "Adds" in field_names
    assert "Drops" in field_names
    assert "Draft picks" in field_names
    assert "Link" in field_names

    teams_field = next(f for f in embed["fields"] if f["name"] == "Teams")
    assert "I Love Lamb." in teams_field["value"]
    assert "Ryanators" in teams_field["value"]

    adds_field = next(f for f in embed["fields"] if f["name"] == "Adds")
    assert "Caleb Williams" in adds_field["value"]
    assert "Marvin Harrison Jr." in adds_field["value"]


def test_waiver_embed_omits_irrelevant_sections(
    sample_transactions: list[dict[str, Any]],
    sample_users: list[dict[str, Any]],
    sample_rosters: list[dict[str, Any]],
    sample_players: dict[str, dict[str, Any]],
) -> None:
    waiver = sample_transactions[1]
    roster_to_team = build_roster_to_team(sample_rosters, sample_users)

    embed = build_transaction_embed(
        tx=waiver,
        league_id="123",
        league_name="Test League",
        roster_to_team=roster_to_team,
        players=sample_players,
    )

    field_names = [f["name"] for f in embed["fields"]]
    assert "Adds" in field_names
    assert "Drops" not in field_names
    assert "Draft picks" not in field_names
    assert "FAAB" not in field_names


def test_free_agent_embed_includes_faab(
    sample_transactions: list[dict[str, Any]],
    sample_users: list[dict[str, Any]],
    sample_rosters: list[dict[str, Any]],
    sample_players: dict[str, dict[str, Any]],
) -> None:
    fa = sample_transactions[2]
    roster_to_team = build_roster_to_team(sample_rosters, sample_users)

    embed = build_transaction_embed(
        tx=fa,
        league_id="123",
        league_name="Test League",
        roster_to_team=roster_to_team,
        players=sample_players,
    )

    faab_field = next(f for f in embed["fields"] if f["name"] == "FAAB")
    assert "$5" in faab_field["value"]


def test_trade_embed_with_grade_includes_values_section(
    sample_transactions: list[dict[str, Any]],
    sample_users: list[dict[str, Any]],
    sample_rosters: list[dict[str, Any]],
    sample_players: dict[str, dict[str, Any]],
) -> None:
    roster_to_team = build_roster_to_team(sample_rosters, sample_users)
    trade = sample_transactions[0]
    grade_data = {
        3: {"sent": 10000, "received": 9500, "net": -500},
        4: {"sent": 9500, "received": 10000, "net": 500},
    }
    embed = build_transaction_embed(
        tx=trade,
        league_id="L1",
        league_name="Test",
        roster_to_team=roster_to_team,
        players=sample_players,
        trade_grade=grade_data,
        imbalance_percent=2.5,
    )
    values_field = next(f for f in embed["fields"] if f["name"] == "Trade values")
    assert "10,000" in values_field["value"]
    assert "2.5%" in values_field["value"]


def test_unknown_player_falls_back_to_id(
    sample_users: list[dict[str, Any]],
    sample_rosters: list[dict[str, Any]],
) -> None:
    roster_to_team = build_roster_to_team(sample_rosters, sample_users)
    tx = {
        "transaction_id": "tx_unknown",
        "status": "complete",
        "type": "free_agent",
        "roster_ids": [1],
        "adds": {"99999": 1},
    }
    embed = build_transaction_embed(
        tx=tx,
        league_id="123",
        league_name="Test League",
        roster_to_team=roster_to_team,
        players={},
    )
    adds_field = next(f for f in embed["fields"] if f["name"] == "Adds")
    assert "99999" in adds_field["value"]

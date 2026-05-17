"""Draft pick diff + embed builder."""

from __future__ import annotations

from typing import Any

from src.discord_notify import build_draft_pick_embed
from src.main import build_roster_to_team
from src.state import LeagueState


def _new_pick_keys(
    picks: list[dict[str, Any]], league_state: LeagueState, draft_id: str
) -> list[str]:
    seen = set(league_state.seen_draft_pick_keys)
    return [f"{draft_id}:{p['pick_no']}" for p in picks if f"{draft_id}:{p['pick_no']}" not in seen]


def test_bootstrap_records_all_pick_keys_without_posting(
    sample_draft: dict[str, Any], sample_draft_picks: list[dict[str, Any]]
) -> None:
    league_state = LeagueState(bootstrapped_at=None)
    did = sample_draft["draft_id"]
    league_state.seen_draft_ids.append(did)
    league_state.seen_draft_pick_keys.extend(f"{did}:{p['pick_no']}" for p in sample_draft_picks)

    assert len(league_state.seen_draft_pick_keys) == 3
    assert _new_pick_keys(sample_draft_picks, league_state, did) == []


def test_diff_finds_only_new_picks(
    sample_draft: dict[str, Any], sample_draft_picks: list[dict[str, Any]]
) -> None:
    did = sample_draft["draft_id"]
    league_state = LeagueState(
        seen_draft_ids=[did], seen_draft_pick_keys=[f"{did}:1"]
    )
    new_keys = _new_pick_keys(sample_draft_picks, league_state, did)
    assert new_keys == [f"{did}:2", f"{did}:3"]


def test_embed_has_team_player_and_pick_fields(
    sample_draft: dict[str, Any],
    sample_draft_picks: list[dict[str, Any]],
    sample_users: list[dict[str, Any]],
    sample_rosters: list[dict[str, Any]],
) -> None:
    roster_to_team = build_roster_to_team(sample_rosters, sample_users)
    pick = sample_draft_picks[1]

    embed = build_draft_pick_embed(
        pick=pick,
        draft=sample_draft,
        league_id="1312238972738502656",
        league_name="512 Dynasty League",
        roster_to_team=roster_to_team,
    )

    assert "1.02" in embed["title"]
    assert "Marvin Harrison Jr." in embed["description"]
    assert "Randy Orton" in embed["description"] or "I Love Lamb." in embed["description"]

    field_names = [f["name"] for f in embed["fields"]]
    assert field_names == ["Team", "Player", "Pick", "Link"]

    player_field = next(f for f in embed["fields"] if f["name"] == "Player")
    assert "WR" in player_field["value"]
    assert "ARI" in player_field["value"]


def test_keeper_pick_shows_keeper_label(
    sample_draft: dict[str, Any],
    sample_draft_picks: list[dict[str, Any]],
    sample_users: list[dict[str, Any]],
    sample_rosters: list[dict[str, Any]],
) -> None:
    roster_to_team = build_roster_to_team(sample_rosters, sample_users)
    keeper_pick = sample_draft_picks[2]
    assert keeper_pick["is_keeper"] is True

    embed = build_draft_pick_embed(
        pick=keeper_pick,
        draft=sample_draft,
        league_id="x",
        league_name="x",
        roster_to_team=roster_to_team,
    )
    player_field = next(f for f in embed["fields"] if f["name"] == "Player")
    assert "(keeper)" in player_field["value"]

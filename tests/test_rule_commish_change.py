"""commish_change rule: first-run snapshot + add/remove detection."""

from __future__ import annotations

from typing import Any

from src.rules.checks.commish_change import CommishChange
from src.rules.engine import RuleContext
from src.state import LeagueState


def _user(uid: str, is_owner: bool = False, name: str = "u") -> dict[str, Any]:
    return {"user_id": uid, "is_owner": is_owner, "display_name": name, "metadata": {"team_name": name}}


def _ctx(users: list[dict[str, Any]], state: LeagueState | None = None) -> RuleContext:
    return RuleContext(
        league_id="L1",
        league_name="Test",
        users=users,
        league_state=state or LeagueState(),
    )


def test_first_run_snapshots_commish_list_silently() -> None:
    state = LeagueState()
    users = [_user("a", is_owner=True), _user("b"), _user("c")]
    assert CommishChange().evaluate(_ctx(users, state), {}) == []
    assert state.last_commish_user_ids == ["a"]


def test_no_change_emits_no_alert() -> None:
    state = LeagueState(last_commish_user_ids=["a"])
    users = [_user("a", is_owner=True), _user("b")]
    assert CommishChange().evaluate(_ctx(users, state), {}) == []


def test_added_commissioner_fires() -> None:
    state = LeagueState(last_commish_user_ids=["a"])
    users = [_user("a", is_owner=True), _user("b", is_owner=True, name="newco")]
    results = CommishChange().evaluate(_ctx(users, state), {})
    assert len(results) == 1
    added_field = next(f for f in results[0].fields if f["name"] == "Added")
    assert "newco" in added_field["value"]
    assert "b" in added_field["value"]
    assert state.last_commish_user_ids == ["a", "b"]


def test_removed_commissioner_fires() -> None:
    state = LeagueState(last_commish_user_ids=["a", "b"])
    users = [_user("a", is_owner=True), _user("b")]  # b no longer owner
    results = CommishChange().evaluate(_ctx(users, state), {})
    assert len(results) == 1
    removed = next(f for f in results[0].fields if f["name"] == "Removed")
    assert "b" in removed["value"]


def test_expected_commissioners_mismatch_fires_even_without_change() -> None:
    state = LeagueState(last_commish_user_ids=["a"])
    users = [_user("a", is_owner=True), _user("b")]
    results = CommishChange().evaluate(_ctx(users, state), {"expected_commissioners": ["different"]})
    assert len(results) == 1
    assert "does not match expected" in results[0].title


def test_expected_commissioners_placeholder_ignored() -> None:
    state = LeagueState(last_commish_user_ids=["a"])
    users = [_user("a", is_owner=True), _user("b")]
    params = {"expected_commissioners": ["REPLACE_WITH_YOUR_SLEEPER_USER_ID"]}
    assert CommishChange().evaluate(_ctx(users, state), params) == []


def test_no_state_returns_empty() -> None:
    ctx = RuleContext(league_id="L1", league_name="Test", users=[_user("a", is_owner=True)])
    assert CommishChange().evaluate(ctx, {}) == []

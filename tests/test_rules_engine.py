"""Engine plumbing: registry, evaluator, enable/disable handling."""

from __future__ import annotations

from typing import Any

import pytest

from src.rules.engine import RuleContext, evaluate_all, register, registered_rule_ids
from src.rules.result import RuleResult, Severity


@pytest.fixture
def ctx() -> RuleContext:
    return RuleContext(league_id="L1", league_name="L")


def test_registry_includes_phase3_checks() -> None:
    ids = registered_rule_ids()
    assert "trade_deadline" in ids
    assert "pick_trade_window" in ids


def test_duplicate_registration_raises() -> None:
    class Dummy:
        rule_id = "trade_deadline"

        def evaluate(self, ctx: Any, params: dict[str, Any]) -> list[RuleResult]:
            return []

    with pytest.raises(ValueError, match="duplicate"):
        register(Dummy())


def test_disabled_rules_are_skipped(ctx: RuleContext) -> None:
    rules_yaml = {"rules": [{"id": "trade_deadline", "enabled": False, "params": {}}]}
    assert evaluate_all(ctx, rules_yaml) == []


def test_unknown_rule_ids_are_skipped(ctx: RuleContext) -> None:
    rules_yaml = {"rules": [{"id": "does_not_exist", "enabled": True, "params": {}}]}
    assert evaluate_all(ctx, rules_yaml) == []


def test_rule_exception_does_not_kill_evaluation(ctx: RuleContext, caplog: Any) -> None:
    """A rule that throws should be logged and skipped, not propagate."""
    class Bomb:
        rule_id = "bomb_rule"

        def evaluate(self, ctx: Any, params: dict[str, Any]) -> list[RuleResult]:
            raise RuntimeError("kaboom")

    register(Bomb())
    rules_yaml = {
        "rules": [
            {"id": "bomb_rule", "enabled": True, "params": {}},
            {"id": "trade_deadline", "enabled": True, "params": {}},
        ]
    }
    assert evaluate_all(ctx, rules_yaml) == []

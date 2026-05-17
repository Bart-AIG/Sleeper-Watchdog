"""Rules engine: a Protocol-based plug-in registry.

Each check lives in `src.rules.checks.<name>` and self-registers on import via
`register(...)`. The orchestrator builds a RuleContext with everything a rule
might want, then calls `evaluate_all(context, rules_yaml)` which iterates over
enabled rules, dispatches to the registered checker, and returns flattened
results.

Rules are pure functions of context + their YAML params. They do not perform
I/O and they do not mutate state. The orchestrator handles posting + dedup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from src.rules.result import RuleResult, Severity

log = structlog.get_logger(__name__)


@dataclass
class RuleContext:
    """All the per-league data any rule might need on a single poll cycle."""

    league_id: str
    league_name: str
    calendar: dict[str, Any] = field(default_factory=dict)
    nfl_state: dict[str, Any] = field(default_factory=dict)
    league: dict[str, Any] = field(default_factory=dict)
    users: list[dict[str, Any]] = field(default_factory=list)
    rosters: list[dict[str, Any]] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    traded_picks: list[dict[str, Any]] = field(default_factory=list)
    players: dict[str, dict[str, Any]] = field(default_factory=dict)
    roster_to_team: dict[int, str] = field(default_factory=dict)


class RuleCheck(Protocol):
    rule_id: str

    def evaluate(self, ctx: RuleContext, params: dict[str, Any]) -> list[RuleResult]: ...


_REGISTRY: dict[str, RuleCheck] = {}


def register(check: RuleCheck) -> RuleCheck:
    if check.rule_id in _REGISTRY:
        raise ValueError(f"duplicate rule registration: {check.rule_id}")
    _REGISTRY[check.rule_id] = check
    return check


def registered_rule_ids() -> list[str]:
    return sorted(_REGISTRY)


def evaluate_all(ctx: RuleContext, rules_yaml: dict[str, Any]) -> list[RuleResult]:
    """Run every enabled rule whose id has a registered implementation.

    Rules without a registered implementation are logged at debug and skipped;
    this makes it safe to ship the engine ahead of all checks.
    """
    out: list[RuleResult] = []
    for rule_cfg in rules_yaml.get("rules", []):
        if not rule_cfg.get("enabled", False):
            continue
        rule_id = rule_cfg.get("id")
        check = _REGISTRY.get(rule_id)
        if check is None:
            log.debug("rule.skipped.not_registered", rule_id=rule_id)
            continue
        try:
            results = check.evaluate(ctx, rule_cfg.get("params") or {})
        except Exception:
            log.exception("rule.failed", rule_id=rule_id)
            continue
        for r in results:
            if r.severity != Severity.PASS:
                out.append(r)
    return out

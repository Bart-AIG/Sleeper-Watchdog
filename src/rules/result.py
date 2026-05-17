"""Severity enum and RuleResult dataclass shared by every rule check."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    PASS = "PASS"
    FLAG = "FLAG"
    BLOCK = "BLOCK"


@dataclass
class RuleResult:
    """One verdict from one rule against one piece of league state.

    `alert_key` is the dedup token written to LeagueState.alerts_posted so we
    do not re-post the same verdict on subsequent runs.
    """

    rule_id: str
    severity: Severity
    title: str
    message: str
    fields: list[dict[str, Any]] = field(default_factory=list)
    alert_key: str = ""

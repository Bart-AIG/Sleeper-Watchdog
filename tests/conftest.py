"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> Any:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_users() -> list[dict[str, Any]]:
    return _load("sample_users.json")


@pytest.fixture
def sample_rosters() -> list[dict[str, Any]]:
    return _load("sample_rosters.json")


@pytest.fixture
def sample_transactions() -> list[dict[str, Any]]:
    return _load("sample_transactions.json")


@pytest.fixture
def sample_players() -> dict[str, dict[str, Any]]:
    return _load("sample_players.json")

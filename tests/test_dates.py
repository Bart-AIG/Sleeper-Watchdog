"""first_saturday_after date helper."""

from __future__ import annotations

from datetime import date

from src.dates import first_saturday_after


def test_friday_returns_next_day() -> None:
    assert first_saturday_after(date(2026, 5, 22)) == date(2026, 5, 23)


def test_monday_returns_same_week_saturday() -> None:
    assert first_saturday_after(date(2026, 5, 18)) == date(2026, 5, 23)


def test_saturday_returns_next_saturday_one_week_later() -> None:
    assert first_saturday_after(date(2026, 5, 23)) == date(2026, 5, 30)


def test_sunday_returns_next_saturday() -> None:
    assert first_saturday_after(date(2026, 5, 24)) == date(2026, 5, 30)

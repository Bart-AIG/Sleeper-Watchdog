"""Small date helpers used by main.py and the calendar_reminders rule."""

from __future__ import annotations

from datetime import date, timedelta


def first_saturday_after(d: date) -> date:
    """First Saturday strictly after d.

    Friday end -> next-day Saturday. Saturday end -> the following Saturday
    (one week buffer so the league has at least a day before waivers open).
    """
    days_until_sat = (5 - d.weekday() + 7) % 7
    if days_until_sat == 0:
        days_until_sat = 7
    return d + timedelta(days=days_until_sat)

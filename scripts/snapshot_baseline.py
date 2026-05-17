"""One-off baseline snapshot for the settings_compliance rule.

Pulls the current live values from Sleeper for one league and prints a YAML
fragment you can paste into `config/rules/<league>.yaml` under the
`settings_compliance` rule's `params` key.

The settings_compliance rule diffs each future poll against this snapshot and
posts a FLAG when anything drifts.

Usage:
    python -m scripts.snapshot_baseline <league_id>
"""

from __future__ import annotations

import sys
from typing import Any

import yaml

from src.sleeper import SleeperClient


def build_baseline(league_id: str) -> dict[str, Any]:
    with SleeperClient() as sleeper:
        league = sleeper.get_league(league_id)
        users = sleeper.get_users(league_id)
        rosters = sleeper.get_rosters(league_id)
        drafts = sleeper.get_drafts(league_id)

    # Use Sleeper's actual API field names so the rule's ctx.league.get(key)
    # matches without any aliasing.
    baseline: dict[str, Any] = {
        "expected_league": {
            "name": league.get("name"),
            "total_rosters": league.get("total_rosters"),
            "season": league.get("season"),
            "season_type": league.get("season_type"),
            "status": league.get("status"),
            "sport": league.get("sport"),
        },
        "expected_settings": _sorted_dict(league.get("settings") or {}),
        "expected_scoring_settings": _sorted_dict(league.get("scoring_settings") or {}),
        "expected_roster_positions": league.get("roster_positions") or [],
        "expected_user_ids": sorted(u["user_id"] for u in users),
        "expected_roster_owners": {
            str(r["roster_id"]): r.get("owner_id") for r in rosters
        },
    }
    if drafts:
        d = drafts[0]
        baseline["expected_draft"] = {
            "draft_id": d.get("draft_id"),
            "type": d.get("type"),
            "rounds": (d.get("settings") or {}).get("rounds"),
            "pick_timer": (d.get("settings") or {}).get("pick_timer"),
            "autopause_enabled": (d.get("settings") or {}).get("autopause_enabled"),
            "autopause_start_time": (d.get("settings") or {}).get("autopause_start_time"),
            "autopause_end_time": (d.get("settings") or {}).get("autopause_end_time"),
            "cpu_autopick": (d.get("settings") or {}).get("cpu_autopick"),
            "reversal_round": (d.get("settings") or {}).get("reversal_round"),
        }
    return baseline


def _sorted_dict(d: dict[str, Any]) -> dict[str, Any]:
    return {k: d[k] for k in sorted(d)}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: python -m scripts.snapshot_baseline <league_id>", file=sys.stderr)
        return 2
    league_id = argv[1]
    baseline = build_baseline(league_id)
    print("# ---- Snapshot from Sleeper. Paste under the settings_compliance rule's params: ----")
    print(yaml.safe_dump(baseline, sort_keys=False, default_flow_style=False, allow_unicode=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

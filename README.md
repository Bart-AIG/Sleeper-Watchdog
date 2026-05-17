# Sleeper Watchdog

A GitHub Actions cron job that watches a Sleeper fantasy football league, evaluates transactions and settings changes against a YAML rules engine, and posts alerts to a Discord channel via webhook.

No persistent bot, no server, $0 hosting.

## How it works

Every 15 minutes, a workflow runs on GitHub's free Ubuntu runners. The script polls the public Sleeper API, diffs against `data/state.json`, fires any rule alerts to a Discord webhook, then commits the updated state back to this repo.

## Project layout

- `src/` Python source (entry point: `src/main.py`)
- `config/leagues.yaml` Which leagues to monitor
- `config/rules/` Constitution rules per league
- `data/state.json` Last-seen state, committed every run
- `data/audit/` Append-only decision log
- `tests/` pytest suite, with fixture JSON in `tests/fixtures/`
- `.github/workflows/watchdog.yml` The cron job

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
```

## Required GitHub repo secrets

| Secret | Purpose |
|---|---|
| `DISCORD_WEBHOOK_URL` | Channel webhook the bot posts to |
| `FANTASYCALC_API_KEY` | Optional, for lopsided-trade detection (Phase 6) |

## Build status

Currently in **Phase 0: Scaffold**. See `sleeper-watchdog-architecture-v1.5.md` for the full spec and phase breakdown.

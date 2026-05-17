"""Sleeper Watchdog entry point.

Phase 1 scope: post a 'watchdog online' embed to the Discord webhook and exit.
Future phases will add Sleeper polling, state diff, and rules evaluation here.

Run with: python -m src.main
"""

from __future__ import annotations

import sys

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.discord_notify import DiscordNotifier, build_hello_embed


class Settings(BaseSettings):
    """Runtime config loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_webhook_url: str = Field(..., alias="DISCORD_WEBHOOK_URL")


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


def run(settings: Settings) -> int:
    log = structlog.get_logger("watchdog")
    log.info("watchdog.start", phase=1)
    with DiscordNotifier(settings.discord_webhook_url) as notifier:
        notifier.post(build_hello_embed())
    log.info("watchdog.done")
    return 0


def main() -> int:
    configure_logging()
    settings = Settings()  # type: ignore[call-arg]
    return run(settings)


if __name__ == "__main__":
    sys.exit(main())

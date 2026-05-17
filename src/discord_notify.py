"""Post embeds to a Discord webhook.

Stateless: callers construct an embed dict and hand it to `DiscordNotifier.post`.
The notifier owns the HTTP client and the webhook URL, nothing else.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)


class DiscordNotifier:
    """Thin wrapper around a single Discord webhook URL."""

    def __init__(self, webhook_url: str, client: httpx.Client | None = None) -> None:
        self._webhook_url = webhook_url
        self._client = client or httpx.Client(timeout=10.0)
        self._owns_client = client is None

    def __enter__(self) -> DiscordNotifier:
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._owns_client:
            self._client.close()

    def post(self, embed: dict[str, Any], username: str = "Sleeper Watchdog") -> None:
        """POST one embed. Raises httpx.HTTPStatusError on 4xx/5xx."""
        payload = {"username": username, "embeds": [embed]}
        response = self._client.post(self._webhook_url, json=payload)
        response.raise_for_status()
        log.info("discord.posted", title=embed.get("title"), status=response.status_code)


def build_hello_embed(now: datetime | None = None) -> dict[str, Any]:
    """The Phase 1 'watchdog online' embed. No league context, just a heartbeat."""
    ts = now or datetime.now(timezone.utc)
    return {
        "title": "Watchdog online",
        "description": "Phase 1 hello: the GitHub Actions cron job reached Discord.",
        "color": 0x57F287,
        "footer": {"text": f"Sleeper Watchdog · {ts.strftime('%Y-%m-%d %H:%M UTC')}"},
    }

"""Reusable token manager for Azure managed-identity credentials.

Tokens are cached and automatically refreshed 2 minutes before expiry so that
callers never see a stale token during a long-running WebSocket session.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from azure.identity.aio import DefaultAzureCredential

logger = logging.getLogger(__name__)

# Refresh tokens 2 minutes before they expire to avoid mid-request failures.
_REFRESH_MARGIN_SECONDS = 120


@dataclass
class TokenManager:
    """Async-safe, self-refreshing token cache for a single Azure scope."""

    scope: str
    _credential: DefaultAzureCredential = field(
        default_factory=DefaultAzureCredential, repr=False
    )
    _token: str | None = field(default=None, repr=False)
    _expires_on: float = field(default=0.0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def get_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if self._token and time.time() < self._expires_on - _REFRESH_MARGIN_SECONDS:
            return self._token

        async with self._lock:
            # Double-check after acquiring the lock.
            if self._token and time.time() < self._expires_on - _REFRESH_MARGIN_SECONDS:
                return self._token

            logger.info("Refreshing token for scope %s", self.scope)
            access = await self._credential.get_token(self.scope)
            self._token = access.token
            self._expires_on = access.expires_on
            return self._token

    async def close(self) -> None:
        """Release the underlying credential transport."""
        await self._credential.close()

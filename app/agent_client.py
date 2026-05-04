"""Async client for Azure AI Foundry agent via the Responses API.

Manages conversation state through ``previous_response_id`` so the agent
retains context across turns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.config import AgentConfig
from app.token_manager import TokenManager

logger = logging.getLogger(__name__)

_FOUNDRY_SCOPE = "https://ai.azure.com/.default"


@dataclass
class AgentReply:
    """Structured result from a single agent turn."""

    text: str
    response_id: str


class AgentClient:
    """Async HTTP client that talks to a Foundry agent via the Responses API."""

    def __init__(self, cfg: AgentConfig) -> None:
        self._cfg = cfg
        self._token_mgr = TokenManager(scope=_FOUNDRY_SCOPE)
        self._http = httpx.AsyncClient(timeout=60.0)

    async def send(
        self,
        user_text: str,
        previous_response_id: Optional[str] = None,
    ) -> AgentReply:
        """Send *user_text* to the agent and return its reply.

        Parameters
        ----------
        user_text:
            The transcribed user utterance.
        previous_response_id:
            Opaque ID from the previous turn to maintain conversation context.
        """
        token = await self._token_mgr.get_token()

        body: dict[str, Any] = {
            "input": [{"role": "user", "content": user_text}],
            "agent_reference": {
                "name": self._cfg.agent_name,
                "version": self._cfg.agent_version,
                "type": "agent_reference",
            },
        }
        if previous_response_id:
            body["previous_response_id"] = previous_response_id

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        logger.info("Sending to agent: %s", user_text[:120])
        response = await self._http.post(
            self._cfg.responses_url,
            json=body,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        return self._parse_response(data)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> AgentReply:
        """Extract the agent's text reply from the Responses API payload."""
        response_id = data.get("id", "")

        # Try top-level output_text first (convenience field)
        if data.get("output_text"):
            return AgentReply(text=data["output_text"], response_id=response_id)

        # Fall back to parsing output array
        output_items: list[dict[str, Any]] = data.get("output", [])
        for item in output_items:
            if item.get("type") == "message":
                content_blocks = item.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "output_text" and block.get("text"):
                        return AgentReply(
                            text=block["text"],
                            response_id=response_id,
                        )

        logger.warning("No message content found in agent response: %s", data)
        return AgentReply(text="I'm sorry, I didn't get a response.", response_id=response_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._http.aclose()
        await self._token_mgr.close()

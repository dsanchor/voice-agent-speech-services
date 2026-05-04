"""Application configuration — constructed from explicit parameters (no env vars)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechConfig:
    """Azure Speech Service configuration."""

    region: str
    resource_id: str
    stt_language: str = "en-US"
    stt_locales: list[str] | None = None
    tts_voice: str = "en-US-AvaMultilingualNeural"
    tts_output_format: str = "audio-16khz-32kbitrate-mono-mp3"

    def __post_init__(self) -> None:
        if self.stt_locales is None:
            object.__setattr__(self, "stt_locales", [self.stt_language])


@dataclass(frozen=True)
class AgentConfig:
    """Foundry agent (Responses API) configuration."""

    endpoint: str
    project: str
    agent_name: str
    api_version: str = "2025-11-15-preview"

    @property
    def responses_url(self) -> str:
        base = self.endpoint.rstrip("/")
        return f"{base}/api/projects/{self.project}/openai/responses?api-version={self.api_version}"

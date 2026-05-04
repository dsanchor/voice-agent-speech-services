"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class SpeechConfig:
    """Azure Speech Service configuration."""

    region: str = field(default_factory=lambda: os.environ["AZURE_SPEECH_REGION"])
    resource_id: str = field(
        default_factory=lambda: os.environ["AZURE_SPEECH_RESOURCE_ID"]
    )
    stt_language: str = field(
        default_factory=lambda: os.getenv("STT_LANGUAGE", "en-US")
    )
    stt_locales: list[str] = field(
        default_factory=lambda: os.getenv("STT_LOCALES", "en-US").split(",")
    )
    tts_voice: str = field(
        default_factory=lambda: os.getenv(
            "TTS_VOICE", "en-US-AvaMultilingualNeural"
        )
    )
    tts_output_format: str = field(
        default_factory=lambda: os.getenv(
            "TTS_OUTPUT_FORMAT", "audio-16khz-32kbitrate-mono-mp3"
        )
    )


@dataclass(frozen=True)
class AgentConfig:
    """Foundry agent (Responses API) configuration."""

    endpoint: str = field(default_factory=lambda: os.environ["FOUNDRY_ENDPOINT"])
    project: str = field(default_factory=lambda: os.environ["FOUNDRY_PROJECT"])
    agent_name: str = field(default_factory=lambda: os.environ["FOUNDRY_AGENT_NAME"])
    api_version: str = field(
        default_factory=lambda: os.getenv("FOUNDRY_API_VERSION", "2025-03-01-preview")
    )

    @property
    def responses_url(self) -> str:
        base = self.endpoint.rstrip("/")
        return f"{base}/api/projects/{self.project}/openai/responses?api-version={self.api_version}"


@dataclass(frozen=True)
class Settings:
    """Root settings aggregating all sub-configs."""

    speech: SpeechConfig = field(default_factory=SpeechConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)

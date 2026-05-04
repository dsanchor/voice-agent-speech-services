"""FastAPI application — serves the voice-agent web UI and WebSocket endpoint.

Start with:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import base64
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from app.agent_client import AgentClient
from app.config import Settings
from app.speech_service import SpeechService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Application lifespan — initialise shared services once
# -----------------------------------------------------------------------

settings: Settings
speech: SpeechService
agent: AgentClient


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    global settings, speech, agent
    settings = Settings()
    speech = SpeechService(settings.speech)
    agent = AgentClient(settings.agent)
    logger.info("Services initialised (region=%s)", settings.speech.region)
    yield
    await speech.close()
    await agent.close()
    logger.info("Services shut down")


app = FastAPI(title="Voice Agent", lifespan=lifespan)

# -----------------------------------------------------------------------
# Health check
# -----------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# -----------------------------------------------------------------------
# WebSocket — voice interaction loop
# -----------------------------------------------------------------------


async def _send_json(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload))


@app.websocket("/ws/voice")
async def voice_ws(ws: WebSocket) -> None:
    """Full-duplex voice loop.

    Protocol (JSON messages with ``type`` field):

    **Client → Server**
    - ``{"type": "config", ...}``  — optional session config (reserved).
    - ``{"type": "audio", "data": "<base64>"}`` — recorded audio chunk.

    **Server → Client**
    - ``{"type": "status", "message": "..."}``
    - ``{"type": "transcript", "text": "..."}``
    - ``{"type": "agent_response", "text": "..."}``
    - ``{"type": "tts_audio", "data": "<base64>", "format": "mp3"}``
    - ``{"type": "error", "message": "..."}``
    """
    await ws.accept()
    logger.info("WebSocket connected")

    previous_response_id: str | None = None

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "config":
                # Reserved for future per-session config (language, voice, etc.)
                await _send_json(ws, {"type": "status", "message": "Config received"})
                continue

            if msg_type == "audio":
                audio_b64 = msg.get("data", "")
                audio_bytes = base64.b64decode(audio_b64)

                if not audio_bytes:
                    await _send_json(ws, {"type": "error", "message": "Empty audio"})
                    continue

                # --- Step 1: STT ---
                await _send_json(ws, {"type": "status", "message": "Transcribing…"})
                try:
                    transcript = await speech.recognise(audio_bytes)
                except Exception as exc:
                    logger.exception("STT failed")
                    await _send_json(ws, {"type": "error", "message": f"STT error: {exc}"})
                    continue

                if not transcript:
                    await _send_json(
                        ws,
                        {"type": "status", "message": "No speech detected, try again."},
                    )
                    continue

                await _send_json(ws, {"type": "transcript", "text": transcript})

                # --- Step 2: Agent ---
                await _send_json(ws, {"type": "status", "message": "Thinking…"})
                try:
                    reply = await agent.send(
                        transcript, previous_response_id=previous_response_id
                    )
                    previous_response_id = reply.response_id
                except Exception as exc:
                    logger.exception("Agent call failed")
                    await _send_json(
                        ws, {"type": "error", "message": f"Agent error: {exc}"}
                    )
                    continue

                await _send_json(ws, {"type": "agent_response", "text": reply.text})

                # --- Step 3: TTS ---
                await _send_json(ws, {"type": "status", "message": "Generating audio…"})
                try:
                    tts_bytes = await speech.synthesise(reply.text)
                except Exception as exc:
                    logger.exception("TTS failed")
                    await _send_json(
                        ws, {"type": "error", "message": f"TTS error: {exc}"}
                    )
                    continue

                tts_b64 = base64.b64encode(tts_bytes).decode()
                await _send_json(
                    ws,
                    {"type": "tts_audio", "data": tts_b64, "format": "mp3"},
                )
            else:
                await _send_json(
                    ws, {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception:
        logger.exception("Unexpected WebSocket error")


# -----------------------------------------------------------------------
# Static files (must be mounted last so API routes take priority)
# -----------------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")

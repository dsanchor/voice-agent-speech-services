"""FastAPI application — serves the voice-agent web UI and WebSocket endpoint.

Uses continuous speech recognition (streaming STT) via PushAudioInputStream.
Audio streams from browser → WebSocket → PushAudioInputStream → SpeechRecognizer.

Start with:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

import azure.cognitiveservices.speech as speechsdk
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
# Per-client session state
# -----------------------------------------------------------------------


@dataclass
class ClientSession:
    """Holds per-WebSocket-connection state for streaming STT."""

    audio_stream: Optional[speechsdk.audio.PushAudioInputStream] = None
    recognizer: Optional[speechsdk.SpeechRecognizer] = None
    previous_response_id: Optional[str] = None
    tts_stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    is_speaking: bool = False
    is_recognizing: bool = False
    stt_language: Optional[str] = None
    tts_voice: Optional[str] = None

    def reset_conversation(self) -> None:
        self.previous_response_id = None

    async def stop_recognition(self) -> None:
        """Stop continuous recognition and close audio stream."""
        if self.recognizer and self.is_recognizing:
            try:
                await asyncio.to_thread(
                    self.recognizer.stop_continuous_recognition
                )
            except Exception as e:
                logger.warning("Error stopping recognition: %s", e)
            self.is_recognizing = False
        if self.audio_stream:
            try:
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None
        self.recognizer = None


# -----------------------------------------------------------------------
# WebSocket — streaming voice interaction
# -----------------------------------------------------------------------


async def _send_json(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:
        pass  # Connection may have closed


@app.websocket("/ws/voice")
async def voice_ws(ws: WebSocket) -> None:
    """Full-duplex streaming voice loop.

    Protocol (JSON messages with ``type`` field):

    **Client → Server**
    - ``{"type": "start_mic"}``  — begin continuous recognition
    - ``{"type": "audio", "data": "<base64>"}`` — PCM audio chunk (16kHz 16bit mono)
    - ``{"type": "stop_mic"}``  — stop continuous recognition
    - ``{"type": "stop_speaking"}`` — interrupt TTS playback
    - ``{"type": "clear_chat"}`` — reset conversation state
    - ``{"type": "config", "tts_voice": "...", "stt_language": "..."}``

    **Server → Client**
    - ``{"type": "recognizing", "text": "..."}`` — partial STT result
    - ``{"type": "recognized", "text": "..."}`` — final STT result
    - ``{"type": "agent_response", "text": "..."}`` — agent text reply
    - ``{"type": "tts_audio", "data": "<base64>", "format": "mp3"}`` — TTS audio
    - ``{"type": "tts_end"}`` — all TTS audio sent
    - ``{"type": "status", "message": "..."}``
    - ``{"type": "error", "message": "..."}``
    """
    await ws.accept()
    logger.info("WebSocket connected")

    session = ClientSession()
    loop = asyncio.get_event_loop()

    async def handle_recognized(text: str) -> None:
        """Called when STT produces a final recognition. Triggers agent + TTS."""
        if not text or not text.strip():
            return

        await _send_json(ws, {"type": "recognized", "text": text})

        # Call the agent
        await _send_json(ws, {"type": "status", "message": "Thinking…"})
        try:
            reply = await agent.send(
                text, previous_response_id=session.previous_response_id
            )
            session.previous_response_id = reply.response_id
        except Exception as exc:
            logger.exception("Agent call failed")
            await _send_json(ws, {"type": "error", "message": f"Agent error: {exc}"})
            return

        await _send_json(ws, {"type": "agent_response", "text": reply.text})

        # TTS — sentence-by-sentence, streamed immediately to client
        session.tts_stop_event.clear()
        session.is_speaking = True
        await _send_json(ws, {"type": "status", "message": "Speaking…"})
        try:
            # Queue for streaming audio from sync callback → async sender
            audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()

            def on_sentence_audio(audio_data: bytes) -> None:
                audio_queue.put_nowait(audio_data)

            async def stream_audio_to_client() -> None:
                """Send audio chunks to the WebSocket as they arrive."""
                while True:
                    chunk = await audio_queue.get()
                    if chunk is None:  # Sentinel: synthesis done
                        break
                    if session.tts_stop_event.is_set():
                        continue  # Drain queue but don't send
                    b64 = base64.b64encode(chunk).decode()
                    await _send_json(
                        ws, {"type": "tts_audio", "data": b64, "format": "mp3"}
                    )

            # Run synthesis and streaming concurrently
            sender_task = asyncio.create_task(stream_audio_to_client())

            await speech.synthesise_sentences(
                reply.text,
                on_audio_chunk=on_sentence_audio,
                stop_event=session.tts_stop_event,
                voice=session.tts_voice,
            )

            # Signal end of synthesis
            audio_queue.put_nowait(None)
            await sender_task

        except Exception as exc:
            logger.exception("TTS failed")
            await _send_json(ws, {"type": "error", "message": f"TTS error: {exc}"})
        finally:
            session.is_speaking = False

        await _send_json(ws, {"type": "tts_end"})
        await _send_json(ws, {"type": "status", "message": "Listening…"})

    # Queue for recognized events from SDK threads → asyncio
    recognized_queue: asyncio.Queue[str] = asyncio.Queue()

    async def process_recognized_queue() -> None:
        """Background task that processes recognized speech events."""
        while True:
            text = await recognized_queue.get()
            if text is None:  # Sentinel to stop
                break
            await handle_recognized(text)

    recognized_task = asyncio.create_task(process_recognized_queue())

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "config":
                session.stt_language = msg.get("stt_language", session.stt_language)
                session.tts_voice = msg.get("tts_voice", session.tts_voice)
                await _send_json(ws, {"type": "status", "message": "Config updated"})

            elif msg_type == "start_mic":
                if session.is_recognizing:
                    continue

                # Create recognizer with callbacks
                def on_recognizing(text: str) -> None:
                    asyncio.run_coroutine_threadsafe(
                        _send_json(ws, {"type": "recognizing", "text": text}),
                        loop,
                    )
                    # Auto barge-in: if TTS is playing, stop it immediately
                    if session.is_speaking and not session.tts_stop_event.is_set():
                        session.tts_stop_event.set()
                        asyncio.run_coroutine_threadsafe(
                            _send_json(ws, {"type": "stop_playback"}),
                            loop,
                        )

                def on_recognized(text: str) -> None:
                    asyncio.run_coroutine_threadsafe(
                        recognized_queue.put(text),
                        loop,
                    )

                def on_canceled(error: str) -> None:
                    asyncio.run_coroutine_threadsafe(
                        _send_json(ws, {"type": "error", "message": f"STT canceled: {error}"}),
                        loop,
                    )

                def on_session_stopped() -> None:
                    asyncio.run_coroutine_threadsafe(
                        _send_json(ws, {"type": "status", "message": "Recognition session ended"}),
                        loop,
                    )

                try:
                    audio_stream, recognizer = await speech.create_recognizer(
                        on_recognizing=on_recognizing,
                        on_recognized=on_recognized,
                        on_canceled=on_canceled,
                        on_session_stopped=on_session_stopped,
                        language=session.stt_language,
                    )
                    session.audio_stream = audio_stream
                    session.recognizer = recognizer

                    await asyncio.to_thread(
                        recognizer.start_continuous_recognition
                    )
                    session.is_recognizing = True
                    await _send_json(ws, {"type": "status", "message": "Listening…"})
                except Exception as exc:
                    logger.exception("Failed to start recognition")
                    await _send_json(
                        ws, {"type": "error", "message": f"Failed to start mic: {exc}"}
                    )

            elif msg_type == "audio":
                if session.audio_stream and session.is_recognizing:
                    audio_b64 = msg.get("data", "")
                    if audio_b64:
                        audio_bytes = base64.b64decode(audio_b64)
                        session.audio_stream.write(audio_bytes)

            elif msg_type == "stop_mic":
                await session.stop_recognition()
                await _send_json(ws, {"type": "status", "message": "Microphone stopped"})

            elif msg_type == "stop_speaking":
                session.tts_stop_event.set()
                await _send_json(ws, {"type": "status", "message": "Stopped speaking"})

            elif msg_type == "clear_chat":
                session.reset_conversation()
                await _send_json(ws, {"type": "status", "message": "Chat cleared"})

            else:
                await _send_json(
                    ws, {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception:
        logger.exception("Unexpected WebSocket error")
    finally:
        await session.stop_recognition()
        # Stop the recognized queue processor
        await recognized_queue.put(None)
        recognized_task.cancel()
        try:
            await recognized_task
        except asyncio.CancelledError:
            pass


# -----------------------------------------------------------------------
# Static files (must be mounted last so API routes take priority)
# -----------------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")

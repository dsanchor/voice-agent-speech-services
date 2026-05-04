"""Azure Speech SDK wrapper for continuous STT and sentence-chunked TTS.

Auth uses a managed-identity token obtained via DefaultAzureCredential,
refreshed automatically by :class:`TokenManager`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable, Optional

import azure.cognitiveservices.speech as speechsdk

from app.config import SpeechConfig as SpeechCfg
from app.token_manager import TokenManager

logger = logging.getLogger(__name__)

_SPEECH_SCOPE = "https://cognitiveservices.azure.com/.default"

# Map friendly config names → SDK enum values for TTS output.
_TTS_FORMATS: dict[str, speechsdk.SpeechSynthesisOutputFormat] = {
    "audio-16khz-32kbitrate-mono-mp3": speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3,
    "audio-24khz-48kbitrate-mono-mp3": speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3,
    "raw-16khz-16bit-mono-pcm": speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm,
}

# Regex to split text into sentences for chunked TTS
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class SpeechService:
    """High-level async façade over the Azure Speech SDK."""

    def __init__(self, cfg: SpeechCfg) -> None:
        self._cfg = cfg
        self._token_mgr = TokenManager(scope=_SPEECH_SCOPE)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_speech_config(self) -> speechsdk.SpeechConfig:
        """Build a SpeechConfig authenticated with a fresh managed-identity token."""
        token = await self._token_mgr.get_token()
        config = speechsdk.SpeechConfig(auth_token=token, region=self._cfg.region)
        config.speech_recognition_language = self._cfg.stt_language
        return config

    # ------------------------------------------------------------------
    # STT — Continuous Recognition
    # ------------------------------------------------------------------

    async def create_recognizer(
        self,
        on_recognizing: Callable[[str], None],
        on_recognized: Callable[[str], None],
        on_canceled: Callable[[str], None],
        on_session_stopped: Callable[[], None],
        language: Optional[str] = None,
    ) -> tuple[speechsdk.audio.PushAudioInputStream, speechsdk.SpeechRecognizer]:
        """Create a PushAudioInputStream and SpeechRecognizer for continuous recognition.

        Returns (audio_stream, recognizer). Caller should call
        recognizer.start_continuous_recognition() after setup.
        """
        config = await self._get_speech_config()
        if language:
            config.speech_recognition_language = language

        audio_stream = speechsdk.audio.PushAudioInputStream(
            stream_format=speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000, bits_per_sample=16, channels=1
            )
        )
        audio_config = speechsdk.audio.AudioConfig(stream=audio_stream)

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=config, audio_config=audio_config
        )

        # Wire up callbacks
        recognizer.recognizing.connect(
            lambda evt: on_recognizing(evt.result.text)
        )
        recognizer.recognized.connect(
            lambda evt: on_recognized(evt.result.text)
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech
            else None
        )
        recognizer.canceled.connect(
            lambda evt: on_canceled(
                evt.cancellation_details.error_details
                if evt.cancellation_details.error_details
                else str(evt.cancellation_details.reason)
            )
        )
        recognizer.session_stopped.connect(lambda evt: on_session_stopped())

        return audio_stream, recognizer

    # ------------------------------------------------------------------
    # TTS — Text-to-Speech (sentence-chunked for faster time-to-first-audio)
    # ------------------------------------------------------------------

    async def synthesise_sentences(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], None],
        stop_event: asyncio.Event,
        voice: Optional[str] = None,
    ) -> None:
        """Synthesise *text* sentence-by-sentence, calling *on_audio_chunk* for each.

        Stops early if *stop_event* is set (user interrupted).
        """
        sentences = _SENTENCE_RE.split(text)
        # Filter empty strings
        sentences = [s.strip() for s in sentences if s.strip()]

        for sentence in sentences:
            if stop_event.is_set():
                logger.info("TTS interrupted by stop event")
                break
            audio_data = await self._synthesise_one(sentence, voice)
            if audio_data and not stop_event.is_set():
                on_audio_chunk(audio_data)

    async def synthesise(self, text: str, voice: Optional[str] = None) -> bytes:
        """Convert *text* to audio bytes (full response, no chunking)."""
        return await self._synthesise_one(text, voice)

    async def _synthesise_one(self, text: str, voice: Optional[str] = None) -> bytes:
        """Synthesise a single text segment to audio bytes."""
        config = await self._get_speech_config()

        fmt = _TTS_FORMATS.get(
            self._cfg.tts_output_format,
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3,
        )
        config.set_speech_synthesis_output_format(fmt)

        # Set voice
        voice_name = voice or self._cfg.tts_voice
        config.speech_synthesis_voice_name = voice_name

        synthesiser = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=None
        )

        result: speechsdk.SpeechSynthesisResult = await asyncio.to_thread(
            synthesiser.speak_text, text
        )

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            logger.info("TTS synthesised %d bytes for: %s", len(result.audio_data), text[:60])
            return result.audio_data

        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation = result.cancellation_details
            logger.error(
                "TTS cancelled: reason=%s, detail=%s",
                cancellation.reason,
                cancellation.error_details,
            )
            raise RuntimeError(
                f"Speech synthesis cancelled: {cancellation.error_details}"
            )

        raise RuntimeError(f"Unexpected TTS result reason: {result.reason}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._token_mgr.close()

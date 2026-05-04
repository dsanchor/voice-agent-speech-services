"""Azure Speech SDK wrapper for STT and TTS.

Auth uses a managed-identity token obtained via DefaultAzureCredential,
refreshed automatically by :class:`TokenManager`.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional

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
    # STT — Speech-to-Text
    # ------------------------------------------------------------------

    async def recognise(self, audio_data: bytes) -> Optional[str]:
        """Transcribe *audio_data* (WAV / PCM-16 kHz 16-bit mono) to text.

        Returns the recognised text, or ``None`` when nothing was understood.
        """
        config = await self._get_speech_config()

        # Wrap raw bytes in a PushAudioInputStream so the SDK can consume them.
        stream = speechsdk.audio.PushAudioInputStream(
            stream_format=speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000, bits_per_sample=16, channels=1
            )
        )
        stream.write(audio_data)
        stream.close()

        audio_config = speechsdk.audio.AudioConfig(stream=stream)
        recogniser = speechsdk.SpeechRecognizer(
            speech_config=config, audio_config=audio_config
        )

        # Run the blocking SDK call on a thread so we don't stall the event loop.
        result: speechsdk.SpeechRecognitionResult = await asyncio.to_thread(
            recogniser.recognize_once
        )

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            logger.info("STT recognised: %s", result.text)
            return result.text

        if result.reason == speechsdk.ResultReason.NoMatch:
            logger.warning("STT no match: %s", result.no_match_details)
            return None

        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation = result.cancellation_details
            logger.error(
                "STT cancelled: reason=%s, detail=%s",
                cancellation.reason,
                cancellation.error_details,
            )
            raise RuntimeError(
                f"Speech recognition cancelled: {cancellation.error_details}"
            )

        return None

    # ------------------------------------------------------------------
    # TTS — Text-to-Speech
    # ------------------------------------------------------------------

    async def synthesise(self, text: str) -> bytes:
        """Convert *text* to audio bytes using Azure TTS.

        Returns audio in the format configured by ``TTS_OUTPUT_FORMAT``
        (default: MP3 16 kHz mono).
        """
        config = await self._get_speech_config()

        fmt = _TTS_FORMATS.get(
            self._cfg.tts_output_format,
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3,
        )
        config.set_speech_synthesis_output_format(fmt)

        # Synthesise into an in-memory stream.
        synthesiser = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=None
        )

        result: speechsdk.SpeechSynthesisResult = await asyncio.to_thread(
            synthesiser.speak_text, text
        )

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            logger.info("TTS synthesised %d bytes", len(result.audio_data))
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

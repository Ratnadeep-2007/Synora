import asyncio
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Belt-and-suspenders with app/main.py: this module may be imported by
# scripts/workers that never go through main, and the flag must be set
# before any OpenMP runtime loads.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from app.core.config import settings

logger = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()

_LANGUAGE_REGION_MAP = {
    "bn": "bn-IN",
    "en": "en-IN",
    "gu": "gu-IN",
    "hi": "hi-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "pa": "pa-IN",
    "ta": "ta-IN",
    "te": "te-IN",
}


class WhisperFallbackError(RuntimeError):
    pass


def normalize_whisper_language(value: Optional[str]) -> str:
    code = str(value or "").strip().lower()
    return _LANGUAGE_REGION_MAP.get(code, code or "unknown")


class WhisperTranscriptionService:
    """Self-hosted faster-whisper fallback for post-meeting audio."""

    @staticmethod
    def _load_model():
        global _model
        if _model is not None:
            return _model

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise WhisperFallbackError(
                "faster-whisper is not installed. Install the backend requirements."
            ) from exc

        with _model_lock:
            if _model is None:
                try:
                    logger.info(
                        "Loading local Whisper model: model=%s device=%s compute_type=%s",
                        settings.WHISPER_MODEL,
                        settings.WHISPER_DEVICE,
                        settings.WHISPER_COMPUTE_TYPE,
                    )
                    _model = WhisperModel(
                        settings.WHISPER_MODEL,
                        device=settings.WHISPER_DEVICE,
                        compute_type=settings.WHISPER_COMPUTE_TYPE,
                        cpu_threads=settings.WHISPER_CPU_THREADS,
                        download_root=settings.WHISPER_MODEL_CACHE_DIR,
                    )
                except Exception as exc:
                    raise WhisperFallbackError(
                        f"Could not load local Whisper model '{settings.WHISPER_MODEL}': {exc}"
                    ) from exc

        return _model

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "meeting.audio",
    ) -> Tuple[Dict[str, Any], str]:
        if not audio_bytes:
            raise WhisperFallbackError("Vexa returned an empty audio recording.")
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes, filename)

    def _transcribe_sync(
        self,
        audio_bytes: bytes,
        filename: str,
    ) -> Tuple[Dict[str, Any], str]:
        model = self._load_model()

        prompt = (
            settings.WHISPER_INITIAL_PROMPT.strip()
            or settings.SARVAM_KEYTERMS.replace(",", ", ").strip()
        )
        suffix = Path(filename).suffix or ".audio"

        try:
            with tempfile.NamedTemporaryFile(
                suffix=suffix,
                prefix="synora-whisper-",
                delete=False,
            ) as temp_file:
                temp_file.write(audio_bytes)
                audio_path = temp_file.name

            try:
                segments, info = model.transcribe(
                    audio_path,
                    language=settings.WHISPER_LANGUAGE_CODE.strip() or None,
                    task="transcribe",
                    beam_size=settings.WHISPER_BEAM_SIZE,
                    vad_filter=settings.WHISPER_VAD_FILTER,
                    without_timestamps=False,
                    word_timestamps=False,
                    condition_on_previous_text=True,
                    initial_prompt=prompt or None,
                )

                normalized: List[Dict[str, Any]] = []
                for index, segment in enumerate(segments):
                    text = str(getattr(segment, "text", "") or "").strip()
                    if not text:
                        continue
                    normalized.append(
                        {
                            "id": f"whisper_seg_{index:06d}",
                            "text": text,
                            "speaker": "Unknown Speaker",
                            "start_seconds": float(getattr(segment, "start", 0.0) or 0.0),
                            "end_seconds": float(getattr(segment, "end", 0.0) or 0.0),
                        }
                    )

                if not normalized:
                    raise WhisperFallbackError(
                        f"Whisper produced no transcript segments for {filename}."
                    )

                result = {
                    "language_code": normalize_whisper_language(
                        getattr(info, "language", None)
                    ),
                    "segments": normalized,
                    "transcription_provider": "whisper_faster_whisper",
                    "model": settings.WHISPER_MODEL,
                }
                return result, f"whisper:{settings.WHISPER_MODEL}"
            finally:
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove temporary Whisper audio file.")
        except WhisperFallbackError:
            raise
        except Exception as exc:
            raise WhisperFallbackError(
                f"Local Whisper transcription failed for {filename}: {exc}"
            ) from exc

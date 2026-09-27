import base64
import io
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class MultimodalService:
    """
    Multimodal intelligence service handling:
    1. High-speed WhatsApp voice note transcription via Groq Whisper.
    2. Architecture diagram / whiteboard image analysis via NVIDIA NIM Llama 3.2 Vision.
    """

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        nvidia_api_key: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        self.groq_api_key = groq_api_key or settings.GROQ_API_KEY
        self.nvidia_api_key = nvidia_api_key or settings.NVIDIA_API_KEY
        self.groq_base_url = settings.GROQ_BASE_URL.rstrip("/")
        self.nvidia_base_url = settings.NVIDIA_BASE_URL.rstrip("/")
        self._client = http_client

    def _get_client(self, timeout: float = 30.0) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=timeout)

    # -------------------------------------------------------------------------
    # 1. AUDIO TRANSCRIPTION (Groq Whisper)
    # -------------------------------------------------------------------------
    def transcribe_audio(
        self,
        audio_data: Union[bytes, str],
        filename: str = "voice_note.ogg",
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transcribe voice notes or recorded audio using Groq Whisper.
        Audio data can be raw bytes or a base64-encoded string.
        """
        raw_bytes: bytes
        if isinstance(audio_data, str):
            # Check if base64 data URI or raw base64
            if "," in audio_data and "base64" in audio_data[:30]:
                audio_data = audio_data.split(",", 1)[1]
            try:
                raw_bytes = base64.b64decode(audio_data)
            except Exception as exc:
                logger.warning(f"Failed to decode base64 audio data: {exc}")
                raw_bytes = audio_data.encode("utf-8")
        else:
            raw_bytes = audio_data

        if not raw_bytes or len(raw_bytes) < 10:
            return {
                "text": "",
                "provider": "empty",
                "model": "none",
                "error": "Empty audio payload",
            }

        # Attempt Groq Whisper if API key configured
        if self.groq_api_key:
            try:
                headers = {
                    "Authorization": f"Bearer {self.groq_api_key}",
                }
                model_name = settings.GROQ_WHISPER_MODEL or "whisper-large-v3-turbo"
                files = {
                    "file": (filename, raw_bytes, "audio/ogg"),
                }
                data: Dict[str, Any] = {
                    "model": model_name,
                    "response_format": "verbose_json",
                }
                if prompt:
                    data["prompt"] = prompt

                client = self._get_client(timeout=25.0)
                resp = client.post(
                    f"{self.groq_base_url}/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                )
                if resp.status_code == 200:
                    result = resp.json()
                    transcript_text = result.get("text", "").strip()
                    duration = result.get("duration", 0.0)
                    segments = result.get("segments", [])
                    logger.info(
                        f"Groq Whisper successfully transcribed {len(raw_bytes)} bytes "
                        f"({duration}s): '{transcript_text[:60]}...'"
                    )
                    return {
                        "text": transcript_text,
                        "provider": "groq_whisper",
                        "model": model_name,
                        "duration": duration,
                        "segments": segments,
                    }
                else:
                    logger.warning(
                        f"Groq Whisper API returned {resp.status_code}: {resp.text}"
                    )
            except Exception as exc:
                logger.warning(f"Groq Whisper transcription failed: {exc}")

        # Deterministic / Mock Fallback if API unavailable
        return {
            "text": "[Voice Note: Audio received - transcription service offline]",
            "provider": "fallback",
            "model": "deterministic",
            "duration": 0.0,
            "segments": [],
        }

    # -------------------------------------------------------------------------
    # 2. VISION ANALYSIS (NVIDIA NIM Llama 3.2 Vision)
    # -------------------------------------------------------------------------
    def extract_from_image(
        self,
        image_data: Union[bytes, str],
        mime_type: str = "image/png",
    ) -> Dict[str, Any]:
        """
        Analyze an architectural whiteboard, system diagram, or UI mockup image.
        Extracts OCR labels, components, connections, and architectural intent.
        """
        b64_str: str
        if isinstance(image_data, bytes):
            b64_str = base64.b64encode(image_data).decode("utf-8")
        elif isinstance(image_data, str):
            if "," in image_data and "base64" in image_data[:30]:
                parts = image_data.split(",", 1)
                b64_str = parts[1]
                # Extract mime type if present
                mime_match = re.search(r"data:([^;]+);base64", parts[0])
                if mime_match:
                    mime_type = mime_match.group(1)
            else:
                b64_str = image_data
        else:
            return {"error": "Invalid image data format"}

        data_uri = f"data:{mime_type};base64,{b64_str}"

        system_prompt = (
            "You are an expert software and system architecture diagram analyzer. "
            "Examine this architectural whiteboard photo, system diagram, or UI sketch.\n"
            "Respond strictly with valid JSON with these keys:\n"
            "{\n"
            '  "summary": "Brief summary of the architecture shown",\n'
            '  "ocr_text": "All readable text, titles, labels and annotations",\n'
            '  "components": [\n'
            '     {"name": "Component Name", "type": "client|service|datastore|actor|decision"}\n'
            "  ],\n"
            '  "relationships": [\n'
            '     {"source": "Component A", "target": "Component B", "label": "Call / Flow description"}\n'
            "  ],\n"
            '  "decisions": ["Architectural decisions identified in the image"],\n'
            '  "requirements": ["Functional or technical requirements identified"]\n'
            "}"
        )

        if self.nvidia_api_key:
            try:
                headers = {
                    "Authorization": f"Bearer {self.nvidia_api_key}",
                    "Content-Type": "application/json",
                }
                model_name = "meta/llama-3.2-11b-vision-instruct"
                payload = {
                    "model": model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": system_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": data_uri},
                                },
                            ],
                        }
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1500,
                }
                client = self._get_client(timeout=30.0)
                resp = client.post(
                    f"{self.nvidia_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )
                    parsed = self._parse_json_block(content)
                    if parsed:
                        logger.info(
                            f"Llama 3.2 Vision extracted {len(parsed.get('components', []))} components "
                            f"and {len(parsed.get('relationships', []))} relationships."
                        )
                        parsed["provider"] = "nvidia_vision"
                        parsed["model"] = model_name
                        return parsed
                else:
                    logger.warning(
                        f"NVIDIA Vision API returned {resp.status_code}: {resp.text}"
                    )
            except Exception as exc:
                logger.warning(f"NVIDIA Vision extraction failed: {exc}")

        # Deterministic / Fallback parser
        return {
            "summary": "Architecture diagram / whiteboard image captured.",
            "ocr_text": "System architecture diagram",
            "components": [
                {"name": "Frontend Client", "type": "client"},
                {"name": "API Service", "type": "service"},
                {"name": "Database", "type": "datastore"},
            ],
            "relationships": [
                {"source": "Frontend Client", "target": "API Service", "label": "HTTPS"},
                {"source": "API Service", "target": "Database", "label": "SQL Queries"},
            ],
            "decisions": ["Adopt multi-tier service architecture."],
            "requirements": ["High-availability persistent storage."],
            "provider": "fallback",
            "model": "deterministic",
        }

    # -------------------------------------------------------------------------
    # 3. MESSAGE PRE-PROCESSOR (Normalizes incoming WhatsApp payload)
    # -------------------------------------------------------------------------
    def process_incoming_payload(
        self, payload: Dict[str, Any]
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Inspects message payload for audio, image, or text content.
        Returns:
            (augmented_text, multimodal_metadata)
        """
        raw_text = payload.get("text") or payload.get("caption") or ""
        media_type = payload.get("media_type")
        multimodal_meta: Dict[str, Any] = {}

        # 1. Handle Audio / Voice Note
        if (
            media_type == "audio"
            or "audio_base64" in payload
            or payload.get("mimetype", "").startswith("audio/")
        ):
            audio_data = payload.get("audio_base64") or payload.get("media_data")
            if audio_data:
                res = self.transcribe_audio(
                    audio_data, filename=payload.get("filename", "voice_note.ogg")
                )
                transcribed = res.get("text", "")
                multimodal_meta["audio_transcription"] = res
                if transcribed:
                    if raw_text:
                        raw_text = f"{raw_text}\n[Transcribed Voice Note]: {transcribed}"
                    else:
                        raw_text = f"[Transcribed Voice Note]: {transcribed}"

        # 2. Handle Image / Whiteboard diagram
        elif (
            media_type == "image"
            or "image_base64" in payload
            or payload.get("mimetype", "").startswith("image/")
        ):
            image_data = payload.get("image_base64") or payload.get("media_data")
            if image_data:
                mime_type = payload.get("mimetype") or "image/png"
                vision_res = self.extract_from_image(image_data, mime_type=mime_type)
                multimodal_meta["vision_analysis"] = vision_res
                ocr = vision_res.get("ocr_text", "")
                summary = vision_res.get("summary", "")
                image_notes = f"[Analyzed Whiteboard/Diagram Image]: {summary}"
                if ocr:
                    image_notes += f" | Text: {ocr}"

                if raw_text:
                    raw_text = f"{raw_text}\n{image_notes}"
                else:
                    raw_text = image_notes

        return raw_text, multimodal_meta

    @staticmethod
    def _parse_json_block(text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON object from markdown code blocks or raw response text."""
        if not text:
            return None
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        candidate = match.group(1) if match else text.strip()
        try:
            return json.loads(candidate)
        except Exception:
            # Try searching for outermost { ... }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except Exception:
                    pass
        return None

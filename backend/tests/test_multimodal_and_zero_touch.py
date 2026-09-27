import base64
import json
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.services.google_oauth import GoogleOAuthService
from app.services.multimodal_service import MultimodalService
from app.services.whatsapp_service import WhatsAppIntelligenceService


def test_multimodal_service_init_and_empty():
    """Verify MultimodalService handles empty/short audio safely."""
    service = MultimodalService()
    res = service.transcribe_audio(b"")
    assert res["text"] == ""
    assert res["provider"] == "empty"


def test_multimodal_audio_transcription_groq_mock():
    """Verify Groq Whisper transcription call structure and response parsing."""
    mock_http_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "text": "Team, we should use Redis for session caching.",
        "duration": 4.5,
        "segments": [{"text": "Team, we should use Redis for session caching.", "start": 0.0, "end": 4.5}],
    }
    mock_http_client.post.return_value = mock_response

    service = MultimodalService(
        groq_api_key="gsk_test_key",
        http_client=mock_http_client,
    )

    fake_audio_bytes = b"OggS" + b"\x00" * 100
    res = service.transcribe_audio(fake_audio_bytes, filename="voice_note.ogg")

    assert res["text"] == "Team, we should use Redis for session caching."
    assert res["provider"] == "groq_whisper"
    assert res["duration"] == 4.5
    assert len(res["segments"]) == 1

    # Verify endpoint called
    assert mock_http_client.post.called
    call_args, call_kwargs = mock_http_client.post.call_args
    assert "audio/transcriptions" in call_args[0]
    assert "Bearer gsk_test_key" in call_kwargs["headers"]["Authorization"]


def test_multimodal_vision_extraction_mock():
    """Verify Llama 3.2 Vision extraction extracts OCR, components, and relationships."""
    mock_http_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "summary": "Three-tier architecture with React Frontend, FastAPI Backend, and PostgreSQL DB.",
                        "ocr_text": "Frontend -> API Gateway -> Database",
                        "components": [
                            {"name": "React Client", "type": "client"},
                            {"name": "API Gateway", "type": "service"},
                            {"name": "PostgreSQL", "type": "datastore"},
                        ],
                        "relationships": [
                            {"source": "React Client", "target": "API Gateway", "label": "HTTPS"},
                            {"source": "API Gateway", "target": "PostgreSQL", "label": "SQL"},
                        ],
                        "decisions": ["Deploy API Gateway for rate limiting"],
                        "requirements": ["PostgreSQL ACID compliance"],
                    })
                }
            }
        ]
    }
    mock_http_client.post.return_value = mock_response

    service = MultimodalService(
        nvidia_api_key="nvapi_test_key",
        http_client=mock_http_client,
    )

    fake_image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    res = service.extract_from_image(fake_image_bytes, mime_type="image/png")

    assert "Three-tier architecture" in res["summary"]
    assert len(res["components"]) == 3
    assert len(res["relationships"]) == 2
    assert "API Gateway" in [c["name"] for c in res["components"]]


def test_multimodal_payload_preprocessing_voice_note():
    """Voice note in WhatsApp payload is transcribed and prepended to text."""
    service = MultimodalService()
    with patch.object(service, "transcribe_audio") as mock_transcribe:
        mock_transcribe.return_value = {
            "text": "Confirmed: we will use PostgreSQL for audit logs.",
            "provider": "groq_whisper",
            "duration": 3.2,
        }

        payload = {
            "audio_base64": base64.b64encode(b"fake audio data").decode("utf-8"),
            "media_type": "audio",
            "sender_name": "Arvind",
        }

        text, meta = service.process_incoming_payload(payload)
        assert "[Transcribed Voice Note]: Confirmed: we will use PostgreSQL for audit logs." in text
        assert "audio_transcription" in meta


def test_multimodal_payload_preprocessing_whiteboard_image():
    """Whiteboard image in WhatsApp payload is analyzed and components extracted."""
    service = MultimodalService()
    with patch.object(service, "extract_from_image") as mock_vision:
        mock_vision.return_value = {
            "summary": "Microservices diagram showing Auth and Billing.",
            "ocr_text": "Auth Service, Billing Service",
            "components": [{"name": "Auth Service", "type": "service"}],
            "relationships": [],
        }

        payload = {
            "image_base64": base64.b64encode(b"fake image data").decode("utf-8"),
            "media_type": "image",
            "caption": "Check our proposed architecture sketch",
        }

        text, meta = service.process_incoming_payload(payload)
        assert "Check our proposed architecture sketch" in text
        assert "[Analyzed Whiteboard/Diagram Image]: Microservices diagram" in text
        assert "vision_analysis" in meta


def test_zero_touch_google_meet_connection_bootstrap(db_session: Session):
    """When GOOGLE_REFRESH_TOKEN is present in .env, ensure_env_connection automatically seeds connection."""
    custom_settings = Settings(
        GOOGLE_CLIENT_ID="test_client_id",
        GOOGLE_CLIENT_SECRET="test_client_secret",
        GOOGLE_REFRESH_TOKEN="1//test_permanent_refresh_token_12345",
    )
    oauth_service = GoogleOAuthService(settings=custom_settings)

    # 1. Bootstrap connection without user clicking in UI
    conn = oauth_service.ensure_env_connection(db_session, user_id="usr_auto_worker")
    assert conn is not None
    assert conn.provider == "google"
    assert conn.status == ConnectionStatus.ACTIVE.value
    assert conn.provider_account_id == "google_env_account"

    # Decrypt and verify refresh token stored safely
    creds = oauth_service.encryption.decrypt_dict(conn.encrypted_credentials)
    assert creds["refresh_token"] == "1//test_permanent_refresh_token_12345"

    # 2. Idempotent call returns existing connection
    conn2 = oauth_service.ensure_env_connection(db_session, user_id="usr_auto_worker")
    assert conn2.id == conn.id

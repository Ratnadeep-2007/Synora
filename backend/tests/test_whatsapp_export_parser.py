import io
import json
import zipfile
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.whatsapp_export_parser import WhatsAppZipParser


def create_sample_whatsapp_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        chat_content = (
            "7/8/26, 10:13\u202fAM - Messages and calls are end-to-end encrypted.\n"
            "7/8/26, 10:15\u202fAM - Alice: Hello team, we need to decide on the architecture for Synora.\n"
            "7/8/26, 10:16\u202fAM - Bob: We will use PostgreSQL for the project state and Excalidraw for the workspace.\n"
            "7/8/26, 10:17\u202fAM - Alice: IMG-20260716-WA0002.jpg (file attached)\n"
            "Here is the architecture whiteboard diagram.\n"
        )
        zf.writestr("WhatsApp Chat with Trial Project.txt", chat_content.encode("utf-8"))
        zf.writestr("IMG-20260716-WA0002.jpg", b"fake-jpg-content")
    buf.seek(0)
    return buf.getvalue()


def test_whatsapp_zip_parser():
    zip_bytes = create_sample_whatsapp_zip()
    parser = WhatsAppZipParser(zip_bytes)
    messages = parser.parse_messages()

    assert len(messages) == 3
    assert messages[0]["sender"] == "Alice"
    assert "architecture for Synora" in messages[0]["text"]

    assert messages[1]["sender"] == "Bob"
    assert "PostgreSQL" in messages[1]["text"]

    assert messages[2]["sender"] == "Alice"
    assert messages[2]["attachment"] == "IMG-20260716-WA0002.jpg"
    assert "whiteboard diagram" in messages[2]["text"]

    raw_att = parser.read_attachment_bytes("IMG-20260716-WA0002.jpg")
    assert raw_att == b"fake-jpg-content"


def test_whatsapp_import_export_endpoint(client: TestClient, db_session):
    from app.services.project_agent_service import ProjectAgentService
    agent_service = ProjectAgentService()
    agent_service.get_or_create_project(
        project_id="proj_default",
        name="Synora Platform Core",
        description="Authoritative project for testing bulk imports",
        workspace_id="ws_default",
        db=db_session,
    )

    zip_bytes = create_sample_whatsapp_zip()

    response = client.post(
        "/connectors/whatsapp/import-export?target_project=proj_default&limit=10",
        files={"file": ("WhatsApp Chat with Trial Project.zip", zip_bytes, "application/zip")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_in_archive"] == 3
    assert data["processed_count"] == 3
    assert data["target_project"] == "proj_default"
    assert data["matched_count"] >= 1

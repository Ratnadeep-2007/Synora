"""End-to-end tests for the WhatsApp chat-export (.zip) import path.

Verifies the full chain:
  .zip export -> parser -> multimodal preprocessing -> shared Context
  Intelligence + Knowledge Intelligence -> project evidence / Unknown Context
"""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.context_resolution import UnknownContextItem
from app.models.evidence import Evidence
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.models.source_event import SourceEvent
from app.services.project_agent_service import ProjectAgentService
from app.services.whatsapp_export_parser import WhatsAppZipParser

CHAT_TXT = """12/09/2026, 14:24 - Messages and calls are end-to-end encrypted.
12/09/2026, 14:25 - Alice: For proj_export_test: we decided to integrate Digilocker KYC API.
12/09/2026, 14:26 - Bob: Agreed, and the requirement is that claims above 5000 need AML checks.
12/09/2026, 14:27 - Alice: I will prepare the migration by Friday.
12/09/2026, 14:30 - Carol: unrelated chatter about the office lunch plan
"""


def _build_zip(chat_text: str = CHAT_TXT, extra_files: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("WhatsApp Chat with Trial Project/_chat.txt", chat_text)
        for name, data in (extra_files or {}).items():
            zf.writestr(f"WhatsApp Chat with Trial Project/{name}", data)
    return buf.getvalue()


# --- parser unit behaviour ----------------------------------------------------
def test_parser_reads_messages_and_filters_system_lines():
    parser = WhatsAppZipParser(_build_zip())
    messages = parser.parse_messages()
    senders = [m["sender"] for m in messages]
    # The end-to-end-encryption system notice must be filtered, not parsed as a message.
    assert "Messages and calls are end-to-end encrypted." not in " ".join(m["text"] for m in messages)
    assert senders == ["Alice", "Bob", "Alice", "Carol"]
    assert messages[0]["text"].startswith("For proj_export_test")


def test_parser_handles_multiline_messages():
    chat = (
        "12/09/2026, 14:25 - Alice: first line\n"
        "second line of the same message\n"
        "12/09/2026, 14:26 - Bob: reply\n"
    )
    messages = WhatsAppZipParser(_build_zip(chat)).parse_messages()
    assert len(messages) == 2
    assert "second line" in messages[0]["text"]


def test_parser_attaches_referenced_media():
    upload = _build_zip(
        "12/09/2026, 14:25 - Alice: PTT-20260912-WA0001.opus\n",
        extra_files={"PTT-20260912-WA0001.opus": b"\x00" * 32},
    )
    messages = WhatsAppZipParser(upload).parse_messages()
    assert messages[0]["attachment"] == "WhatsApp Chat with Trial Project/PTT-20260912-WA0001.opus"


def test_parser_prefers_canonical_chat_file():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.txt", "unrelated notes that are not a chat export")
        zf.writestr("_chat.txt", "12/09/2026, 14:25 - Alice: real message\n")
    parser = WhatsAppZipParser(buf.getvalue())
    assert parser.txt_filename == "_chat.txt"
    assert len(parser.parse_messages()) == 1


def test_parser_rejects_zip_without_chat_file():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("random.md", "no chat here")
        zf.writestr("image.png", b"\x00\x01")
    with pytest.raises(ValueError):
        WhatsAppZipParser(buf.getvalue())


# --- endpoint / end-to-end ----------------------------------------------------
def _project(db: Session, project_id: str, name: str):
    return ProjectAgentService().get_or_create_project(
        project_id=project_id, db=db, workspace_id="ws_default", name=name
    )


def test_import_export_routes_and_classifies(client: TestClient, test_user, db_session: Session):
    _project(db_session, "proj_export_test", "Export Test Project")

    resp = client.post(
        "/connectors/whatsapp/import-export",
        files={"file": ("WhatsApp Chat with Trial Project.zip", _build_zip(), "application/zip")},
        headers={"X-User-ID": test_user.id},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["ok"] is True
    assert data["processed_count"] == 4
    # Alice's explicit project reference resolves; the lunch chatter goes to Unknown Context.
    assert data["matched_count"] >= 1
    assert data["unknown_context_count"] >= 1

    # Evidence exists for the resolved project and for Unknown Context.
    project_evidence = (
        db_session.query(Evidence).filter(Evidence.project_id == "proj_export_test").all()
    )
    assert project_evidence, "expected evidence routed to the named project"
    unknown_items = (
        db_session.query(UnknownContextItem)
        .filter(UnknownContextItem.status == "pending")
        .all()
    )
    assert unknown_items, "expected unresolved content in Unknown Context"
    assert all(i.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID for i in unknown_items)


def test_import_export_with_target_project_forced(client: TestClient, test_user, db_session: Session):
    _project(db_session, "proj_force_target", "Forced Target")

    resp = client.post(
        "/connectors/whatsapp/import-export?target_project=proj_force_target",
        files={"file": ("WhatsApp Chat with Trial Project.zip", _build_zip(), "application/zip")},
        headers={"X-User-ID": test_user.id},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # target_project prefixes every message with an explicit project reference,
    # so nothing should land in Unknown Context. (Casual chatter is still
    # filtered and therefore not counted as matched.)
    assert data["unknown_context_count"] == 0
    assert data["matched_count"] >= 1


def test_import_export_rejects_non_zip(client: TestClient, test_user):
    resp = client.post(
        "/connectors/whatsapp/import-export",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers={"X-User-ID": test_user.id},
    )
    assert resp.status_code == 400


def test_import_export_marks_media_without_fabricating(client: TestClient, test_user, db_session: Session):
    """Voice notes must be reported as not-processed, never fabricated as content."""
    _project(db_session, "proj_media_test", "Media Test")

    upload = _build_zip(
        "12/09/2026, 14:25 - Alice: For proj_media_test: PTT-20260912-WA0001.opus\n",
        extra_files={"PTT-20260912-WA0001.opus": b"\x00" * 64},
    )
    resp = client.post(
        "/connectors/whatsapp/import-export",
        files={"file": ("WhatsApp Chat with Trial Project.zip", upload, "application/zip")},
        headers={"X-User-ID": test_user.id},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True

    evidence = db_session.query(Evidence).all()
    joined = " ".join(e.content or "" for e in evidence)
    # No invented architecture must appear when the transcription provider is offline.
    assert "Frontend Client" not in joined
    assert "API Service" not in joined


# --- idempotency --------------------------------------------------------------
def test_reimport_is_idempotent(client: TestClient, test_user, db_session: Session):
    _project(db_session, "proj_idem_export", "Idempotent Export")

    payload = _build_zip("12/09/2026, 14:25 - Alice: For proj_idem_export: we decided to use Redis.\n")
    headers = {"X-User-ID": test_user.id}

    first = client.post(
        "/connectors/whatsapp/import-export",
        files={"file": ("WhatsApp Chat with Trial Project.zip", payload, "application/zip")},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    evidence_after_first = db_session.query(Evidence).count()

    second = client.post(
        "/connectors/whatsapp/import-export",
        files={"file": ("WhatsApp Chat with Trial Project.zip", payload, "application/zip")},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    evidence_after_second = db_session.query(Evidence).count()

    # Re-importing the same archive must not duplicate evidence.
    assert evidence_after_second == evidence_after_first

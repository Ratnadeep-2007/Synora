"""API regressions for direct input, channel routing and human triage."""
import hashlib
import hmac
import io
import json
import time
from unittest.mock import patch

from app.connectors.registry import registry
from app.connectors.slack import SlackConnector
from app.connectors.base import FetchEventsResult
from app.models.context_resolution import UnknownContextItem
from app.models.evidence import Evidence
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.models.source_event import SourceEvent
from app.services.direct_input_service import MAX_UPLOAD_BYTES
from app.services.project_agent_service import ProjectAgentService

HEADERS = {"X-User-ID": "usr_test_lead"}
TEXT = "Requirement: procure 50 specialized FPGA accelerator boards for physical layer encoding."


def project(db):
    return ProjectAgentService().get_or_create_project(
        project_id="proj_direct_input", db=db, workspace_id="ws_default", name="Direct Input"
    )


def test_manual_unknown_assign_and_replay(client, db_session):
    project(db_session)
    response = client.post("/connectors/manual/text", json={"text": TEXT}, headers=HEADERS)
    assert response.status_code == 200, response.text
    outcome = response.json()
    assert outcome["outcome"] == "unknown_context"
    ev = db_session.get(Evidence, outcome["evidence_id"])
    assert ev.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    assert ev.content == TEXT
    assigned = client.post(f"/unknown-context/items/{outcome['unknown_item_id']}/assign",
                           json={"project_id": "proj_direct_input"}, headers=HEADERS)
    assert assigned.status_code == 200, assigned.text
    db_session.refresh(ev)
    assert ev.project_id == "proj_direct_input"
    replay = client.post("/connectors/manual/text", json={"text": TEXT}, headers=HEADERS).json()
    assert replay["outcome"] == "duplicate"
    assert db_session.query(Evidence).count() == 1


def test_manual_trusted_project_and_invalid_target(client, db_session):
    project(db_session)
    response = client.post("/connectors/manual/text", json={
        "text": "Decision: We will use PostgreSQL for storage.", "project_id": "proj_direct_input"
    }, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "resolved"
    invalid = client.post("/connectors/manual/text", json={"text": TEXT, "project_id": "no_project"}, headers=HEADERS)
    assert invalid.status_code == 404
    assert client.post("/connectors/manual/text", json={"text": "   "}, headers=HEADERS).status_code == 400
    assert client.post("/connectors/manual/text", json={"text": TEXT}).status_code == 401


def test_upload_text_and_bad_files(client, db_session):
    response = client.post("/connectors/manual/upload", files={"file": ("notes.md", TEXT.encode())}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "ignored"
    assert db_session.query(Evidence).count() == 0
    assert db_session.query(UnknownContextItem).count() == 0
    for name, content, status in [
        ("empty.txt", b"", 400), ("bad.txt", b"\xff", 400),
        ("program.exe", b"binary", 415), ("scene.json", b"[]", 415),
        ("huge.txt", b"x" * (MAX_UPLOAD_BYTES + 1), 413)
    ]:
        res = client.post("/connectors/manual/upload", files={"file": (name, content)}, headers=HEADERS)
        assert res.status_code == status, res.text


def test_docx_upload(client):
    from docx import Document
    document = Document(); document.add_paragraph(TEXT)
    content = io.BytesIO(); document.save(content)
    response = client.post("/connectors/manual/upload", files={"file": ("notes.docx", content.getvalue())}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "ignored"


def test_removed_input_routes_and_scene_uploads(client):
    for path in ("/connectors/excalidraw/ingest", "/connectors/slack/events",
                 "/connectors/slack/sync?channel=C1", "/projects/proj_direct_input/excalidraw/ingest"):
        assert client.post(path, json={"elements": []}, headers=HEADERS).status_code == 404
    response = client.post("/connectors/manual/upload", files={"file": ("drawing.excalidraw", b'{"elements": []}')}, headers=HEADERS)
    assert response.status_code == 415
    providers = [c["provider"] for c in client.get("/connectors").json()]
    assert set(providers) == {"google_meet", "whatsapp"}


def image_bytes(fmt="PNG"):
    from PIL import Image
    data = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(data, format=fmt)
    return data.getvalue()


def test_image_project_provenance_and_retry(client, db_session):
    project(db_session)
    data = image_bytes()
    analysis = {"processed": True, "ocr_text": TEXT, "summary": "FPGA procurement", "provider": "test"}
    with patch("app.services.multimodal_service.MultimodalService.extract_from_image", return_value=analysis):
        response = client.post("/connectors/manual/upload", files={"file": ("notes.png", data)}, data={"project_id": "proj_direct_input"}, headers=HEADERS)
        assert response.status_code == 200, response.text
        assert response.json()["source"] == "image_upload"
        assert response.json()["outcome"] == "resolved"
        analysis["summary"] = "A different OCR summary"
        retry = client.post("/connectors/manual/upload", files={"file": ("notes.png", data)}, data={"project_id": "proj_direct_input"}, headers=HEADERS)
        assert retry.json()["outcome"] == "duplicate"
    event = db_session.query(SourceEvent).filter_by(source="image_upload").one()
    payload = json.loads(event.payload_json)
    assert payload["image_base64"]
    assert payload["sha256"] == hashlib.sha256(data).hexdigest()
    assert db_session.query(Evidence).count() == 1


def test_image_unavailable_and_invalid_files(client, db_session):
    with patch("app.services.multimodal_service.MultimodalService.extract_from_image", return_value={"processed": False}):
        response = client.post("/connectors/manual/upload", files={"file": ("notes.png", image_bytes())}, headers=HEADERS)
        assert response.status_code == 503
    for name, data in [("notes.png", b"fake image"), ("notes.jpg", image_bytes())]:
        assert client.post("/connectors/manual/upload", files={"file": (name, data)}, headers=HEADERS).status_code == 400
    assert db_session.query(Evidence).count() == 0


def test_pdf_upload(client):
    # A minimal valid text PDF exercises the extractor without a cloud provider.
    stream = b"BT /F1 12 Tf 50 750 Td (Requirement: FPGA accelerator boards for encoding.) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"; offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf)); pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    response = client.post("/connectors/manual/upload", files={"file": ("notes.pdf", pdf)}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "ignored"


def test_unmatched_image_is_ignored_without_memory_or_triage(client, db_session):
    project(db_session)
    analysis = {"processed": True, "ocr_text": TEXT, "summary": "FPGA procurement"}
    with patch("app.services.multimodal_service.MultimodalService.extract_from_image", return_value=analysis):
        response = client.post("/connectors/manual/upload", files={"file": ("notes.png", image_bytes())}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "ignored"
    assert not response.json()["evidence_id"]
    assert db_session.query(Evidence).count() == 0
    assert db_session.query(UnknownContextItem).count() == 0
    assert db_session.query(SourceEvent).count() == 0


def test_matching_file_updates_project_memory(client, db_session):
    project(db_session)
    text = "Decision: We will use PostgreSQL for storage."
    response = client.post("/connectors/manual/upload", files={"file": ("notes.txt", text.encode())},
                           data={"project_id": "proj_direct_input"}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "resolved"
    from app.models.project_state import ProjectState
    state = db_session.query(ProjectState).filter_by(project_id="proj_direct_input").one()
    assert "PostgreSQL" in state.decisions_json
    assert db_session.query(UnknownContextItem).count() == 0


def test_image_auto_matches_existing_project_and_updates_memory(client, db_session):
    project(db_session)
    analysis = {"processed": True,
                "ocr_text": "[proj_direct_input] Decision: We will use Redis for session storage.",
                "summary": "Direct Input architecture"}
    with patch("app.services.multimodal_service.MultimodalService.extract_from_image", return_value=analysis):
        response = client.post("/connectors/manual/upload", files={"file": ("architecture.png", image_bytes())}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "resolved"
    assert response.json()["project_id"] == "proj_direct_input"
    from app.models.project_state import ProjectState
    state = db_session.query(ProjectState).filter_by(project_id="proj_direct_input").one()
    assert "Redis" in state.decisions_json
    assert db_session.query(UnknownContextItem).count() == 0

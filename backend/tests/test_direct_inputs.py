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
    assert response.json()["outcome"] == "unknown_context"
    assert db_session.get(Evidence, response.json()["evidence_id"]).source == "file_upload"
    for name, content, status in [
        ("empty.txt", b"", 400), ("bad.txt", b"\xff", 400),
        ("program.exe", b"binary", 415), ("scene.json", b"[]", 400),
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
    assert response.json()["outcome"] == "unknown_context"


def test_drawing_and_uploaded_scene_preserve_raw_elements(client, db_session):
    scene = {"name": "Input", "elements": [{"id": "node", "type": "text", "text": TEXT}]}
    response = client.post("/connectors/excalidraw/ingest", json=scene, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "unknown_context"
    event = db_session.query(SourceEvent).filter_by(source="excalidraw").one()
    assert json.loads(event.payload_json)["elements"] == scene["elements"]
    upload = client.post("/connectors/manual/upload", files={"file": ("drawing.excalidraw", json.dumps(scene).encode())}, headers=HEADERS)
    assert upload.status_code == 200, upload.text
    assert upload.json()["source"] == "excalidraw"
    empty = client.post("/connectors/excalidraw/ingest", json={"elements": []}, headers=HEADERS)
    assert empty.status_code == 400


def test_signed_slack_event_routes_to_unknown_and_replays(client, db_session):
    connector = registry.get("slack")
    payload = {"type": "event_callback", "team_id": "T1", "event": {
        "type": "message", "channel": "C1", "ts": "12345.6", "user": "U1", "text": TEXT
    }}
    body = json.dumps(payload).encode(); timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(b"test-secret", b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    headers = {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature, "Content-Type": "application/json"}
    with patch.object(connector, "signing_secret", "test-secret"):
        response = client.post("/connectors/slack/events", content=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["outcomes"][0]["outcome"] == "unknown_context"
        replay = client.post("/connectors/slack/events", content=body, headers=headers)
        assert replay.json()["outcomes"][0]["outcome"] == "duplicate"
    assert db_session.query(UnknownContextItem).count() == 1
    assert db_session.query(Evidence).count() == 1
    assert not SlackConnector(signing_secret="").verify_webhook(body, headers)


def test_slack_sync_routes_history_and_reports_pagination(client, db_session):
    connector = registry.get("slack")
    event = connector.normalize({"text": TEXT, "ts": "555", "user": "U1"}, "message", channel="C2")
    with patch("app.api.connectors.settings.SLACK_BOT_TOKEN", "xoxb-test"), patch.object(
        connector, "fetch_events", return_value=FetchEventsResult(events=[event], next_cursor="next", has_more=True)
    ):
        response = client.post("/connectors/slack/sync?channel=C2", headers=HEADERS)
        assert response.status_code == 200, response.text
        assert response.json()["outcomes"][0]["outcome"] == "unknown_context"
        assert response.json()["next_cursor"] == "next"
    with patch("app.api.connectors.settings.SLACK_BOT_TOKEN", ""):
        assert client.post("/connectors/slack/sync?channel=C2", headers=HEADERS).status_code == 503


def test_diagram_connections_keep_arrow_direction():
    from app.services.direct_input_service import diagram_text
    elements = [
        {"id": "a", "type": "rectangle", "boundElements": [{"id": "ta", "type": "text"}]},
        {"id": "ta", "type": "text", "text": "Client"},
        {"id": "b", "type": "rectangle", "boundElements": [{"id": "tb", "type": "text"}]},
        {"id": "tb", "type": "text", "text": "API"},
        {"id": "arrow", "type": "arrow", "startBinding": {"elementId": "a"},
         "endBinding": {"elementId": "b"}, "startArrowhead": None, "endArrowhead": "arrow"},
    ]
    assert "Connection: Client -> API" in diagram_text(elements)
    assert "Connection: API -> Client" not in diagram_text(elements)
    elements[-1].update(startArrowhead="arrow", endArrowhead=None)
    assert "Connection: API -> Client" in diagram_text(elements)
    assert "Connection: Client -> API" not in diagram_text(elements)


def test_invalid_drawing_shape_is_validation_error(client):
    response = client.post("/connectors/excalidraw/ingest", json={"elements": [1]}, headers=HEADERS)
    assert response.status_code == 422


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
    assert response.json()["outcome"] == "unknown_context"

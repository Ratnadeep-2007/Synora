"""User-submitted sources share the same evidence/routing boundary as channels."""
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.project import Project
from app.services.source_intelligence_pipeline import SourceIntelligencePipeline

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 200_000


def diagram_text(elements: list[Dict[str, Any]]) -> str:
    """Keep node labels and bound arrow directions in extracted evidence."""
    active = {str(e.get("id")): e for e in elements if not e.get("isDeleted")}
    def label(element_id: Optional[str]) -> str:
        element = active.get(str(element_id), {})
        own = element.get("text") or element.get("originalText")
        if own:
            return str(own)
        return " ".join(str(active.get(str(bound.get("id")), {}).get("text") or "")
                        for bound in element.get("boundElements", [])
                        if isinstance(bound, dict) and bound.get("type") == "text").strip()
    lines = [str(e.get("text") or e.get("originalText") or "") for e in active.values()
             if e.get("text") or e.get("originalText")]
    for element in active.values():
        if element.get("type") != "arrow":
            continue
        start = label((element.get("startBinding") or {}).get("elementId"))
        end = label((element.get("endBinding") or {}).get("elementId"))
        if not start or not end:
            continue
        if element.get("endArrowhead"):
            lines.append(f"Connection: {start} -> {end}")
        if element.get("startArrowhead"):
            lines.append(f"Connection: {end} -> {start}")
        if not element.get("endArrowhead") and not element.get("startArrowhead"):
            lines.append(f"Connection: {start} -- {end} (undirected)")
    return "\n".join(lines).strip()


def validate_target(project_id: Optional[str], db: Session) -> None:
    if project_id and not db.query(Project).filter(
        Project.id == project_id, Project.is_system.is_(False)
    ).first():
        raise HTTPException(404, "Target project does not exist or is a system project.")


def process_input(source: str, payload: Dict[str, Any], db: Session, tenant_id: str,
                  actor_id: str, project_id: Optional[str] = None,
                  source_event_id: Optional[str] = None) -> Dict[str, Any]:
    validate_target(project_id, db)
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "Input must contain text or labeled diagram elements.")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(413, "Extracted text exceeds 200,000 characters.")
    # Content-addressed within actor + tenant + target: safe retry, distinct routing.
    digest = hashlib.sha256(json.dumps(
        [tenant_id, actor_id, project_id, payload], sort_keys=True, default=str
    ).encode()).hexdigest()
    outcome = SourceIntelligencePipeline().process(
        source=source, payload=payload, db=db, tenant_id=tenant_id,
        actor_id=actor_id, project_id=project_id,
        source_event_id=source_event_id or f"{source}_{digest}",
        event_type="diagram_import" if source == "excalidraw" else "manual_submission",
        metadata={"filename": payload.get("filename"), "submitted_by": actor_id},
        visual_context=text if source == "excalidraw" else None,
    )
    return outcome.model_dump()


def extract_upload(filename: str, data: bytes) -> tuple[str, Dict[str, Any]]:
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Uploads are limited to 10 MB.")
    suffix = Path(filename).suffix.lower()
    payload: Dict[str, Any] = {"filename": Path(filename).name,
                              "sha256": hashlib.sha256(data).hexdigest()}
    source = "file_upload"
    try:
        if suffix in {".txt", ".md", ".csv", ".tsv", ".vtt", ".srt"}:
            text = data.decode("utf-8-sig")
        elif suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        elif suffix == ".docx":
            from docx import Document
            document = Document(io.BytesIO(data))
            text = "\n".join([p.text for p in document.paragraphs] + [
                "\t".join(cell.text for cell in row.cells)
                for table in document.tables for row in table.rows
            ])
        elif suffix in {".json", ".excalidraw"}:
            scene = json.loads(data.decode("utf-8-sig"))
            if not isinstance(scene, dict) or not isinstance(scene.get("elements"), list):
                raise ValueError("Expected an Excalidraw scene with an elements array")
            elements = scene["elements"]
            if not all(isinstance(element, dict) for element in elements):
                raise ValueError("Every scene element must be an object")
            text = diagram_text(elements)
            payload.update(elements=elements, app_state=scene.get("appState") or {},
                           name=scene.get("name") or filename)
            source = "excalidraw"
        else:
            raise HTTPException(415, "Supported files: TXT, Markdown, CSV, TSV, VTT, SRT, PDF, DOCX and Excalidraw JSON.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Could not read file: {exc}") from exc
    payload["text"] = text.strip()
    if not payload["text"]:
        raise HTTPException(400, "No readable text found. Scanned PDFs and unlabeled drawings need text labels.")
    return source, payload

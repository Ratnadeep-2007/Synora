"""Durable original files and retryable derived text, scoped to project sources."""

import base64
import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from app.models.memory_engine import SourceArtifact
from app.services.memory_jobs import enqueue_job

MAX_BYTES = 10 * 1024 * 1024


class SourceArtifactService:
    def capture(self, payload, evidence, tenant_id, db, metadata=None):
        encoded = next((payload[key] for key in ("original_base64", "audio_base64", "image_base64") if payload.get(key)), None)
        if not encoded:
            artifact_id = payload.get("artifact_id")
            artifact = db.get(SourceArtifact, artifact_id) if artifact_id else None
            if artifact and artifact.tenant_id == tenant_id and artifact.project_id == evidence.project_id:
                artifact.evidence_id = evidence.id
                return artifact
            return None
        encoded = str(encoded).split(",", 1)[-1]
        if len(encoded) > (MAX_BYTES * 4 // 3 + 16):
            raise ValueError("Original media exceeds the 10 MB limit")
        data = base64.b64decode(encoded, validate=True)
        if not data or len(data) > MAX_BYTES:
            raise ValueError("Invalid or oversized original media")
        sha = hashlib.sha256(data).hexdigest()
        identity = f"{tenant_id}:{evidence.source_event_id}:{sha}"
        artifact_id = "art_" + hashlib.sha256(identity.encode()).hexdigest()[:40]
        existing = db.get(SourceArtifact, artifact_id)
        if existing:
            return existing
        filename = Path(payload.get("filename") or "attachment").name[:255]
        mime = payload.get("mime_type") or payload.get("mimetype") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        multimodal = (metadata or {}).get("multimodal") or {}
        extraction = payload.get("vision_analysis") or multimodal.get("vision_analysis") or multimodal.get("audio_transcription") or {}
        extraction = {**extraction, "selected_project_id": payload.get("selected_project_id")}
        failed = extraction.get("processed") is False
        artifact = SourceArtifact(id=artifact_id, tenant_id=tenant_id, project_id=evidence.project_id,
            evidence_id=evidence.id, source=evidence.source, filename=filename, mime_type=mime,
            sha256=sha, data=data, status="failed" if failed else "complete",
            error=extraction.get("error") if failed else None,
            extraction_json=json.dumps(extraction or {"text": payload.get("text", ""), "provider": "document_parser"}))
        db.add(artifact)
        db.flush()
        if failed:
            enqueue_job(db, "media_transform", {"artifact_id": artifact.id}, artifact.project_id, tenant_id, key=artifact.id)
        return artifact

    def describe(self, artifact):
        extraction = json.loads(artifact.extraction_json or "{}")
        return {"id": artifact.id, "filename": artifact.filename, "mime_type": artifact.mime_type,
                "status": artifact.status, "error": artifact.error, "sha256": artifact.sha256,
                "provider": extraction.get("provider"), "model": extraction.get("model"),
                "text": extraction.get("text") or extraction.get("ocr_text") or extraction.get("summary") or "",
                "segments": extraction.get("segments", []), "updated_at": artifact.updated_at.isoformat()}

    def retry(self, artifact, db):
        if artifact.status == "complete":
            return None
        artifact.status = "received"
        artifact.error = None
        job = enqueue_job(db, "media_transform", {"artifact_id": artifact.id}, artifact.project_id,
                          artifact.tenant_id, key=artifact.id, requeue=True)
        db.commit()
        return job

    def reprocess(self, artifact_id, db):
        artifact = db.get(SourceArtifact, artifact_id)
        if not artifact:
            return {"skipped": "source_deleted"}
        if artifact.status == "complete":
            return {"skipped": "already_processed"}
        from app.services.multimodal_service import MultimodalService
        artifact.status = "processing"
        db.commit()
        media = MultimodalService()
        if artifact.mime_type.startswith("audio/") or artifact.source == "manual_audio":
            result = media.transcribe_audio(artifact.data, artifact.filename)
            text = str(result.get("text") or "").strip()
        elif artifact.mime_type.startswith("image/"):
            result = media.extract_from_image(artifact.data, artifact.mime_type)
            text = "\n".join(str(result.get(key) or "") for key in ("ocr_text", "summary")).strip()
        else:
            from app.services.direct_input_service import extract_upload
            _, payload = extract_upload(artifact.filename, artifact.data)
            text = payload["text"]
            result = {"processed": True, "text": text, "provider": "document_parser"}
        artifact.updated_at = datetime.now(timezone.utc)
        previous_extraction = json.loads(artifact.extraction_json or "{}")
        artifact.extraction_json = json.dumps({**previous_extraction, **result})
        if not result.get("processed") or not text:
            artifact.status = "failed"
            artifact.error = result.get("error") or "No source text could be extracted"
            db.commit()
            raise RuntimeError(artifact.error)
        artifact.status = "complete"
        artifact.error = None
        original_evidence_id = artifact.evidence_id
        if artifact.source != "manual_audio":
            from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
            from app.services.source_intelligence_pipeline import SourceIntelligencePipeline
            outcome = SourceIntelligencePipeline().process(
                source=artifact.source, payload={"text": text, "filename": artifact.filename, "artifact_id": artifact.id},
                db=db, tenant_id=artifact.tenant_id,
                project_id=previous_extraction.get("selected_project_id") or (None if artifact.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID else artifact.project_id),
                source_event_id=f"derived:{artifact.id}:{hashlib.sha256(text.encode()).hexdigest()[:16]}",
                event_type="media_reprocessed", metadata={"artifact_id": artifact.id, "derived_from_original": True},
            )
            if outcome.evidence_id:
                from app.models.context_resolution import UnknownContextItem
                for item in db.query(UnknownContextItem).filter_by(evidence_id=original_evidence_id, status="pending").all():
                    item.status = "dismissed"
                    item.payload_json = json.dumps({**json.loads(item.payload_json), "reprocessed_as_evidence_id": outcome.evidence_id})
                artifact.evidence_id = outcome.evidence_id
                artifact.project_id = outcome.project_id or SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
        db.commit()
        return {"artifact_id": artifact.id, "status": artifact.status}

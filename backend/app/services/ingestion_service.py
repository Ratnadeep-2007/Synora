from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.evidence import Evidence
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.source_event import SourceEvent
from app.schemas.source_event import SourceEventCreate

logger = logging.getLogger(__name__)


class IngestionError(SynesisException):
    """Raised when an error occurs during event ingestion or validation."""
    pass


class IngestionService:
    """
    Core Ingestion Service responsible for:
    1. Validating and persisting provider-independent SourceEvent records
    2. Enforcing ingestion idempotency
    3. Normalizing Google Meet transcript entries into SourceEvents and Evidence records
    4. Separating raw source data from interpreted knowledge
    """

    def ingest_event(self, event_in: SourceEventCreate, db: Session, commit: bool = True) -> SourceEvent:
        """
        Idempotently ingests a single normalized source event.
        If an event with the same (project_id, source, source_event_id) exists,
        returns the existing record without duplicate insertion.
        """
        if not event_in.source_event_id or not event_in.source:
            raise IngestionError("SourceEvent must have non-empty source and source_event_id.")

        existing = (
            db.query(SourceEvent)
            .filter(
                SourceEvent.project_id == event_in.project_id,
                SourceEvent.source == event_in.source,
                SourceEvent.source_event_id == event_in.source_event_id,
            )
            .first()
        )

        if existing:
            return existing

        payload_str = json.dumps(event_in.payload) if isinstance(event_in.payload, dict) else str(event_in.payload)

        source_event = SourceEvent(
            tenant_id=event_in.tenant_id,
            project_id=event_in.project_id,
            source=event_in.source,
            source_event_id=event_in.source_event_id,
            event_type=event_in.event_type,
            actor_id=event_in.actor_id,
            occurred_at=event_in.occurred_at or datetime.now(timezone.utc),
            payload_json=payload_str,
            status=event_in.status or "received",
        )
        db.add(source_event)
        if commit:
            db.commit()
            db.refresh(source_event)
        return source_event

    def create_evidence_from_event(
        self,
        event: SourceEvent,
        db: Session,
        meeting_id: Optional[str] = None,
        transcript_id: Optional[str] = None,
        transcript_entry_id: Optional[str] = None,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        commit: bool = True,
    ) -> Evidence:
        """
        Creates an Evidence record linking back to a SourceEvent.
        Guarantees provenance: 'Why does Synesis believe this?'
        """
        # Deduplication check
        existing = (
            db.query(Evidence)
            .filter(
                Evidence.project_id == event.project_id,
                Evidence.source_event_id == event.event_id,
            )
            .first()
        )
        if existing:
            return existing

        raw_content = content
        if not raw_content:
            try:
                payload = json.loads(event.payload_json)
                raw_content = payload.get("text", payload.get("content", ""))
            except Exception:
                raw_content = event.payload_json

        if not raw_content:
            raise IngestionError(f"Cannot create Evidence from event {event.event_id}: missing content.")

        evidence = Evidence(
            project_id=event.project_id,
            source=event.source,
            source_event_id=event.event_id,
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            transcript_entry_id=transcript_entry_id,
            actor_id=event.actor_id,
            occurred_at=event.occurred_at,
            content=raw_content,
            metadata_json=json.dumps(metadata or {}),
        )
        db.add(evidence)
        event.status = "processed"
        if commit:
            db.commit()
            db.refresh(evidence)
        return evidence

    def ingest_events(self, events: List[SourceEventCreate], db: Session) -> List[SourceEvent]:
        """
        Ingests a batch of normalized source events idempotently using a single batch commit.
        """
        results: List[SourceEvent] = []
        for ev in events:
            results.append(self.ingest_event(ev, db, commit=False))
        db.commit()
        for r in results:
            db.refresh(r)
        return results

    def normalize_events_to_evidence(
        self,
        events: List[SourceEvent],
        db: Session,
    ) -> List[Evidence]:
        """
        Transforms arbitrary SourceEvent records into Evidence records using batch commit.
        Provider-independent: works identically for Google Meet, Slack, or any external source.
        """
        evidence_list: List[Evidence] = []
        for ev in events:
            raw_content = ""
            payload_dict = {}
            try:
                payload_dict = json.loads(ev.payload_json) if isinstance(ev.payload_json, str) else ev.payload_json
                if isinstance(payload_dict, dict):
                    raw_content = payload_dict.get("text") or payload_dict.get("content") or ""
                else:
                    raw_content = str(payload_dict)
            except Exception:
                raw_content = str(ev.payload_json)

            if not raw_content or not str(raw_content).strip():
                continue

            evidence = self.create_evidence_from_event(
                event=ev,
                db=db,
                content=str(raw_content),
                metadata=payload_dict if isinstance(payload_dict, dict) else {},
                commit=False,
            )
            evidence_list.append(evidence)
        db.commit()
        for e in evidence_list:
            db.refresh(e)
        return evidence_list

    def normalize_meeting_to_evidence(
        self,
        meeting_id: str,
        project_id: str,
        db: Session,
    ) -> List[Evidence]:
        """
        Normalizes all TranscriptEntries for a given Meeting into SourceEvents and Evidence.
        Idempotent: Safe to call repeatedly without generating duplicate events or evidence.
        """
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            raise IngestionError(f"Meeting '{meeting_id}' not found.")

        # Load transcripts and entries
        transcripts = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).all()
        created_evidence_list: List[Evidence] = []

        for transcript in transcripts:
            entries = (
                db.query(TranscriptEntry)
                .filter(TranscriptEntry.transcript_id == transcript.id)
                .order_by(TranscriptEntry.start_time.asc())
                .all()
            )

            for entry in entries:
                if not entry.text or not entry.text.strip():
                    continue

                speaker_name = entry.participant.display_name if entry.participant else None

                # 1. Ingest normalized SourceEvent
                event_in = SourceEventCreate(
                    tenant_id="tenant_default",
                    project_id=project_id,
                    source="google_meet",
                    source_event_id=entry.provider_entry_id,
                    event_type="transcript_entry",
                    actor_id=speaker_name or "Unknown Speaker",
                    occurred_at=entry.start_time,
                    payload={
                        "text": entry.text,
                        "language_code": entry.language_code,
                        "start_time": entry.start_time.isoformat() if entry.start_time else None,
                        "end_time": entry.end_time.isoformat() if entry.end_time else None,
                        "speaker_name": speaker_name,
                        "meeting_id": meeting.id,
                        "conference_id": meeting.provider_conference_id,
                    },
                    status="received",
                )
                source_event = self.ingest_event(event_in, db)

                # 2. Create Evidence record
                meta = {
                    "language_code": entry.language_code,
                    "speaker_display_name": speaker_name,
                    "meeting_title": meeting.title,
                    "conference_id": meeting.provider_conference_id,
                }
                evidence = self.create_evidence_from_event(
                    event=source_event,
                    db=db,
                    meeting_id=meeting.id,
                    transcript_id=transcript.id,
                    transcript_entry_id=entry.id,
                    content=entry.text,
                    metadata=meta,
                )
                created_evidence_list.append(evidence)

        logger.info(f"Meeting '{meeting_id}' normalized: {len(created_evidence_list)} evidence records ready.")
        return created_evidence_list

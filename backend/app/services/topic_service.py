"""Topic boundaries and expiring continuity, without a model call per turn."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from app.models.memory_engine import TopicWindow
from app.services.memory_retrieval import words

SWITCH = re.compile(r"\b(next project|another project|switch(?:ing)? to|moving on|now (?:about|for)|agla project|dusra project|ab .+ project)\b", re.I)


class TopicService:
    def split_entries(self, entries, window_size=12, gap_seconds=45):
        windows = []
        current = []
        previous = None
        for entry in entries:
            gap = False
            start = getattr(entry, "start_time", None)
            end = getattr(previous, "end_time", None) or getattr(previous, "start_time", None)
            if start is not None and end is not None:
                delta = start - end
                gap = (delta.total_seconds() if hasattr(delta, "total_seconds") else float(delta)) >= gap_seconds
            if current and (len(current) >= window_size or gap or SWITCH.search(entry.text or "")):
                windows.append(current)
                current = []
            current.append(entry)
            previous = entry
        if current:
            windows.append(current)
        return windows

    def split_text(self, text):
        # Exact source offsets survive segmentation. Switches are structural
        # hints; they do not authorize a destination or create a project.
        starts = [0]
        for match in re.finditer(r"(?m)^.*$", text):
            if match.start() and SWITCH.search(match.group()):
                starts.append(match.start())
        starts.append(len(text))
        return [{"text": text[start:end], "start": start, "end": end}
                for start, end in zip(starts, starts[1:]) if text[start:end].strip()]

    def remember(self, source, payload, evidence, tenant_id, db):
        stream = payload.get("group_jid") or payload.get("channel_id") or payload.get("meeting_id") or evidence.meeting_id
        if not stream:
            return
        stream_id = f"{source}:{stream}"
        key = "topic_" + hashlib.sha256(f"{tenant_id}:{stream_id}".encode()).hexdigest()[:40]
        row = db.get(TopicWindow, key)
        if not row:
            row = TopicWindow(id=key, tenant_id=tenant_id, stream_id=stream_id)
            db.add(row)
        timestamp = datetime.now(timezone.utc)
        previous_time = row.updated_at
        if previous_time and previous_time.tzinfo is None:
            previous_time = previous_time.replace(tzinfo=timezone.utc)
        reset = not previous_time or previous_time < timestamp - timedelta(minutes=45) or SWITCH.search(evidence.content or "")
        reset = reset or bool(row.project_id and row.project_id != evidence.project_id)
        ids = [] if reset else json.loads(row.evidence_ids_json or "[]")
        row.evidence_ids_json = json.dumps(list(dict.fromkeys([*ids, evidence.id]))[-6:])
        row.topic_terms_json = json.dumps(list(dict.fromkeys(words(evidence.content)))[:20])
        row.project_id = evidence.project_id
        row.updated_at = timestamp

    def continuity(self, source, stream, current_text, tenant_id, db):
        if SWITCH.search(current_text or ""):
            return ""
        key = "topic_" + hashlib.sha256(f"{tenant_id}:{source}:{stream}".encode()).hexdigest()[:40]
        row = db.get(TopicWindow, key)
        if not row:
            return ""
        updated = row.updated_at.replace(tzinfo=timezone.utc) if row.updated_at.tzinfo is None else row.updated_at
        if updated < datetime.now(timezone.utc) - timedelta(minutes=45):
            return ""
        from app.models.evidence import Evidence
        records = {item.id: item for item in db.query(Evidence).filter(
            Evidence.id.in_(json.loads(row.evidence_ids_json)), Evidence.project_id == row.project_id,
        ).all()}
        return "\n".join(f"- {records[eid].content[:240]}" for eid in json.loads(row.evidence_ids_json) if eid in records)[:1500]

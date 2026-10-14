"""Validate canvas citations and preserve unchanged managed elements."""

import copy
import json
import hashlib
from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.models.source_event import SourceEvent
from app.services.memory_lifecycle import normalized


def enrich_scene(scene, project_id, tenant_id, db):
    tenants = ["default_tenant", "tenant_default"] if tenant_id in {"default_tenant", "tenant_default"} else [tenant_id]
    source_rows = db.query(Evidence).join(SourceEvent, Evidence.source_event_id == SourceEvent.event_id).filter(
        Evidence.project_id == project_id, SourceEvent.tenant_id.in_(tenants),
    ).all()
    sources = {row.id: row for row in source_rows}
    aliases = {"ev_text_" + hashlib.sha1((row.content or "").split("\n[EN]")[0].strip().encode()).hexdigest()[:12]: row.id for row in source_rows}
    claims = db.query(CandidateKnowledge).filter(CandidateKnowledge.project_id == project_id,
        CandidateKnowledge.status.in_(["approved", "conflict", "candidate", "proposed"])).all()
    result = copy.deepcopy(scene)
    texts = {item.get("containerId"): item.get("text", "") for item in result if item.get("type") == "text"}
    for item in result:
        custom = item.setdefault("customData", {})
        visual = custom.get("visual")
        if not isinstance(visual, dict):
            continue
        cited = list(dict.fromkeys(aliases.get(eid, eid) for eid in visual.get("evidence_ids", []) if aliases.get(eid, eid) in sources))
        if cited != visual.get("evidence_ids", []):
            visual["invalid_citation_count"] = len(visual.get("evidence_ids", [])) - len(cited)
        visual["evidence_ids"] = cited
        text = normalized(item.get("text") or texts.get(item.get("id")) or "")
        matches = [claim for claim in claims if text and normalized(claim.title) == text and
                   set(json.loads(claim.evidence_ids_json)) & set(cited)]
        visual["claim_ids"] = [claim.id for claim in matches]
        visual["project_id"] = project_id
        visual["record_status"] = "conflict" if any(claim.status == "conflict" for claim in matches) else "approved" if any(
            claim.status == "approved" for claim in matches
        ) else "source" if cited and visual.get("support_type") == "explicit" else "inferred"
        from app.services.memory_retrieval import words
        statement_terms = set(words(text))
        source_terms = {term for eid in cited for term in words(sources[eid].content)}
        if not cited or (statement_terms and not matches and len(statement_terms & source_terms) / len(statement_terms) < 0.7):
            visual["support_type"] = "inferred"
            visual["record_status"] = "inferred"
        if visual["record_status"] == "conflict" and item.get("type") != "text":
            item["strokeColor"] = "#b45309"
            item["strokeStyle"] = "dashed"
    return result


def signature(item):
    return json.dumps({key: value for key, value in item.items() if key not in {
        "x", "y", "version", "versionNonce", "updated", "seed"
    }}, sort_keys=True, default=str)


def overlap(left, right):
    return left.get("x", 0) < right.get("x", 0) + right.get("width", 0) and right.get("x", 0) < left.get("x", 0) + left.get("width", 0) and \
        left.get("y", 0) < right.get("y", 0) + right.get("height", 0) and right.get("y", 0) < left.get("y", 0) + left.get("height", 0)


def reconcile_managed(old_scene, new_scene):
    old = {item["id"]: item for item in old_scene if item.get("id")}
    shapes = {"rectangle", "ellipse", "diamond"}
    changed = [item for item in new_scene if item.get("type") in shapes and (
        item.get("id") not in old or signature(item) != signature(old[item["id"]])
    )]
    preserved = set()
    for item in new_scene:
        previous = old.get(item.get("id"))
        if previous and signature(previous) == signature(item) and not any(overlap(previous, shape) for shape in changed):
            preserved.add(item["id"])
    # A text stays with its container. Avoid retaining a label's old position
    # when its containing shape actually changed or could not be preserved.
    result = []
    for item in new_scene:
        container = item.get("containerId")
        keep = item.get("id") in preserved and (not container or container in preserved)
        result.append(copy.deepcopy(old[item["id"]] if keep else item))
    return result

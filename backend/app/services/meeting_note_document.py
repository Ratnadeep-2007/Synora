"""Meeting-only, evidence-linked reading structure shared by AI and fallback.

This module formats derived notes. It never writes candidates, evidence or memory.
"""
import hashlib
import re
from typing import Any, Dict, List, Optional

from app.schemas.visual_plan import NoteBlock, NoteSection, NotesDocument, VisualPlan
from app.services.translation_service import needs_translation


MEETING_NOTES_VERSION = "meeting-notes-v1"
MEETING_NOTES_PROMPT = """DEFAULT MEETING READING ORDER:
Summary (one or two sentences), Decisions, Next steps, Topics discussed (topic
subheadings), Discussed and rejected, Open questions, Details and diagrams.
The application adds meeting metadata and a source appendix once after merging.
Use one claim per block, evidence_ids on EVERY claim, and stable semantic IDs.
Use callout for summary, bullets for decisions/topics/questions, checklist for
next steps, paragraph for details. Prefer bullets of about 140 characters, but
NEVER remove a condition, negation, uncertainty, number or scope to shorten them.
Preserve 'without manager approval' rather than claiming an unconditional ban.
No Speaker: prefixes or raw quotes in bullets; quotes belong in Details only.
Attribute an agreement or task only when its source explicitly supports it.
Speaker identity is not task ownership. Omit unknown owner/deadline or label
them unassigned/not stated. Do not turn proposals into agreed decisions.
Later corrections supersede earlier claims; rejected proposals belong ONLY in
Discussed and rejected. Keep project identity in each claim/topic; independent
projects must never share an invented integration. Proposed memory is not approved
memory. Do not fill empty sections with invented content. Preserve implementation
detail below the overview and draw useful evidence-backed relationships freely.
"""

ORDER = ["Summary", "Decisions", "Next steps", "Topics discussed",
         "Discussed and rejected", "Open questions", "Details"]
REJECTED = re.compile(r"\b(reject(?:ed|ing)?|ruled out|not proceeding|will not adopt|decided against|not approved)\b", re.I)
CONDITIONAL = re.compile(r"\b(without|unless|only if|provided that|subject to|pending approval)\b", re.I)


def _category(title: str) -> str:
    value = title.lower()
    if any(s in value for s in ("reject", "ruled out", "not proceeding")):
        return "Discussed and rejected"
    if any(s in value for s in ("summary", "overview", "outcome")):
        return "Summary"
    if "decision" in value or "agreed" in value:
        return "Decisions"
    if any(s in value for s in ("next step", "action", "task", "todo")):
        return "Next steps"
    if any(s in value for s in ("question", "unresolved", "open issue")):
        return "Open questions"
    if any(s in value for s in ("detail", "appendix", "quote")):
        return "Details"
    return "Topics discussed"


def assemble_meeting_notes(
    state: Dict[str, Any], snippets: List[Dict[str, Any]],
    plan: Optional[VisualPlan] = None,
) -> VisualPlan:
    """Consolidate batches once; missing extraction degrades to source excerpts."""
    sources = {str(s.get("id")): s for s in snippets if s.get("id")
               and s.get("source") != "translation_pending"}
    aliases = state.get("evidence_aliases") or {}
    grouped: Dict[str, List[NoteBlock]] = {key: [] for key in ORDER}
    seen = set()

    def add(category: str, text: str, ids: List[str], kind: str = "bullets",
            topic: str = "", tone: Optional[str] = None) -> None:
        refs = list(dict.fromkeys(str(aliases.get(str(i), i)) for i in ids))
        refs = [i for i in refs if i in sources]
        text = re.sub(r"^(?:Unknown Speaker|SPEAKER_\d+|Speaker):\s*", "", text.strip(), flags=re.I)
        if not refs or not text or needs_translation(text) or "translation pending" in text.lower():
            return
        source_text = " ".join(str(sources[i].get("text") or sources[i].get("content") or "") for i in refs)
        # Conservative repair of the observed lost-condition failure. Keep the
        # complete cited source instead of guessing how to reconstruct a rule.
        if category != "Details" and CONDITIONAL.search(source_text) and not CONDITIONAL.search(text):
            text = source_text
        if REJECTED.search(text):
            category = "Discussed and rejected"
            kind = "bullets"
        elif category == "Decisions" and re.search(r"\b(proposed|proposal|tentative|considering|might|could)\b", text, re.I):
            category = "Topics discussed"
        key = (category, topic.casefold(), re.sub(r"\W+", " ", text.lower()).strip())
        if key in seen:
            existing = next((b for b in grouped[category] if b.id == seen_map[key]), None)
            if existing:
                existing.evidence_ids = list(dict.fromkeys(existing.evidence_ids + refs))
            return
        seen.add(key)
        block_id = "meeting_claim_" + hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:16]
        seen_map[key] = block_id
        stamp = sources[refs[0]].get("timestamp")
        if stamp and category in ("Topics discussed", "Details", "Discussed and rejected") and not re.search(r"\(\d+:\d{2}\)$", text):
            text = f"{text} ({stamp})"
        if topic and category not in ("Topics discussed", "Details", "Summary") and topic.lower() not in ("decisions", "next steps", "open questions", "discussed and rejected"):
            text = f"{topic} — {text}"
        grouped[category].append(NoteBlock(
            id=block_id, block_type=kind,
            text=text if kind in ("paragraph", "callout", "quote") else "",
            items=[text] if kind in ("bullets", "checklist") else [],
            title=topic or None, evidence_ids=refs, tone=tone or {"Decisions": "success", "Next steps": "warning", "Open questions": "info"}.get(category),
        ))

    seen_map: Dict[Any, str] = {}
    if plan:
        sections = list(plan.notes_document.sections if plan.notes_document else []) + list(plan.notes_sections or [])
        visited = set()
        for section in sections:
            if section.id in visited:
                continue
            visited.add(section.id)
            category = _category(section.title)
            if section.id.endswith("meeting_header") or "transcript appendix" in section.title.lower():
                continue
            for block in section.blocks:
                if block.support_type == "status":
                    continue
                for text in block.items or ([block.text] if block.text else []):
                    add(category, text, block.evidence_ids, "checklist" if category == "Next steps" else
                        "callout" if category == "Summary" else "paragraph" if category == "Details" else "bullets", section.title)

    # Use extracted intelligence only when no AI content covers that category.
    # The full transcript still feeds AI and the appendix, regardless of routing.
    intelligence = state.get("meeting_intelligence") or {}
    for field, category in (("decisions", "Decisions"), ("action_items", "Next steps"),
                            ("requirements", "Topics discussed"), ("open_questions", "Open questions")):
        if grouped[category]:
            continue
        for item in intelligence.get(field) or []:
            text = str(item.get("content") or item.get("title") or "")
            target_category = category
            # Candidate classification alone is not proof that the meeting
            # agreed. With no explicit agreement wording, retain it as a topic.
            if category == "Decisions" and not REJECTED.search(text):
                refs = [str(aliases.get(str(i), i)) for i in item.get("evidence_ids") or []]
                support = " ".join(str(sources.get(i, {}).get("text") or sources.get(i, {}).get("content") or "") for i in refs)
                if not re.search(r"\b(agreed|decided|approved|confirmed|will use|we will keep|we are keeping)\b", support, re.I):
                    target_category = "Topics discussed"
            # Actor hints are authors, not an explicit assignment of ownership.
            if category == "Next steps":
                text = f"{text}" + (f" — Due: {item['due_hint']}" if item.get("due_hint") else "")
            project = str((state.get("project_names") or {}).get(item.get("project_id")) or item.get("project_id") or "")
            add(target_category, text, item.get("evidence_ids") or [], "checklist" if category == "Next steps" else "bullets", project)

    if not any(grouped.values()):
        for source_id, source in sources.items():
            add("Details", str(source.get("text") or source.get("content") or ""), [source_id], "paragraph")

    # Each batch may propose a summary. Keep one brief overview, with other
    # supported summaries retained as detail rather than repeated at the top.
    if len(grouped["Summary"]) > 1:
        grouped["Details"].extend(grouped["Summary"][1:])
        grouped["Summary"] = grouped["Summary"][:1]

    sections = [NoteSection(id="meeting_header", title="Meeting", order=0, blocks=[NoteBlock(
        id="meeting_metadata", block_type="key_value", rows=[
            ["Title", str(state.get("title") or "Meeting notes")],
            ["Date / time", str(state.get("meeting_date") or "Not recorded")],
            ["Speakers", ", ".join(state.get("participants") or []) or "Not identified"],
            ["Observed duration", str(state.get("meeting_duration") or "Not recorded")],
        ],
    )])]
    for index, category in enumerate(ORDER, 1):
        blocks = grouped[category]
        if category in ("Topics discussed", "Details") and blocks:
            topic_groups: Dict[str, List[NoteBlock]] = {}
            for block in blocks:
                topic_groups.setdefault(block.title or "Discussion", []).append(block)
            blocks = []
            for topic_index, (topic, topic_blocks) in enumerate(topic_groups.items()):
                if topic.lower() not in ("notes", "topics discussed", "details", "discussion"):
                    blocks.append(NoteBlock(id=f"meeting_topic_{index}_{topic_index}", block_type="heading",
                        text=topic, evidence_ids=list(dict.fromkeys(e for b in topic_blocks for e in b.evidence_ids))))
                blocks.extend(topic_blocks)
        if not blocks and category in ("Summary", "Decisions", "Next steps"):
            message = {"Summary": "Structured summary unavailable; review the discussion details.",
                       "Decisions": "No agreed decisions identified.", "Next steps": "No next steps identified."}[category]
            blocks = [NoteBlock(id=f"meeting_empty_{index}", block_type="paragraph", text=message, support_type="status")]
        if blocks:
            sections.append(NoteSection(id=f"meeting_section_{index}", title=category, order=index, blocks=blocks))
    appendix = []
    # A bounded index, not another full transcript dump. Original transcript is
    # retained in its dedicated UI panel, accessible through these source IDs.
    for source_id, source in list(sources.items())[:12]:
        text = str(source.get("text") or source.get("content") or "")
        if needs_translation(text):
            continue
        excerpt = text if len(text) <= 200 else text[:197] + "..."
        appendix.append(NoteBlock(id=f"meeting_source_{source_id}", block_type="paragraph",
            text=f"({source.get('timestamp') or '--:--'}) {excerpt}", evidence_ids=[source_id], tone="muted"))
    if appendix:
        sections.append(NoteSection(id="meeting_transcript_appendix", title="Transcript appendix · source excerpts", order=9, blocks=appendix))
    result = plan.model_copy(deep=True) if plan else VisualPlan(canvas_strategy="text", model="deterministic")
    def grounded_refs(value):
        return list(dict.fromkeys(str(aliases.get(str(i), i)) for i in value
                                  if str(aliases.get(str(i), i)) in sources))
    for node in result.nodes:
        node.evidence_ids = grounded_refs(node.evidence_ids)
    result.nodes = [node for node in result.nodes if node.evidence_ids]
    node_ids = {node.id for node in result.nodes}
    for edge in result.relationships:
        edge.evidence_ids = grounded_refs(edge.evidence_ids)
    result.relationships = [edge for edge in result.relationships if edge.evidence_ids
                            and edge.source in node_ids and edge.target in node_ids]
    for visual in result.visualizations:
        visual.evidence_ids = grounded_refs(visual.evidence_ids)
        for primitive in visual.elements:
            primitive.evidence_ids = grounded_refs(primitive.evidence_ids)
        visual.elements = [p for p in visual.elements if p.evidence_ids]
        surviving = {p.id for p in visual.elements}
        visual.elements = [p for p in visual.elements if (not p.source or p.source in surviving)
                           and (not p.target or p.target in surviving)]
    result.visualizations = [v for v in result.visualizations if v.evidence_ids or v.elements]
    result.title = str(state.get("title") or "Meeting notes")
    result.notes_sections = []
    result.notes = []
    result.notes_document = NotesDocument(title=result.title,
        subtitle="Meeting notes · memory proposals require separate approval", sections=sections)
    result.prompt_version = MEETING_NOTES_VERSION
    return result

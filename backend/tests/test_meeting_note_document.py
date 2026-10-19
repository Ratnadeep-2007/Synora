"""Regression cases for the meeting reading structure and truthful fallback."""
from app.schemas.visual_plan import NoteBlock, NoteSection, NotesDocument, VisualNode, VisualPlan
from app.services.meeting_note_document import assemble_meeting_notes
from app.services.excalidraw_compiler import ExcalidrawCompiler
from app.services.visual_plan_service import VisualPlanService


def source(eid="turn1", text="We agreed no manual correction without manager approval.", stamp="00:12"):
    return {"id": eid, "text": text, "content": text, "timestamp": stamp, "source": "meeting_transcript"}


def state(**kwargs):
    return {"title": "Harbor", "context_scope": "complete_meeting_discussion", **kwargs}


def block_text(plan, title):
    return " ".join(b.text or " ".join(b.items) for s in plan.notes_document.sections if s.title == title for b in s.blocks)


def test_fallback_uses_intelligence_preserves_condition_and_never_assigns_author():
    data = state(evidence_aliases={"ev1": "turn1"}, meeting_intelligence={
        "decisions": [{"content": "No manual correction.", "evidence_ids": ["ev1"]}],
        "action_items": [{"content": "Build dashboard", "evidence_ids": ["ev1"], "owner_hints": ["Alice"]}],
    })
    plan = VisualPlanService()._deterministic_plan(data, [], evidence_snippets=[source()])
    assert "without manager approval" in block_text(plan, "Decisions")
    assert "Alice" not in block_text(plan, "Next steps")
    assert [s.title for s in plan.notes_document.sections][:4] == ["Meeting", "Summary", "Decisions", "Next steps"]
    assert "Details" not in [s.title for s in plan.notes_document.sections]


def test_rejected_proposal_never_in_decisions_and_uncited_claim_dropped():
    plan = VisualPlan(notes_document=NotesDocument(sections=[NoteSection(id="d", title="Decisions", blocks=[
        NoteBlock(id="a", block_type="bullets", items=["MongoDB migration rejected"], evidence_ids=["turn1"]),
        NoteBlock(id="b", text="Budget approved", evidence_ids=["not_in_this_meeting"]),
    ])]), nodes=[VisualNode(id="bad", label="Invented integration")])
    result = assemble_meeting_notes(state(), [source(text="MongoDB migration rejected")], plan)
    assert "MongoDB" not in block_text(result, "Decisions")
    assert "MongoDB" in block_text(result, "Discussed and rejected")
    assert "Budget approved" not in result.model_dump_json()
    assert not result.nodes


def test_empty_extraction_preserves_source_in_details_and_translation_status_not_a_fact():
    result = assemble_meeting_notes(state(), [source(), {"id": "pending", "content": "English translation pending", "source": "translation_pending"}])
    assert "without manager approval" in block_text(result, "Details")
    assert "No agreed decisions identified" in block_text(result, "Decisions")
    assert "English translation pending" not in result.model_dump_json()


def test_one_overview_deduped_sources_and_topic_timestamp():
    sections = [NoteSection(id=f"s{i}", title="Summary", blocks=[NoteBlock(id=f"b{i}", text=text, evidence_ids=["turn1"])]) for i, text in enumerate(["Track stock", "Track warehouse stock"])]
    sections += [NoteSection(id="topic", title="Harbor scope", blocks=[NoteBlock(id="t", text="Track stock", evidence_ids=["turn1"])])]
    result = assemble_meeting_notes(state(), [source(text="Track warehouse stock")], VisualPlan(notes_sections=sections))
    summary = next(s for s in result.notes_document.sections if s.title == "Summary")
    assert len(summary.blocks) == 1
    assert "00:12" in block_text(result, "Topics discussed")
    assert "Harbor scope" in block_text(result, "Topics discussed")


def test_compiled_blocks_keep_source_and_type_appendix_is_to_right_and_text_grows():
    result = assemble_meeting_notes(state(meeting_intelligence={"action_items": [
        {"content": "Build dashboard", "evidence_ids": ["turn1"]}]}), [source(text="We will build dashboard")])
    elements = ExcalidrawCompiler().compile(result)
    notes = [e for e in elements if e.get("customData", {}).get("visual", {}).get("type") == "note_block"]
    checklist = next(e for e in notes if e["customData"]["visual"]["block_type"] == "checklist")
    assert checklist["customData"]["visual"]["block_items"]
    assert checklist["customData"]["visual"]["evidence_ids"] == ["turn1"]
    appendix = next(e for e in notes if e["customData"]["visual"]["section_id"] == "meeting_transcript_appendix")
    assert appendix["x"] > checklist["x"] + 560
    assert all(e.get("autoResize") is False and e["height"] > 0 for e in elements if e["type"] == "text")


def test_candidate_proposal_cannot_become_agreed_decision():
    result = assemble_meeting_notes(state(meeting_intelligence={"decisions": [{
        "content": "Use MongoDB", "evidence_ids": ["turn1"]}]}), [source(text="We could consider MongoDB.")])
    assert "Use MongoDB" not in block_text(result, "Decisions")
    assert "Use MongoDB" in block_text(result, "Topics discussed")


def test_condition_split_across_turns_repairs_over_summarized_claim():
    snippets = [source("condition", "Without the warehouse manager's approval", "00:36"),
                source("rule", "There will be no manual stock correction", "00:44")]
    plan = VisualPlan(notes_sections=[NoteSection(id="d", title="Decisions", blocks=[
        NoteBlock(id="ban", text="No manual stock correction allowed", evidence_ids=["rule"])])])
    result = assemble_meeting_notes(state(), snippets, plan)
    assert "Without the warehouse manager's approval" in block_text(result, "Decisions")
    block = next(s for s in result.notes_document.sections if s.title == "Decisions").blocks[0]
    assert block.evidence_ids == ["condition", "rule"]


def test_valid_but_unrelated_reference_is_not_grounding_and_unknown_discussion_survives():
    snippets = [source("a", "A frappe agent helps with corrections"),
                source("b", "Nimbus Cold Chain buffers temperature readings offline", "02:30")]
    plan = VisualPlan(notes_sections=[NoteSection(id="r", title="Discussed and rejected", blocks=[
        NoteBlock(id="bad", text="MongoDB migration rejected", evidence_ids=["a"])])])
    result = assemble_meeting_notes(state(), snippets, plan)
    assert "MongoDB" not in result.model_dump_json()
    assert "Nimbus Cold Chain" in block_text(result, "Details")


def test_negated_rejection_is_not_a_rejected_outcome():
    snippets = [source(text="MongoDB was not rejected")]
    plan = VisualPlan(notes_sections=[NoteSection(id="d", title="Topics", blocks=[
        NoteBlock(id="x", text="MongoDB was not rejected", evidence_ids=["turn1"])])])
    result = assemble_meeting_notes(state(), snippets, plan)
    assert "MongoDB" not in block_text(result, "Discussed and rejected")


def test_variable_height_notebook_pages_do_not_overlap():
    sources = [source(str(i), f"Recorded detail {i}: " + "warehouse stock detail " * 50) for i in range(15)]
    plan = assemble_meeting_notes(state(), sources)
    elements = ExcalidrawCompiler().compile(plan)
    pages = [e for e in elements if e.get("customData", {}).get("visual", {}).get("type") == "project_notes_page"]
    for i, left in enumerate(pages):
        for right in pages[i + 1:]:
            assert left["x"] + left["width"] <= right["x"] or right["x"] + right["width"] <= left["x"] or left["y"] + left["height"] <= right["y"] or right["y"] + right["height"] <= left["y"]

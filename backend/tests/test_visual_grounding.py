"""
Regression coverage for the five anti-hallucination fixes.

These tests encode the observed failures:

1. A node or relationship citing no evidence is refused at compile time.
   Previously any node survived, which is how one WhatsApp sentence produced a
   seven-node architecture full of plausible-sounding components nobody had
   mentioned.
2. A critique finding must be able to prevent auto-apply.
3. The deterministic planner must not ship a hardcoded domain template.
4. Visual generation is deferred until a project has enough evidence.
5. Inferred elements are drawn dashed and tagged so a reader can tell them
   apart from what the source actually stated.
"""

import json

import pytest

from app.core.exceptions import SynesisException
from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship
from app.services.excalidraw_compiler import ExcalidrawCompiler


def _node(nid, label, evidence=("ev_1",), support="explicit", node_type="service"):
    return VisualNode(
        id=nid,
        label=label,
        node_type=node_type,
        evidence_ids=list(evidence),
        support_type=support,
    )


# ---------------------------------------------------------------- fix 1


def test_ungrounded_nodes_are_dropped():
    plan = VisualPlan(
        title="T",
        nodes=[
            _node("a", "Grounded", evidence=["ev_1"]),
            _node("ghost", "Invented", evidence=[]),
        ],
        relationships=[VisualRelationship(source="a", target="ghost", evidence_ids=["ev_1"])],
    )
    scene = ExcalidrawCompiler().compile(plan)
    ids = {e["id"] for e in scene}
    assert "node_a" in ids
    assert "node_ghost" not in ids


def test_fully_ungrounded_plan_is_refused():
    plan = VisualPlan(title="T", nodes=[_node("x", "Only invented", evidence=[])])
    with pytest.raises(SynesisException):
        ExcalidrawCompiler().compile(plan)


def test_edge_to_dropped_node_is_removed():
    plan = VisualPlan(
        title="T",
        nodes=[_node("a", "A"), _node("b", "B"), _node("ghost", "G", evidence=[])],
        relationships=[
            VisualRelationship(source="a", target="b", evidence_ids=["ev_1"]),
            VisualRelationship(source="a", target="ghost", evidence_ids=["ev_1"]),
        ],
    )
    scene = ExcalidrawCompiler().compile(plan)
    arrows = [e for e in scene if e["type"] == "arrow"]
    targets = {(e.get("endBinding") or {}).get("elementId") for e in arrows}
    assert "node_ghost" not in targets


# ---------------------------------------------------------------- fix 5


def test_explicit_node_is_solid_and_tagged():
    scene = ExcalidrawCompiler().compile(
        VisualPlan(title="T", nodes=[_node("a", "Stated", support="explicit")])
    )
    rect = next(e for e in scene if e["id"] == "node_a")
    assert rect["strokeStyle"] == "solid"
    assert rect["customData"]["visual"]["support_type"] == "explicit"
    assert rect["customData"]["visual"]["evidence_ids"] == ["ev_1"]


def test_inferred_node_is_dashed_and_tagged():
    scene = ExcalidrawCompiler().compile(
        VisualPlan(title="T", nodes=[_node("a", "Guessed", support="inferred")])
    )
    rect = next(e for e in scene if e["id"] == "node_a")
    assert rect["strokeStyle"] == "dashed"
    assert rect["customData"]["visual"]["support_type"] == "inferred"


def test_inferred_relationship_is_dashed_and_carries_evidence():
    plan = VisualPlan(
        title="T",
        nodes=[_node("a", "A"), _node("b", "B")],
        relationships=[
            VisualRelationship(source="a", target="b", evidence_ids=["ev_9"], support_type="inferred")
        ],
    )
    scene = ExcalidrawCompiler().compile(plan)
    arrow = next(e for e in scene if e["type"] == "arrow")
    assert arrow["strokeStyle"] == "dashed"
    assert arrow["customData"]["visual"]["evidence_ids"] == ["ev_9"]


def test_annotation_inherits_node_provenance():
    """Annotation captions are factual claims; they must be traceable too.

    Previously an annotation was the only text on the canvas with no source,
    which is where invented detail such as "PostgreSQL ledger" landed.
    """
    node = _node("a", "Orders", support="explicit")
    node.annotations = ["PostgreSQL ledger"]
    scene = ExcalidrawCompiler().compile(VisualPlan(title="T", nodes=[node]))
    annotation = next(e for e in scene if e["id"] == "annotation_a_0")
    visual = annotation["customData"]["visual"]
    assert visual["type"] == "node_annotation"
    assert visual["semantic_id"] == "a"
    assert visual["evidence_ids"] == ["ev_1"]
    assert visual["support_type"] == "explicit"


def _lanes(scene):
    return {
        e["customData"]["visual"]["group"]: e
        for e in scene
        if (e.get("customData") or {}).get("visual", {}).get("type") == "architecture_group"
    }


def test_group_lane_reports_aggregated_provenance():
    plan = VisualPlan(
        title="T",
        nodes=[
            _node("a", "A", evidence=("ev_1",), support="explicit"),
            _node("b", "B", evidence=("ev_2",), support="inferred"),
            _node("c", "C", evidence=("ev_3",), support="explicit"),
        ],
    )
    plan.nodes[0].group = "core"
    plan.nodes[1].group = "core"
    plan.nodes[2].group = "data"
    lanes = _lanes(ExcalidrawCompiler().compile(plan))

    assert lanes["core"]["customData"]["visual"]["evidence_ids"] == ["ev_1", "ev_2"]
    # One member is inferred, so the lane must not read as fully stated.
    assert lanes["core"]["customData"]["visual"]["support_type"] == "inferred"
    assert lanes["core"]["strokeStyle"] == "dashed"

    assert lanes["data"]["customData"]["visual"]["support_type"] == "explicit"
    assert lanes["data"]["strokeStyle"] == "solid"


def test_group_lane_solid_when_every_member_is_explicit():
    plan = VisualPlan(
        title="T",
        nodes=[
            _node("a", "A", evidence=("ev_1",), support="explicit"),
            _node("b", "B", evidence=("ev_2",), support="explicit"),
        ],
    )
    for n in plan.nodes:
        n.group = "core"
    plan.nodes[0].group = "core"
    plan.nodes[1].group = "data"
    scene = ExcalidrawCompiler().compile(plan)
    for lane in _lanes(scene).values():
        assert lane["customData"]["visual"]["support_type"] == "explicit"
        assert lane["strokeStyle"] == "solid"


def test_sticky_note_carries_evidence_provenance():
    plan = VisualPlan(
        title="T",
        nodes=[_node("a", "A")],
        notes=[
            {
                "text": "Claims must return a denial reason.",
                "kind": "requirement",
                "order": 0,
                "evidence_ids": ["ev_42"],
            }
        ],
    )
    scene = ExcalidrawCompiler().compile(plan)
    card = next(
        e for e in scene
        if (e.get("customData") or {}).get("visual", {}).get("type") == "architectural_note"
    )
    visual = card["customData"]["visual"]
    assert visual["kind"] == "requirement"
    assert visual["evidence_ids"] == ["ev_42"]
    assert visual["support_type"] == "explicit"


def test_sticky_note_without_evidence_is_marked_inferred():
    plan = VisualPlan(title="T", nodes=[_node("a", "A")], notes=["A bare string note"])
    scene = ExcalidrawCompiler().compile(plan)
    card = next(
        e for e in scene
        if (e.get("customData") or {}).get("visual", {}).get("type") == "architectural_note"
    )
    assert card["customData"]["visual"]["evidence_ids"] == []
    assert card["customData"]["visual"]["support_type"] == "inferred"


# ---------------------------------------------------------------- fix 2


class _AlwaysFailsCritique:
    """Stands in for a critique that rejects the plan."""

    def critique(self, plan, elements):
        from app.services.visual_critique_service import VisualCritique

        return VisualCritique(
            ok=False,
            issues=["plan drops 3 preserved nodes", "node overlap detected"],
            repairs=[],
            repairs_applied=[],
        )


def test_text_diagram_is_held_as_proposal_when_critique_fails(db_session, monkeypatch):
    """auto_apply=True must not bypass the critique.

    The text-to-diagram path wrote straight to the canvas with no critique at
    all, so a plan the critic would have rejected was committed anyway.
    """
    import app.services.visual_critique_service as critique_mod
    from app.core.config import settings
    from app.models.project import Project
    from app.services.excalidraw_service import ExcalidrawService

    # This test asserts grounded-mode behavior. The local .env may select
    # free design mode, so pin it: the free-mode counterpart lives in
    # test_meta_provider.py.
    monkeypatch.setattr(settings, "VISUAL_DESIGN_MODE", "grounded")

    # The method imports the critique service inside the function body, so the
    # patch has to land on the defining module.
    monkeypatch.setattr(critique_mod, "VisualCritiqueService", _AlwaysFailsCritique)

    db_session.add(
        Project(id="proj_critique_gate", workspace_id="ws_default", name="Critique Gate")
    )
    db_session.commit()

    excal = ExcalidrawService()
    art = excal.get_or_create_artifact("proj_critique_gate", db_session)
    assert art.version == 1

    result = excal.generate_diagram_from_text(
        project_id="proj_critique_gate",
        text="the client calls the API which writes to the database",
        db=db_session,
        auto_apply=True,
    )

    assert result["auto_applied"] is False
    assert result["critique_ok"] is False
    assert result["critique_issues"]

    # Canvas untouched; the plan waits for a human.
    db_session.refresh(art)
    assert art.version == 1

    from app.models.excalidraw import ExcalidrawProposal

    proposal = (
        db_session.query(ExcalidrawProposal)
        .filter(ExcalidrawProposal.project_id == "proj_critique_gate")
        .first()
    )
    assert proposal is not None
    assert proposal.status == "pending"


def test_plan_evidence_unions_node_and_relationship_ids():
    from app.services.excalidraw_service import ExcalidrawService

    plan = VisualPlan(
        title="T",
        nodes=[
            _node("a", "A", evidence=("ev_1",)),
            _node("b", "B", evidence=("ev_2", "ev_1")),
        ],
        relationships=[
            VisualRelationship(source="a", target="b", evidence_ids=["ev_3"])
        ],
    )
    assert ExcalidrawService._plan_evidence(plan) == ["ev_1", "ev_2", "ev_3"]


# ---------------------------------------------------------------- fix 3


def test_deterministic_plan_has_no_hardcoded_dinein_template():
    from app.services.visual_plan_service import VisualPlanService

    svc = VisualPlanService.__new__(VisualPlanService)
    plan = svc._deterministic_plan(
        state_summary={"title": "MediClaim", "vision": "claims adjudication"},
        current_nodes=[],
        focus_prompt="restaurant table ordering dinein",
        evidence_snippets=[{"id": "ev_1", "content": "claims must return a denial reason"}],
    )
    labels = " ".join(n.label.lower() for n in plan.nodes)
    for forbidden in ("kitchen", "table qr", "pos integration", "orders & menu"):
        assert forbidden not in labels


def test_deterministic_plan_grounds_nodes_in_evidence():
    """In free design mode the deterministic fallback preserves content as a
    text notebook instead of fabricating a fixed diagram. Evidence ids travel
    on the note block so provenance survives without any diagram nodes."""
    from app.services.visual_plan_service import VisualPlanService

    svc = VisualPlanService.__new__(VisualPlanService)
    plan = svc._deterministic_plan(
        state_summary={"title": "MediClaim", "vision": "claims"},
        current_nodes=[],
        focus_prompt=None,
        evidence_snippets=[{"id": "ev_77", "content": "claims return a denial reason"}],
    )
    assert plan.canvas_strategy == "text"
    assert plan.model == "deterministic"
    blocks = plan.notes_document.sections[0].blocks
    assert blocks
    assert "ev_77" in (blocks[0].evidence_ids or [])


def test_deterministic_plan_notes_state_source_not_guessed_domain():
    from app.services.visual_plan_service import VisualPlanService

    svc = VisualPlanService.__new__(VisualPlanService)
    plan = svc._plan_from_text_deterministic("we need dinein table ordering", "X")
    blob = json.dumps(plan.notes).lower()
    assert "kitchen dispatch" not in blob


# ---------------------------------------------------------------- fix 1 prompt


def test_planner_prompt_exposes_evidence_ids_and_requires_citation():
    from app.services.visual_plan_service import VisualPlanService

    svc = VisualPlanService.__new__(VisualPlanService)
    prompt = svc._build_prompt(
        state_summary={"title": "EER"},
        current_nodes=[],
        evidence_snippets=[{"id": "ev_abc", "content": "add agentic layer"}],
        focus_prompt=None,
        constraints=[],
    )
    assert "[EVIDENCE: ev_abc]" in prompt
    assert "evidence_ids" in prompt
    assert "CONTENT AND REPRESENTATION ARE OPEN-ENDED" in prompt


def test_schema_accepts_singular_evidence_spelling():
    node = VisualNode(id="n", label="L", evidence_id="ev_x")
    assert node.evidence_ids == ["ev_x"]
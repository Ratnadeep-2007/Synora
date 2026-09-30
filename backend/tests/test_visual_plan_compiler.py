"""VisualPlan + deterministic Excalidraw compiler tests (spec section 19, cases 24-25)."""

import json

import pytest
from sqlalchemy.orm import Session

from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship
from app.services.excalidraw_compiler import ExcalidrawCompileError, ExcalidrawCompiler
from app.services.excalidraw_service import ExcalidrawService
from app.services.project_state_service import ProjectStateService
from app.services.visual_critique_service import VisualCritiqueService
from app.services.visual_plan_service import VisualPlanService
from app.services.visual_revision_service import VisualRevisionService


class FakeVisualClient:
    """Stub multimodal/visual planner returning a fixed JSON plan."""

    model_name = "fake-visual"

    def __init__(self, payload):
        self._payload = payload

    def generate_visual_plan(self, prompt: str) -> str:
        return json.dumps(self._payload)


# 24. Deterministic compiler produces valid Excalidraw JSON -------------------
def test_compiler_produces_valid_scene():
    plan = VisualPlan(
        title="Test",
        nodes=[
            VisualNode(id="a", label="Client", node_type="client"),
            VisualNode(id="b", label="Service", node_type="service"),
            VisualNode(id="c", label="DB", node_type="datastore"),
        ],
        relationships=[
            VisualRelationship(source="a", target="b"),
            VisualRelationship(source="b", target="c", style="dashed"),
        ],
    )
    scene = ExcalidrawCompiler().compile(plan)

    # validate_scene runs inside compile; assert structure explicitly too.
    assert any(el["type"] == "rectangle" for el in scene)
    assert any(el["type"] == "text" for el in scene)
    arrows = [el for el in scene if el["type"] == "arrow"]
    assert len(arrows) == 2
    assert arrows[0]["startBinding"]["elementId"] == "node_a"
    assert arrows[0]["endBinding"]["elementId"] == "node_b"
    assert arrows[1]["strokeStyle"] == "dashed"

    # Geometry is owned by the compiler, not the model.
    for el in scene:
        if el["type"] == "rectangle":
            assert {"x", "y", "width", "height"} <= set(el)

    # Stable ids make recompilation idempotent.
    again = ExcalidrawCompiler().compile(plan)
    assert [e["id"] for e in again] == [e["id"] for e in scene]


def test_compiler_rejects_empty_plan():
    with pytest.raises(ExcalidrawCompileError):
        ExcalidrawCompiler().compile(VisualPlan(nodes=[]))


def test_compiler_drops_relationship_with_unknown_node():
    plan = VisualPlan(
        nodes=[VisualNode(id="a", label="A", node_type="service")],
        relationships=[VisualRelationship(source="a", target="ghost")],
    )
    scene = ExcalidrawCompiler().compile(plan)
    assert not any(el["type"] == "arrow" for el in scene)


# Critique ---------------------------------------------------------------------
def test_critique_detects_overlap_and_missing_relationships():
    plan = VisualPlan(
        nodes=[
            VisualNode(id="a", label="A", node_type="service"),
            VisualNode(id="b", label="B", node_type="service"),
        ],
        relationships=[],  # no relationships -> flagged
    )
    overlapping = [
        {"id": "node_a", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 50},
        {"id": "node_b", "type": "rectangle", "x": 10, "y": 10, "width": 100, "height": 50},
    ]
    result = VisualCritiqueService().critique(plan, overlapping)
    assert result.ok is False
    assert any("overlap" in i.lower() for i in result.issues)
    assert any("relationship" in i.lower() for i in result.issues)


# Deterministic fallback plan is explicitly NOT labelled as AI -----------------
def test_visual_plan_deterministic_fallback_is_labelled():
    plan, ai_status = VisualPlanService().build_plan(
        state_summary={
            "title": "Demo",
            "architecture": [{"component": "API Gateway"}, {"component": "Worker"}],
        }
    )
    assert ai_status == "deterministic"
    assert plan.model == "deterministic"
    assert any(n.label == "Synora Agent" for n in plan.nodes)


def test_visual_plan_uses_injected_client_and_labels_ai():
    client = FakeVisualClient(
        {
            "title": "AI Plan",
            "nodes": [
                {"id": "x", "label": "X", "node_type": "service"},
                {"id": "y", "label": "Y", "node_type": "datastore"},
            ],
            "relationships": [{"source": "x", "target": "y"}],
        }
    )
    plan, ai_status = VisualPlanService(client=client).build_plan(
        state_summary={"title": "Demo"}
    )
    assert ai_status == "ai"
    assert plan.model == "fake-visual"
    assert len(plan.nodes) == 2


# 23. AI generation is proposal-only and never mutates the current revision ---
def test_ai_visual_architecture_is_proposal_only(db_session: Session):
    from app.models.project import Project

    db_session.add(Project(id="proj_plan_test", workspace_id="ws_default", name="Plan Test"))
    db_session.commit()
    ProjectStateService().get_or_create_state("proj_plan_test", db_session)

    excal = ExcalidrawService()
    excal.get_or_create_artifact("proj_plan_test", db_session)
    revisions = VisualRevisionService()
    before = revisions.current_revision("proj_plan_test", db_session)

    proposal, artifact = excal.generate_ai_visual_architecture(
        project_id="proj_plan_test",
        db=db_session,
        direct_apply=False,
        visual_plan_service=VisualPlanService(
            client=FakeVisualClient(
                {
                    "nodes": [
                        {"id": "a", "label": "Client", "node_type": "client"},
                        {"id": "b", "label": "API", "node_type": "service"},
                    ],
                    "relationships": [{"source": "a", "target": "b"}],
                }
            )
        ),
    )

    assert proposal.status == "pending"
    assert artifact is None  # nothing applied

    after = revisions.current_revision("proj_plan_test", db_session)
    assert after.id == before.id  # current visual workspace untouched

    diff = json.loads(proposal.diff_preview_json)
    assert diff["nodes_after"] == ["Client", "API"]
    assert diff["ai_status"] == "ai"
    assert "critique_ok" in diff

    # Now verify direct_apply=True automatically applies and advances the workspace
    proposal2, artifact2 = excal.generate_ai_visual_architecture(
        project_id="proj_plan_test",
        db=db_session,
        direct_apply=True,
        visual_plan_service=VisualPlanService(
            client=FakeVisualClient(
                {
                    "nodes": [
                        {"id": "a", "label": "Client", "node_type": "client"},
                        {"id": "b", "label": "API", "node_type": "service"},
                        {"id": "c", "label": "DB", "node_type": "database"},
                    ],
                    "relationships": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
                }
            )
        ),
    )
    assert proposal2.status == "approved"
    assert artifact2 is not None
    assert artifact2.version >= 2
    after2 = revisions.current_revision("proj_plan_test", db_session)
    assert after2.id != before.id


def test_generate_diagram_from_text_automated(db_session: Session):
    from app.models.project import Project
    from app.services.excalidraw_service import ExcalidrawService

    db_session.add(Project(id="proj_text_diagram_test", workspace_id="ws_default", name="Text Diagram Test"))
    db_session.commit()

    excal = ExcalidrawService()
    # Baseline must be clean and empty without predefined boilerplate
    art = excal.get_or_create_artifact("proj_text_diagram_test", db_session)
    assert json.loads(art.elements_json) == []
    assert json.loads(art.extracted_nodes_json) == []

    # Automated Text -> Model Analysis -> Excalidraw Output
    res = excal.generate_diagram_from_text(
        project_id="proj_text_diagram_test",
        text="Next.js frontend calls FastAPI backend with PostgreSQL database and Redis cache",
        db=db_session,
        auto_apply=True,
    )

    assert res["success"] is True
    assert res["auto_applied"] is True
    assert res["artifact_version"] >= 2
    assert len(res["elements"]) > 0

    # Ensure artifact in database was directly updated without waiting for manual UI approval
    db_session.refresh(art)
    elements = json.loads(art.elements_json)
    assert len(elements) > 0
    node_labels = json.loads(art.extracted_nodes_json)
    assert any("Backend" in l or "Postgres" in l or "Redis" in l or "Frontend" in l or "Service" in l or "Database" in l for l in node_labels)

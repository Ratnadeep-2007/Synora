"""Focused tests for semantic visual patch planning."""

from app.schemas.visual_patch import PatchSafetyClassification, VisualPatchOpType
from app.services.visual_patch_service import VisualPatchIntent, VisualPatchService


class FakeSemanticLLM:
    def generate_structured(self, prompt, schema):
        assert schema is VisualPatchIntent
        return VisualPatchIntent(
            operations=[
                {
                    "op_type": "ADD_NODE",
                    "target_id": "node_payment_service",
                    "label": "Payment Service",
                    "node_type": "service",
                },
                {
                    "op_type": "ADD_EDGE",
                    "target_id": "edge_order_payment",
                    "source": "node_order_service",
                    "target": "node_payment_service",
                },
                {
                    "op_type": "ADD_NOTE",
                    "target_id": "note_payment_order",
                    "category": "REQUIREMENT",
                    "content": "Payment must complete before order confirmation.",
                },
            ],
            safety_classification=PatchSafetyClassification.SAFE_AUTO_APPLY,
            context_notes=[
                "PURPOSE — Table ordering platform for restaurant guests.",
                "CURRENT STATE — Payment now participates in order confirmation.",
                "KEY DECISION — Payment is required before final confirmation.",
            ],
            reason="Payment is introduced into the order-confirmation workflow.",
        )


def test_visual_patch_planning_is_model_driven():
    service = VisualPatchService(llm_client=FakeSemanticLLM())
    operations, context_notes, safety, reason = service._synthesize_operations(
        project_id="proj_dinein",
        text="Payment must complete before the order is confirmed.",
        state={},
        current_rev=None,
    )

    assert safety == PatchSafetyClassification.SAFE_AUTO_APPLY
    assert context_notes[0].startswith("PURPOSE")
    assert "Payment" in reason
    assert [op.op_type for op in operations] == [
        VisualPatchOpType.ADD_NODE,
        VisualPatchOpType.ADD_EDGE,
        VisualPatchOpType.ADD_NOTE,
    ]
    assert operations[0].label == "Payment Service"


def test_visual_patch_planner_does_not_require_domain_keywords():
    service = VisualPatchService(llm_client=FakeSemanticLLM())
    operations, _, _, _ = service._synthesize_operations(
        project_id="proj_dinein",
        text="Introduce a secure payment gateway before confirmation.",
        state={},
        current_rev=None,
    )

    assert operations
    assert any(op.target_id == "node_payment_service" for op in operations)


def test_three_way_merge_preserves_unrelated_human_canvas_edits():
    from app.schemas.visual_patch import VisualPatch, VisualPatchOperation
    from app.services.visual_merge_service import VisualMergeService

    base = [
        {
            "id": "node_order_service",
            "semantic_id": "node_order_service",
            "semantic_type": "node",
            "type": "rectangle",
            "x": 100,
            "y": 100,
            "width": 220,
            "height": 92,
            "strokeWidth": 1,
        },
        {
            "id": "context_current_state",
            "semantic_id": "context_current_state",
            "semantic_type": "note",
            "type": "rectangle",
            "x": 500,
            "y": 100,
            "width": 760,
            "height": 108,
            "boundElements": [{"type": "text", "id": "txt_context_current_state"}],
        },
        {
            "id": "txt_context_current_state",
            "semantic_id": "context_current_state",
            "semantic_type": "note_text",
            "type": "text",
            "text": "[PROJECT_CONTEXT]\nInitial state",
            "containerId": "context_current_state",
        },
    ]
    user = [dict(el) for el in base]
    user[0]["x"] = 900
    user[0]["y"] = 700
    user[2]["text"] = "[PROJECT_CONTEXT]\nHuman-edited state"

    patch = VisualPatch(
        patch_id="vpatch_test",
        project_id="proj",
        base_revision_number=1,
        operations=[
            VisualPatchOperation(
                op_type="UPDATE_NOTE",
                target_id="context_current_state",
                category="PROJECT_CONTEXT",
                content="AI synthesized state",
            )
        ],
    )

    merged, applied, conflicts = VisualMergeService().merge(
        base_elements=base,
        user_elements=user,
        patch=patch,
    )

    assert next(e for e in merged if e["id"] == "node_order_service")["x"] == 900
    assert next(e for e in merged if e["id"] == "node_order_service")["y"] == 700
    assert next(e for e in merged if e["id"] == "txt_context_current_state")["text"] == "[PROJECT_CONTEXT]\nHuman-edited state"
    assert conflicts
    assert not applied


def test_project_visual_update_entrypoints_do_not_compile_or_replace_full_scene():
    import inspect
    from app.services.excalidraw_service import ExcalidrawService

    source = inspect.getsource(ExcalidrawService._create_semantic_visual_proposal)
    source += inspect.getsource(ExcalidrawService.generate_proposal_from_state)
    source += inspect.getsource(ExcalidrawService.generate_ai_visual_architecture)
    source += inspect.getsource(ExcalidrawService.generate_diagram_from_text)
    source += inspect.getsource(ExcalidrawService.review_proposal)

    assert "ExcalidrawCompiler" not in source
    assert "artifact.elements_json = json.dumps(proposed_elements)" not in source
    assert "artifact.elements_json = json.dumps(compiled_elements)" not in source
    assert "artifact.elements_json = proposal.proposed_elements_json" not in source
    assert "VisualPatchService" in source

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
            reason="Payment is introduced into the order-confirmation workflow.",
        )


def test_visual_patch_planning_is_model_driven():
    service = VisualPatchService(llm_client=FakeSemanticLLM())
    operations, safety, reason = service._synthesize_operations(
        project_id="proj_dinein",
        text="Payment must complete before the order is confirmed.",
        state={},
        current_rev=None,
    )

    assert safety == PatchSafetyClassification.SAFE_AUTO_APPLY
    assert "Payment" in reason
    assert [op.op_type for op in operations] == [
        VisualPatchOpType.ADD_NODE,
        VisualPatchOpType.ADD_EDGE,
        VisualPatchOpType.ADD_NOTE,
    ]
    assert operations[0].label == "Payment Service"


def test_visual_patch_planner_does_not_require_domain_keywords():
    service = VisualPatchService(llm_client=FakeSemanticLLM())
    operations, _, _ = service._synthesize_operations(
        project_id="proj_dinein",
        text="Introduce a secure payment gateway before confirmation.",
        state={},
        current_rev=None,
    )

    assert operations
    assert any(op.target_id == "node_payment_service" for op in operations)

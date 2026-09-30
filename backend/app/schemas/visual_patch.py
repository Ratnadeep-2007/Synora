from enum import Enum
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class VisualPatchOpType(str, Enum):
    ADD_NODE = "ADD_NODE"
    UPDATE_NODE = "UPDATE_NODE"
    REMOVE_NODE = "REMOVE_NODE"

    ADD_EDGE = "ADD_EDGE"
    UPDATE_EDGE = "UPDATE_EDGE"
    REMOVE_EDGE = "REMOVE_EDGE"

    ADD_NOTE = "ADD_NOTE"
    UPDATE_NOTE = "UPDATE_NOTE"
    REMOVE_NOTE = "REMOVE_NOTE"

    ADD_GROUP = "ADD_GROUP"
    UPDATE_GROUP = "UPDATE_GROUP"
    REMOVE_GROUP = "REMOVE_GROUP"

    REQUEST_LAYOUT_ADJUSTMENT = "REQUEST_LAYOUT_ADJUSTMENT"


class PatchSafetyClassification(str, Enum):
    SAFE_AUTO_APPLY = "SAFE_AUTO_APPLY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    USER_ONLY = "USER_ONLY"


class VisualNoteCategory(str, Enum):
    DECISION = "DECISION"
    REQUIREMENT = "REQUIREMENT"
    ACTION = "ACTION"
    RISK = "RISK"
    CONSTRAINT = "CONSTRAINT"
    INTEGRATION = "INTEGRATION"
    OPEN_QUESTION = "OPEN_QUESTION"
    ARCHITECTURE_PRINCIPLE = "ARCHITECTURE_PRINCIPLE"
    CONVERSATION = "CONVERSATION"


def make_stable_semantic_id(prefix: str, name: str) -> str:
    """Generate deterministic, stable semantic id that survives layout, revisions, and reordering.

    Example: prefix='node', name='Kitchen Display System' -> 'node_kitchen_display_system'
    """
    clean = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return f"{prefix}_{clean}" if clean else f"{prefix}_unknown"


class VisualPatchOperation(BaseModel):
    op_type: VisualPatchOpType
    target_id: str = Field(description="Stable semantic ID of the target element")
    label: Optional[str] = None
    node_type: Optional[str] = Field(
        default=None,
        description="client | service | datastore | actor | decision | requirement | group | note | infrastructure",
    )
    source: Optional[str] = Field(default=None, description="Source node id for edge operations")
    target: Optional[str] = Field(default=None, description="Target node id for edge operations")
    style: Optional[str] = Field(default="solid", description="solid | dashed")
    group: Optional[str] = None
    emphasis: Optional[str] = Field(default="normal", description="normal | primary | muted")
    category: Optional[VisualNoteCategory] = None
    content: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)


class VisualPatch(BaseModel):
    patch_id: str
    project_id: str
    base_revision_number: Optional[int] = None
    operations: List[VisualPatchOperation] = Field(default_factory=list)
    safety_classification: PatchSafetyClassification = PatchSafetyClassification.SAFE_AUTO_APPLY
    reason: str = ""
    evidence_ids: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator


class VisualNode(BaseModel):
    """A semantic diagram node. The agent chooses meaning; the compiler chooses placement."""

    id: str = Field(description="Stable semantic id used for element identity")
    label: str
    node_type: str = Field(
        default="service",
        description="Free-form semantic type such as service, actor, datastore, decision, system, milestone, etc.",
    )
    group: Optional[str] = None
    emphasis: Optional[str] = Field(default=None, description="normal | primary | muted")
    annotations: List[str] = []
    evidence_ids: List[str] = Field(default=[])
    support_type: str = Field(
        default="inferred",
        description="explicit = stated in evidence; inferred = reasoned by the model",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_evidence(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw = data.get("evidence_ids")
            if isinstance(raw, str):
                data = dict(data)
                data["evidence_ids"] = [raw]
            elif isinstance(raw, tuple):
                data = dict(data)
                data["evidence_ids"] = list(raw)
        return data

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "type" in data and "node_type" not in data:
                data["node_type"] = data.pop("type")
            if "evidence_ids" not in data:
                for alt in ("evidence_id", "evidence", "sources", "source"):
                    if alt in data:
                        data["evidence_ids"] = data.pop(alt)
                        break
        return data

    @property
    def type(self) -> str:
        return self.node_type


class VisualRelationship(BaseModel):
    """A semantic relationship. Geometry is deliberately absent from the schema."""

    source: str
    target: str
    label: Optional[str] = None
    style: Optional[str] = Field(default="solid")
    evidence_ids: List[str] = Field(default=[])
    support_type: str = Field(default="inferred")

    @model_validator(mode="before")
    @classmethod
    def _coerce_edge_evidence(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw = data.get("evidence_ids")
            if isinstance(raw, str):
                data = dict(data)
                data["evidence_ids"] = [raw]
            elif isinstance(raw, tuple):
                data = dict(data)
                data["evidence_ids"] = list(raw)
        return data

    @model_validator(mode="before")
    @classmethod
    def normalize_edges(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "from" in data and "source" not in data:
                data["source"] = data.pop("from")
            elif "from_node" in data and "source" not in data:
                data["source"] = data.pop("from_node")
            if "to" in data and "target" not in data:
                data["target"] = data.pop("to")
            elif "to_node" in data and "target" not in data:
                data["target"] = data.pop("to_node")
            if "evidence_ids" not in data:
                for alt in ("evidence_id", "evidence", "sources", "source_ids"):
                    if alt in data:
                        data["evidence_ids"] = data.pop(alt)
                        break
        return data


class NoteBlock(BaseModel):
    """A document block for rich, human-readable project notes."""

    id: str = Field(description="Stable semantic block id")
    block_type: str = Field(
        default="paragraph",
        description="paragraph | heading | bullets | numbered | checklist | quote | key_value | table | callout | divider",
    )
    text: str = ""
    items: List[str] = []
    rows: List[List[str]] = []
    title: Optional[str] = None
    level: int = Field(default=2, ge=1, le=4)
    tone: Optional[str] = None
    evidence_ids: List[str] = []
    support_type: str = Field(default="explicit")

    @model_validator(mode="before")
    @classmethod
    def normalize_block(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"id": "note_block", "block_type": "paragraph", "text": data}
        if isinstance(data, dict):
            data = dict(data)
            if "type" in data and "block_type" not in data:
                data["block_type"] = data.pop("type")
            if "content" in data and not data.get("text"):
                data["text"] = data.pop("content")
            if "evidence_id" in data and "evidence_ids" not in data:
                data["evidence_ids"] = [data.pop("evidence_id")]
        return data


class NoteSection(BaseModel):
    """A coherent chapter of the project notebook."""

    id: str = Field(description="Stable semantic section id")
    title: str
    blocks: List[NoteBlock] = []
    order: int = 0
    evidence_ids: List[str] = []
    support_type: str = Field(default="explicit")

    @model_validator(mode="before")
    @classmethod
    def normalize_section(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {
                "id": "notes",
                "title": "Notes",
                "blocks": [{"id": "note_block", "block_type": "paragraph", "text": data}],
            }
        if isinstance(data, dict):
            data = dict(data)
            if "content" in data and "blocks" not in data:
                data["blocks"] = [{"id": "note_block", "block_type": "paragraph", "text": str(data.pop("content"))}]
            if "body" in data and "blocks" not in data:
                body = str(data.pop("body") or "").strip()
                bullets = data.pop("bullets", []) or []
                blocks: List[Dict[str, Any]] = []
                if body:
                    blocks.append({"id": "body", "block_type": "paragraph", "text": body})
                if bullets:
                    blocks.append({"id": "bullets", "block_type": "bullets", "items": bullets})
                data["blocks"] = blocks
            if "evidence_id" in data and "evidence_ids" not in data:
                data["evidence_ids"] = [data.pop("evidence_id")]
        return data


class NotesDocument(BaseModel):
    """The complete project notebook. Structure is chosen by the agent, not hard-coded."""

    title: str = "PROJECT NOTES"
    subtitle: Optional[str] = None
    sections: List[NoteSection] = []
    updated_label: Optional[str] = None


class VisualPrimitive(BaseModel):
    """A free-form semantic visual primitive. No x/y positioning is accepted from the agent."""

    id: str
    primitive_type: str = Field(
        default="rectangle",
        description="Free-form semantic/rendering type. Compiler supports common Excalidraw primitives and gracefully falls back for unknown types.",
    )
    text: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    target: Optional[str] = None
    group: Optional[str] = None
    width: Optional[float] = None
    height: Optional[float] = None
    style: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}
    evidence_ids: List[str] = []
    support_type: str = Field(default="explicit")

    @model_validator(mode="before")
    @classmethod
    def normalize_primitive(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "type" in data and "primitive_type" not in data:
                data["primitive_type"] = data.pop("type")
            # Position is compiler-owned. Ignore model-provided geometry
            # coordinates rather than allowing an LLM to write x/y to the canvas.
            data.pop("x", None)
            data.pop("y", None)
            data.pop("position", None)
            if "evidence_id" in data and "evidence_ids" not in data:
                data["evidence_ids"] = [data.pop("evidence_id")]
        return data


class VisualVisualization(BaseModel):
    """An open-ended visual composition.

    The agent is free to invent the semantic form: matrices, timelines, flows,
    maps, quadrants, scorecards, system sketches, callouts, or a custom
    composition. Only canvas positioning is compiler-owned.
    """

    id: str
    kind: str = Field(default="custom", description="Free-form visual kind; do not constrain the agent to a fixed vocabulary.")
    title: Optional[str] = None
    purpose: Optional[str] = None
    elements: List[VisualPrimitive] = []
    content: Dict[str, Any] = {}
    evidence_ids: List[str] = []
    support_type: str = Field(default="explicit")

    @model_validator(mode="before")
    @classmethod
    def normalize_visualization(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "text" in data and not data.get("content"):
                data["content"] = {"text": data.pop("text")}
            if "visual_elements" in data and "elements" not in data:
                data["elements"] = data.pop("visual_elements")
            if "evidence_id" in data and "evidence_ids" not in data:
                data["evidence_ids"] = [data.pop("evidence_id")]
        return data


class VisualPlan(BaseModel):
    """Semantic plan for a living project notebook + optional visual modeling canvas.

    The agent decides what deserves notes, a visualization, or a genuine diagram.
    The compiler is responsible for positioning and collision avoidance only.
    """

    title: Optional[str] = None
    canvas_strategy: str = Field(default="mixed", description="text | mixed | diagram")
    layout_direction: str = Field(default="horizontal", description="horizontal | vertical")
    grouping_intent: List[str] = []
    nodes: List[VisualNode] = []
    relationships: List[VisualRelationship] = []
    groups: List[Any] = []
    layout: Optional[Dict[str, Any]] = None
    emphasis: List[str] = []
    preserve: List[str] = Field(default=[])
    add: List[str] = []
    change: List[str] = []
    remove: List[str] = []

    notes_document: Optional[NotesDocument] = None
    notes_sections: List[NoteSection] = []
    visualizations: List[VisualVisualization] = []

    # Backward-compatible note representation retained for existing callers.
    notes: List[Union[str, Dict[str, Any]]] = []

    model: str = ""
    prompt_version: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize_plan(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "edges" in data and "relationships" not in data:
                data["relationships"] = data.pop("edges")
            if "layout" in data and isinstance(data["layout"], dict):
                dir_val = data["layout"].get("direction")
                if dir_val in ("left_to_right", "horizontal"):
                    data.setdefault("layout_direction", "horizontal")
                elif dir_val in ("top_to_bottom", "vertical"):
                    data.setdefault("layout_direction", "vertical")
            if "note_sections" in data and "notes_sections" not in data:
                data["notes_sections"] = data.pop("note_sections")
            if "visuals" in data and "visualizations" not in data:
                data["visualizations"] = data.pop("visuals")
        return data

    @property
    def edges(self) -> List[VisualRelationship]:
        return self.relationships


class VisualCritique(BaseModel):
    """Result of the deterministic visual critique pass."""

    ok: bool = True
    issues: List[str] = []
    repairs_applied: List[str] = []

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator


class VisualNode(BaseModel):
    """A node the visual model wants on the canvas."""

    id: str = Field(description="Stable semantic id used for element identity")
    label: str
    node_type: str = Field(
        default="service",
        description="client | service | datastore | actor | decision | requirement | group | note | infrastructure",
    )
    group: Optional[str] = None
    emphasis: Optional[str] = Field(default=None, description="normal | primary | muted")
    annotations: List[str] = []
    # Provenance. A node must cite the evidence that justifies it.
    evidence_ids: List[str] = Field(default=[], description="Evidence ids justifying this node")

    @model_validator(mode="before")
    @classmethod
    def _coerce_evidence(cls, data: Any) -> Any:
        """Accept a bare string where a list of ids was requested."""
        if isinstance(data, dict):
            raw = data.get("evidence_ids")
            if isinstance(raw, str):
                data = dict(data)
                data["evidence_ids"] = [raw]
            elif isinstance(raw, tuple):
                data = dict(data)
                data["evidence_ids"] = list(raw)
        return data
    support_type: str = Field(
        default="inferred",
        description="explicit = stated in evidence; inferred = reasoned by the model",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "type" in data and "node_type" not in data:
                data = dict(data)
                data["node_type"] = data.pop("type")
            # Tolerate singular / alternate evidence spellings from the model.
            if "evidence_ids" not in data:
                for alt in ("evidence_id", "evidence", "sources", "source"):
                    if alt in data:
                        data = dict(data)
                        data["evidence_ids"] = data.pop(alt)
                        break
        return data

    @property
    def type(self) -> str:
        return self.node_type


class VisualRelationship(BaseModel):
    """A directed relationship between two nodes."""

    source: str
    target: str
    label: Optional[str] = None
    style: Optional[str] = Field(default="solid", description="solid | dashed")
    evidence_ids: List[str] = Field(default=[], description="Evidence ids justifying this edge")

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
    support_type: str = Field(default="inferred", description="explicit | inferred")

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


class VisualNoteSection(BaseModel):
    """A document-like notes section rendered on the notes page."""

    id: str = Field(description="Stable semantic section id")
    title: str
    body: str = ""
    bullets: List[str] = []
    order: int = 0
    evidence_ids: List[str] = []
    support_type: str = Field(default="explicit", description="explicit | inferred")

    @model_validator(mode="before")
    @classmethod
    def normalize_section(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"id": "notes", "title": "Notes", "body": data}
        if isinstance(data, dict):
            data = dict(data)
            if "content" in data and "body" not in data:
                data["body"] = data.pop("content")
            if "text" in data and "body" not in data:
                data["body"] = data.pop("text")
            if "evidence_id" in data and "evidence_ids" not in data:
                data["evidence_ids"] = [data.pop("evidence_id")]
        return data


class VisualVisualization(BaseModel):
    """A lightweight visual when a full diagram would not add enough value."""

    id: str = Field(description="Stable semantic visualization id")
    kind: str = Field(
        default="callout",
        description="metric | status | callout | timeline",
    )
    title: str
    value: Optional[str] = None
    items: List[str] = []
    caption: Optional[str] = None
    evidence_ids: List[str] = []
    support_type: str = Field(default="explicit", description="explicit | inferred")

    @model_validator(mode="before")
    @classmethod
    def normalize_visualization(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "text" in data and "value" not in data:
                data["value"] = data.pop("text")
            if "evidence_id" in data and "evidence_ids" not in data:
                data["evidence_ids"] = [data.pop("evidence_id")]
        return data


class VisualPlan(BaseModel):
    """A structured, semantic canvas plan.

    The AI decides what deserves plain text, lightweight visualization, or a
    genuine diagram. The deterministic compiler owns all pixel geometry.
    """

    title: Optional[str] = None
    canvas_strategy: str = Field(
        default="mixed",
        description="text | mixed | diagram",
    )
    layout_direction: str = Field(default="horizontal", description="horizontal | vertical")
    grouping_intent: List[str] = []
    nodes: List[VisualNode] = []
    relationships: List[VisualRelationship] = []
    groups: List[Any] = []
    layout: Optional[Dict[str, Any]] = None
    emphasis: List[str] = []
    preserve: List[str] = Field(default=[], description="Node ids that must remain")
    add: List[str] = []
    change: List[str] = []
    remove: List[str] = []
    notes_sections: List[VisualNoteSection] = []
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

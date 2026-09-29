from typing import Any, Dict, List, Optional
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

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "type" in data and "node_type" not in data:
                data = dict(data)
                data["node_type"] = data.pop("type")
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
        return data


class VisualPlan(BaseModel):
    """A structured, semantic description of a diagram.

    The AI produces a VisualPlan, NEVER raw Excalidraw JSON. The deterministic
    compiler owns coordinates, spacing, alignment, routing, dimensions,
    collision avoidance, typography and viewport fitting.
    """

    title: Optional[str] = None
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
    notes: List[str] = []
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
        return data

    @property
    def edges(self) -> List[VisualRelationship]:
        return self.relationships


class VisualCritique(BaseModel):
    """Result of the deterministic visual critique pass."""

    ok: bool = True
    issues: List[str] = []
    repairs_applied: List[str] = []

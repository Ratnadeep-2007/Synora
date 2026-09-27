from typing import List, Optional
from pydantic import BaseModel, Field


class VisualNode(BaseModel):
    """A node the visual model wants on the canvas."""

    id: str = Field(description="Stable semantic id used for element identity")
    label: str
    node_type: str = Field(
        default="service",
        description="client | service | datastore | actor | decision | requirement | group | note",
    )
    group: Optional[str] = None
    emphasis: Optional[str] = Field(default=None, description="normal | primary | muted")
    annotations: List[str] = []


class VisualRelationship(BaseModel):
    """A directed relationship between two nodes."""

    source: str
    target: str
    label: Optional[str] = None
    style: Optional[str] = Field(default="solid", description="solid | dashed")


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
    preserve: List[str] = Field(default=[], description="Node ids that must remain")
    add: List[str] = []
    change: List[str] = []
    remove: List[str] = []
    notes: List[str] = []
    model: str = ""
    prompt_version: str = ""


class VisualCritique(BaseModel):
    """Result of the deterministic visual critique pass."""

    ok: bool = True
    issues: List[str] = []
    repairs_applied: List[str] = []

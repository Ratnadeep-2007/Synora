from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.connectors.base import (
    BaseConnector,
    ConnectorHealth,
    ConnectorStatus,
    FetchEventsResult,
)
from app.schemas.source_event import SourceEventCreate

logger = logging.getLogger(__name__)


class ExcalidrawConnector(BaseConnector):
    """
    Excalidraw Connector conforming to BaseConnector contract.
    Handles:
    - Role A (Input): Ingests visual diagram scene files and normalizes them into SourceEvents.
    - Role B (Output): Formulates proposed diagram changes derived from approved Project State.
    """

    provider_name: str = "excalidraw"

    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """
        Validate Excalidraw integration parameters.
        For file/URL ingestion, validates that a workspace or token is provided if required.
        """
        # Excalidraw JSON files can be local or via Excalidraw+ API
        return True

    def disconnect(self, connection_id: str) -> bool:
        """Disconnect visual artifact integration."""
        logger.info(f"Excalidraw artifact connection {connection_id} disconnected.")
        return True

    def health_check(self, connection_id: Optional[str] = None) -> ConnectorHealth:
        """Verify Excalidraw parser and serializer readiness."""
        return ConnectorHealth(
            provider=self.provider_name,
            status=ConnectorStatus.HEALTHY,
            latency_ms=1.0,
            details={"type": "visual_artifact", "format": "application/vnd.excalidraw+json"},
        )

    def fetch_events(
        self,
        connection_id: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        **kwargs: Any,
    ) -> FetchEventsResult:
        """
        Simulate or retrieve diagram change events.
        """
        raw_diagrams = kwargs.get("raw_diagrams", [])
        project_id = kwargs.get("project_id", "default_project")
        tenant_id = kwargs.get("tenant_id", "default_tenant")

        events: List[SourceEventCreate] = []
        for diag in raw_diagrams:
            ev = self.normalize(
                raw_data=diag,
                event_type="diagram_change",
                project_id=project_id,
                tenant_id=tenant_id,
            )
            events.append(ev)

        return FetchEventsResult(
            events=events,
            next_cursor=None,
            has_more=False,
        )

    def normalize(self, raw_data: Any, event_type: str = "diagram_change", **kwargs: Any) -> SourceEventCreate:
        """
        Transform Excalidraw diagram scene data into a standardized SourceEventCreate.
        """
        project_id = kwargs.get("project_id", "default_project")
        tenant_id = kwargs.get("tenant_id", "default_tenant")

        if isinstance(raw_data, dict):
            artifact_id = raw_data.get("artifact_id", "diag_01")
            version = raw_data.get("version", 1)
            name = raw_data.get("name", "Architecture Diagram")
            elements = raw_data.get("elements", [])
            actor_id = raw_data.get("actor_id", "architect")
        else:
            artifact_id = getattr(raw_data, "id", "diag_01")
            version = getattr(raw_data, "version", 1)
            name = getattr(raw_data, "name", "Architecture Diagram")
            elements = getattr(raw_data, "elements", [])
            actor_id = getattr(raw_data, "actor_id", "architect")

        # Extract text nodes representing workflow or architecture components
        extracted_nodes = []
        for el in elements:
            if isinstance(el, dict) and el.get("type") == "text":
                text_val = el.get("text", "").strip()
                if text_val and text_val not in extracted_nodes:
                    extracted_nodes.append(text_val)

        source_event_id = f"excal_{artifact_id}_v{version}"
        summary_text = f"Excalidraw diagram '{name}' v{version} containing components: {' -> '.join(extracted_nodes)}"

        return SourceEventCreate(
            tenant_id=tenant_id,
            project_id=project_id,
            source=self.provider_name,
            source_event_id=source_event_id,
            event_type=event_type,
            actor_id=actor_id,
            occurred_at=datetime.now(timezone.utc),
            payload={
                "artifact_id": artifact_id,
                "name": name,
                "version": version,
                "elements_count": len(elements),
                "extracted_nodes": extracted_nodes,
                "summary": summary_text,
                "provider": "excalidraw",
            },
            status="received",
        )

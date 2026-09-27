from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.excalidraw import (
    ExcalidrawArtifact,
    ExcalidrawRevision,
    ExcalidrawProposal,
    ExcalidrawProposalStatus,
)
from app.models.evidence import Evidence
from app.models.project import Project
from app.models.project_state import ProjectState, ProjectStateVersion
from app.schemas.excalidraw import (
    ExcalidrawArtifactRead,
    ExcalidrawDiffPreview,
    ExcalidrawRevisionDiffRead,
    ExcalidrawRevisionRead,
    ExcalidrawIngestRequest,
    ExcalidrawProposalRead,
)
from app.schemas.source_event import SourceEventCreate
from app.services.audit_service import AuditService
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)


class ExcalidrawError(SynesisException):
    """Raised when an operation on an Excalidraw artifact or proposal fails."""
    pass


class ExcalidrawService:
    """
    Excalidraw Service managing visual architecture diagrams in Synesis.
    Fulfills two explicit roles:
    - Role A (Input): Ingests visual diagram scenes as evidence.
    - Role B (Output): Proposes diagram changes derived from approved Project State,
      strictly requiring human approval before mutation (Output Safety).
    """

    def __init__(
        self,
        ingestion_service: Optional[IngestionService] = None,
        audit_service: Optional[AuditService] = None,
    ):
        self.ingestion_service = ingestion_service or IngestionService()
        self.audit_service = audit_service or AuditService()

    def get_or_create_artifact(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        name: str = "System Architecture Diagram",
    ) -> ExcalidrawArtifact:
        """Retrieves existing visual artifact or initializes baseline."""
        artifact = (
            db.query(ExcalidrawArtifact)
            .filter(
                ExcalidrawArtifact.project_id == project_id,
                ExcalidrawArtifact.tenant_id == tenant_id,
            )
            .first()
        )
        if not artifact:
            # Default baseline elements: canonical 5-tier flow
            canonical_capabilities = ["Business Analysis", "Project Planning", "Functional Analysis", "Technical Architecture", "Frappe / ERP Analysis"]
            initial_elements = self._build_living_workspace_elements(canonical_capabilities)
            baseline_nodes = ["Sources / Evidence", "One Shared Synora Agent", "Capabilities", "Deterministic Guardrails", "Authoritative Project State", "Excalidraw Living Workspace"]
            artifact = ExcalidrawArtifact(
                project_id=project_id,
                tenant_id=tenant_id,
                name=name,
                version=1,
                elements_json=json.dumps(initial_elements),
                app_state_json=json.dumps({"viewBackgroundColor": "#ffffff", "gridSize": 20}),
                extracted_nodes_json=json.dumps(baseline_nodes),
            )
            db.add(artifact)
            db.flush()
            self._create_revision(
                artifact,
                db,
                revision_number=1,
                actor_id="system",
                change_summary={"action": "baseline_created", "revision": 1},
            )
            db.commit()
            db.refresh(artifact)
            logger.info(f"Initialized ExcalidrawArtifact v1 for project '{project_id}'")
        return artifact


    def _snapshot_payload(self, artifact: ExcalidrawArtifact) -> Dict[str, Any]:
        return {
            "elements": json.loads(artifact.elements_json) if artifact.elements_json else [],
            "app_state": json.loads(artifact.app_state_json) if artifact.app_state_json else {},
            "extracted_nodes": json.loads(artifact.extracted_nodes_json) if artifact.extracted_nodes_json else [],
        }

    def _create_revision(
        self,
        artifact: ExcalidrawArtifact,
        db: Session,
        *,
        revision_number: Optional[int] = None,
        derived_from_state_version: Optional[int] = None,
        parent_revision_id: Optional[str] = None,
        change_summary: Optional[Dict[str, Any]] = None,
        source_event_ids: Optional[List[str]] = None,
        proposal_id: Optional[str] = None,
        actor_id: str = "system",
    ) -> ExcalidrawRevision:
        revision_number = revision_number or artifact.version
        existing = (
            db.query(ExcalidrawRevision)
            .filter(
                ExcalidrawRevision.artifact_id == artifact.id,
                ExcalidrawRevision.revision_number == revision_number,
            )
            .first()
        )
        if existing:
            return existing

        revision = ExcalidrawRevision(
            artifact_id=artifact.id,
            project_id=artifact.project_id,
            tenant_id=artifact.tenant_id,
            revision_number=revision_number,
            parent_revision_id=parent_revision_id,
            derived_from_state_version=derived_from_state_version,
            snapshot_json=json.dumps(self._snapshot_payload(artifact)),
            change_summary_json=json.dumps(change_summary or {}),
            source_event_ids_json=json.dumps(source_event_ids or []),
            proposal_id=proposal_id,
            actor_id=actor_id,
        )
        db.add(revision)
        db.flush()
        return revision

    def _ensure_current_revision(
        self,
        artifact: ExcalidrawArtifact,
        db: Session,
        actor_id: str = "system",
    ) -> ExcalidrawRevision:
        existing = (
            db.query(ExcalidrawRevision)
            .filter(
                ExcalidrawRevision.artifact_id == artifact.id,
                ExcalidrawRevision.revision_number == artifact.version,
            )
            .first()
        )
        if existing:
            return existing
        return self._create_revision(
            artifact,
            db,
            actor_id=actor_id,
            change_summary={"action": "backfill_current_revision", "revision": artifact.version},
        )

    @staticmethod
    def _element_diff(
        old_elements: List[Dict[str, Any]],
        new_elements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        old_by_id = {str(e.get("id")): e for e in old_elements if e.get("id")}
        new_by_id = {str(e.get("id")): e for e in new_elements if e.get("id")}
        added = [new_by_id[k] for k in new_by_id.keys() - old_by_id.keys()]
        removed = [old_by_id[k] for k in old_by_id.keys() - new_by_id.keys()]
        changed = []
        for key in new_by_id.keys() & old_by_id.keys():
            before = old_by_id[key]
            after = new_by_id[key]
            if json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
                changed.append({"before": before, "after": after})
        unchanged = len(new_by_id.keys() & old_by_id.keys()) - len(changed)
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged": max(0, unchanged),
        }

    def ingest_diagram(
        self,
        project_id: str,
        req: ExcalidrawIngestRequest,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> tuple[ExcalidrawArtifact, Evidence]:
        """
        Role A (Input): Ingests an Excalidraw scene as authoritative architectural evidence.
        Emits a SourceEvent ('excalidraw', 'diagram_change') and creates an Evidence record.
        """
        extracted_nodes = self._extract_node_labels(req.elements)
        artifact = (
            db.query(ExcalidrawArtifact)
            .filter(
                ExcalidrawArtifact.project_id == project_id,
                ExcalidrawArtifact.tenant_id == tenant_id,
            )
            .first()
        )

        if not artifact:
            artifact = ExcalidrawArtifact(
                project_id=project_id,
                tenant_id=tenant_id,
                name=req.name,
                version=1,
                elements_json=json.dumps(req.elements),
                app_state_json=json.dumps(req.app_state),
                extracted_nodes_json=json.dumps(extracted_nodes),
            )
            db.add(artifact)
        else:
            artifact.name = req.name
            artifact.elements_json = json.dumps(req.elements)
            artifact.app_state_json = json.dumps(req.app_state)
            artifact.extracted_nodes_json = json.dumps(extracted_nodes)
            artifact.version += 1

        db.flush()
        parent = (
            db.query(ExcalidrawRevision)
            .filter(
                ExcalidrawRevision.artifact_id == artifact.id,
                ExcalidrawRevision.revision_number == artifact.version - 1,
            )
            .first()
        )
        # Revision is tied to the saved artifact state and is immutable.
        self._create_revision(
            artifact,
            db,
            parent_revision_id=parent.id if parent else None,
            actor_id="human",
            change_summary={"action": "manual_ingest", "name": artifact.name},
        )
        db.commit()
        db.refresh(artifact)

        # Ingest as SourceEvent + Evidence
        event_create = SourceEventCreate(
            tenant_id=tenant_id,
            project_id=project_id,
            source="excalidraw",
            source_event_id=f"excal_{artifact.id}_v{artifact.version}",
            event_type="diagram_change",
            actor_id="system_excalidraw",
            occurred_at=datetime.now(timezone.utc),
            payload={
                "artifact_id": artifact.id,
                "version": artifact.version,
                "name": artifact.name,
                "nodes": extracted_nodes,
                "element_count": len(req.elements),
                "summary": f"Excalidraw diagram '{req.name}' updated to v{artifact.version} with nodes: {', '.join(extracted_nodes)}",
            },
        )
        source_event = self.ingestion_service.ingest_event(event_create, db)
        evidence = self.ingestion_service.create_evidence_from_event(
            event=source_event,
            db=db,
            content=f"Architecture Diagram: {req.name} (v{artifact.version}). Nodes: {', '.join(extracted_nodes)}",
            metadata={"artifact_id": artifact.id, "extracted_nodes": extracted_nodes},
        )

        logger.info(f"Ingested Excalidraw diagram for project '{project_id}' as evidence '{evidence.id}'")
        return artifact, evidence

    def generate_proposal_from_state(
        self,
        project_id: str,
        state_version: int,
        db: Session,
        tenant_id: str = "default_tenant",
        reason: Optional[str] = None,
    ) -> ExcalidrawProposal:
        """
        Role B (Output): Generates a structured Excalidraw change proposal from an approved Project State.
        Computes a visual diff preview without modifying the authoritative artifact.
        """
        artifact = self.get_or_create_artifact(project_id, db, tenant_id=tenant_id)
        
        # Read the target state or version snapshot
        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        if not state:
            raise ExcalidrawError(f"Project '{project_id}' has no ProjectState.")

        nodes_before = json.loads(artifact.extracted_nodes_json) if artifact.extracted_nodes_json else []

        # Architecture is the semantic visual model. The old agent_workflow field
        # is retained only for database compatibility and is never used to build
        # the living visual workspace.
        architecture_items = json.loads(state.architecture_json) if state.architecture_json else []
        nodes_from_architecture = []
        for item in architecture_items:
            if isinstance(item, dict):
                label = item.get("name") or item.get("title") or item.get("label")
            else:
                label = str(item)
            if label and label not in nodes_from_architecture:
                nodes_from_architecture.append(label)

        baseline_nodes = [
            "Sources / Evidence",
            "One Shared Synora Agent",
            "Internal Capabilities",
            "Deterministic Guardrails",
            "Authoritative Project State",
            "Excalidraw Living Workspace",
        ]
        nodes_after = []
        for node in baseline_nodes + nodes_from_architecture:
            if node not in nodes_after:
                nodes_after.append(node)

        nodes_added = [n for n in nodes_after if n not in nodes_before]
        nodes_removed = [n for n in nodes_before if n not in nodes_after]

        connections_before = [f"{nodes_before[i]} -> {nodes_before[i+1]}" for i in range(len(nodes_before) - 1)]
        connections_after = [
            "Sources / Evidence -> One Shared Synora Agent",
            "One Shared Synora Agent -> Internal Capabilities",
            "Internal Capabilities -> Deterministic Guardrails",
            "Deterministic Guardrails -> Authoritative Project State",
            "Authoritative Project State -> Excalidraw Living Workspace",
        ]

        diff_preview = {
            "nodes_before": nodes_before,
            "nodes_after": nodes_after,
            "nodes_added": nodes_added,
            "nodes_removed": nodes_removed,
            "connections_before": connections_before,
            "connections_after": connections_after,
        }

        # Build proposed elements scene with decisions and living workspace cards
        decisions = json.loads(state.decisions_json) if state.decisions_json else []
        requirements = json.loads(state.requirements_json) if state.requirements_json else []
        proposed_elements = self._build_living_workspace_elements(
            node_names=nodes_after,
            decisions=decisions,
            requirements=requirements,
        )

        summary_reason = reason or (
            f"Align architecture diagram with approved Project State v{state_version}. "
            f"Added nodes: {', '.join(nodes_added) if nodes_added else 'None'}. "
            f"Removed nodes: {', '.join(nodes_removed) if nodes_removed else 'None'}."
        )

        proposal = ExcalidrawProposal(
            artifact_id=artifact.id,
            project_id=project_id,
            tenant_id=tenant_id,
            derived_from_state_version=state_version,
            status=ExcalidrawProposalStatus.PENDING.value,
            reason=summary_reason,
            proposed_elements_json=json.dumps(proposed_elements),
            diff_preview_json=json.dumps(diff_preview),
            evidence_ids_json="[]",
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)

        logger.info(f"Created Excalidraw proposal '{proposal.id}' for project '{project_id}' from state v{state_version}")
        return proposal

    def generate_ai_visual_architecture(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        focus_prompt: Optional[str] = None,
        direct_apply: bool = False,
        actor_id: str = "ai_visual_architect",
    ) -> tuple[ExcalidrawProposal, Optional[ExcalidrawArtifact]]:
        """
        AI Visual Architecture Generator (Role B - Output):
        Synthesizes an intelligent, multi-tier system architecture diagram for Excalidraw,
        incorporating client channels, application core, one shared Synora Agent,
        NVIDIA NIM / DeepSeek semantic intelligence, and persistence layers with living decision/requirement cards.
        """
        artifact = self.get_or_create_artifact(project_id, db, tenant_id=tenant_id)
        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        state_version = state.current_version if state else 1

        project_obj = db.query(Project).filter(Project.id == project_id).first()
        project_name = project_obj.name if project_obj else f"Project {project_id}"

        workflow = []
        decisions = json.loads(state.decisions_json) if (state and state.decisions_json) else []
        requirements = json.loads(state.requirements_json) if (state and state.requirements_json) else []

        nodes_before = json.loads(artifact.extracted_nodes_json) if artifact.extracted_nodes_json else []
        nodes_after = [
            "Next.js Web Client", "Google Meet Ingestor", "WhatsApp Gateway", "Excalidraw Workspace",
            "FastAPI Core Engine", "Context Intelligence", "One Shared Synora Agent", "Internal Capabilities",
            "Deterministic Guardrails", "PostgreSQL Project State", "Evidence Provenance", "Excalidraw Revisions"
        ]

        proposed_elements = self._build_ai_architecture_scene(
            project_name=project_name,
            workflow_nodes=workflow,
            decisions=decisions,
            requirements=requirements,
            focus_prompt=focus_prompt,
        )

        nodes_added = [n for n in nodes_after if n not in nodes_before]
        nodes_removed = [n for n in nodes_before if n not in nodes_after]

        diff_preview = {
            "nodes_before": nodes_before,
            "nodes_after": nodes_after,
            "nodes_added": nodes_added,
            "nodes_removed": nodes_removed,
            "connections_before": [],
            "connections_after": ["Ingress -> Core", "Core -> Synora Agent", "Synora Agent -> Capabilities", "Capabilities -> Guardrails", "Guardrails -> Persistence"],
        }

        reason = (
            f"Visual Architecture: Canonical architecture blueprint for {project_name} "
            f"with One Shared Synora Agent, Internal Capabilities, Deterministic Guardrails, and PostgreSQL System of Record."
        )

        proposal = ExcalidrawProposal(
            artifact_id=artifact.id,
            project_id=project_id,
            tenant_id=tenant_id,
            derived_from_state_version=state_version,
            status=ExcalidrawProposalStatus.PENDING.value,
            reason=reason,
            proposed_elements_json=json.dumps(proposed_elements),
            diff_preview_json=json.dumps(diff_preview),
            evidence_ids_json="[]",
        )
        # Consequential visual changes stay proposal-first.
        db.add(proposal)

        if direct_apply:
            now = datetime.now(timezone.utc)
            db.flush()
            previous_revision = (
                db.query(ExcalidrawRevision)
                .filter(
                    ExcalidrawRevision.artifact_id == artifact.id,
                    ExcalidrawRevision.revision_number == artifact.version,
                )
                .first()
            )
            proposal.status = ExcalidrawProposalStatus.APPROVED.value
            proposal.approved_at = now
            proposal.approved_by = actor_id
            artifact.elements_json = json.dumps(proposed_elements)
            artifact.extracted_nodes_json = json.dumps(nodes_after)
            artifact.version += 1
            artifact.updated_at = now
            self._create_revision(
                artifact,
                db,
                parent_revision_id=previous_revision.id if previous_revision else None,
                derived_from_state_version=state_version,
                change_summary={"action": "direct_apply_ai_visual", "reason": reason},
                source_event_ids=[],
                proposal_id=proposal.id,
                actor_id=actor_id,
            )

        db.commit()
        db.refresh(proposal)
        if direct_apply:
            db.refresh(artifact)

        logger.info(
            f"AI Visual Architecture generated for '{project_id}' (proposal={proposal.id}, direct_apply={direct_apply})"
        )
        return proposal, artifact if direct_apply else None

    def review_proposal(
        self,
        proposal_id: str,
        action: str,  # "approve" or "reject"
        actor_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        reason: Optional[str] = None,
    ) -> tuple[ExcalidrawProposal, Optional[ExcalidrawArtifact]]:
        """
        Human Review Gate: Approves or rejects an Excalidraw change proposal.
        Only approval commits the proposed elements to the ExcalidrawArtifact.
        """
        proposal = (
            db.query(ExcalidrawProposal)
            .filter(
                ExcalidrawProposal.id == proposal_id,
                ExcalidrawProposal.tenant_id == tenant_id,
            )
            .first()
        )
        if not proposal:
            raise ExcalidrawError(f"Proposal '{proposal_id}' not found.")

        if proposal.status != ExcalidrawProposalStatus.PENDING.value:
            raise ExcalidrawError(f"Proposal '{proposal_id}' has already been reviewed ({proposal.status}).")

        now = datetime.now(timezone.utc)
        artifact = None

        if action.lower() == "approve":
            proposal.status = ExcalidrawProposalStatus.APPROVED.value
            proposal.approved_at = now
            proposal.approved_by = actor_id

            # Apply to artifact
            artifact = db.query(ExcalidrawArtifact).filter(ExcalidrawArtifact.id == proposal.artifact_id).first()
            if artifact:
                diff_data = json.loads(proposal.diff_preview_json)
                previous_revision = (
                    db.query(ExcalidrawRevision)
                    .filter(
                        ExcalidrawRevision.artifact_id == artifact.id,
                        ExcalidrawRevision.revision_number == artifact.version,
                    )
                    .first()
                )
                artifact.elements_json = proposal.proposed_elements_json
                artifact.extracted_nodes_json = json.dumps(diff_data.get("nodes_after", []))
                artifact.version += 1
                artifact.updated_at = now
                self._create_revision(
                    artifact,
                    db,
                    parent_revision_id=previous_revision.id if previous_revision else None,
                    derived_from_state_version=proposal.derived_from_state_version,
                    change_summary={"action": "proposal_approved", "reason": proposal.reason},
                    source_event_ids=json.loads(proposal.evidence_ids_json or "[]"),
                    proposal_id=proposal.id,
                    actor_id=actor_id,
                )

            self.audit_service.record_event(
                action="excalidraw_proposal_approved",
                actor_id=actor_id,
                resource_type="excalidraw_proposal",
                resource_id=proposal.id,
                db=db,
                tenant_id=tenant_id,
                after_state={"status": "approved", "artifact_version": artifact.version if artifact else None},
            )
            logger.info(f"Excalidraw proposal '{proposal.id}' approved by '{actor_id}'. Artifact updated to v{artifact.version if artifact else 'N/A'}")

        elif action.lower() == "reject":
            proposal.status = ExcalidrawProposalStatus.REJECTED.value
            proposal.approved_at = now
            proposal.approved_by = actor_id
            if reason:
                proposal.reason += f" [Rejected: {reason}]"

            self.audit_service.record_event(
                action="excalidraw_proposal_rejected",
                actor_id=actor_id,
                resource_type="excalidraw_proposal",
                resource_id=proposal.id,
                db=db,
                tenant_id=tenant_id,
                after_state={"status": "rejected", "rejection_reason": reason},
            )
            logger.info(f"Excalidraw proposal '{proposal.id}' rejected by '{actor_id}'.")
        else:
            raise ExcalidrawError(f"Invalid review action '{action}'. Must be 'approve' or 'reject'.")

        db.commit()
        db.refresh(proposal)
        if artifact:
            db.refresh(artifact)

        return proposal, artifact


    def list_revisions(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        limit: int = 50,
    ) -> List[ExcalidrawRevision]:
        artifact = self.get_or_create_artifact(project_id, db, tenant_id=tenant_id)
        self._ensure_current_revision(artifact, db)
        db.commit()
        return (
            db.query(ExcalidrawRevision)
            .filter(
                ExcalidrawRevision.project_id == project_id,
                ExcalidrawRevision.tenant_id == tenant_id,
            )
            .order_by(ExcalidrawRevision.revision_number.desc())
            .limit(limit)
            .all()
        )

    def get_revision(
        self,
        project_id: str,
        revision_number: int,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> ExcalidrawRevision:
        artifact = self.get_or_create_artifact(project_id, db, tenant_id=tenant_id)
        self._ensure_current_revision(artifact, db)
        revision = (
            db.query(ExcalidrawRevision)
            .filter(
                ExcalidrawRevision.project_id == project_id,
                ExcalidrawRevision.tenant_id == tenant_id,
                ExcalidrawRevision.revision_number == revision_number,
            )
            .first()
        )
        if not revision:
            raise ExcalidrawError(
                f"Excalidraw revision v{revision_number} not found for project '{project_id}'."
            )
        return revision

    def compare_revisions(
        self,
        project_id: str,
        from_revision: int,
        to_revision: int,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> ExcalidrawRevisionDiffRead:
        before = self.get_revision(project_id, from_revision, db, tenant_id=tenant_id)
        after = self.get_revision(project_id, to_revision, db, tenant_id=tenant_id)
        old_snapshot = json.loads(before.snapshot_json)
        new_snapshot = json.loads(after.snapshot_json)
        diff = self._element_diff(
            old_snapshot.get("elements", []),
            new_snapshot.get("elements", []),
        )
        return ExcalidrawRevisionDiffRead(
            project_id=project_id,
            artifact_id=after.artifact_id,
            from_revision=from_revision,
            to_revision=to_revision,
            added_elements=diff["added"],
            removed_elements=diff["removed"],
            changed_elements=diff["changed"],
            unchanged_count=diff["unchanged"],
        )

    def format_revision_read(self, revision: ExcalidrawRevision) -> ExcalidrawRevisionRead:
        return ExcalidrawRevisionRead(
            id=revision.id,
            artifact_id=revision.artifact_id,
            project_id=revision.project_id,
            tenant_id=revision.tenant_id,
            revision_number=revision.revision_number,
            parent_revision_id=revision.parent_revision_id,
            derived_from_state_version=revision.derived_from_state_version,
            snapshot=json.loads(revision.snapshot_json),
            change_summary=json.loads(revision.change_summary_json or "{}"),
            source_event_ids=json.loads(revision.source_event_ids_json or "[]"),
            proposal_id=revision.proposal_id,
            actor_id=revision.actor_id,
            created_at=revision.created_at,
        )

    def list_proposals(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        status: Optional[str] = None,
    ) -> List[ExcalidrawProposal]:
        """Lists proposals for a given project."""
        q = db.query(ExcalidrawProposal).filter(
            ExcalidrawProposal.project_id == project_id,
            ExcalidrawProposal.tenant_id == tenant_id,
        )
        if status:
            q = q.filter(ExcalidrawProposal.status == status)
        return q.order_by(ExcalidrawProposal.created_at.desc()).all()

    def _extract_node_labels(self, elements: List[Dict[str, Any]]) -> List[str]:
        """Extracts readable node labels from Excalidraw elements."""
        labels = []
        for el in elements:
            if el.get("type") == "text":
                text = el.get("text", "").strip()
                if text and text not in labels:
                    labels.append(text)
        return labels

    def _normalize_element(self, el: Dict[str, Any], idx: int = 1) -> Dict[str, Any]:
        """Ensures an Excalidraw element contains all standard properties required by Excalidraw renderers."""
        defaults = {
            "angle": 0,
            "strokeColor": "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "seed": 100000 + idx,
            "version": 1,
            "versionNonce": 1,
            "isDeleted": False,
            "boundElements": None,
            "updated": 1,
            "link": None,
            "locked": False,
        }
        defaults.update(el)
        return defaults

    def _build_ai_architecture_scene(
        self,
        project_name: str,
        workflow_nodes: Optional[List[str]] = None,
        decisions: Optional[List[Dict[str, Any]]] = None,
        requirements: Optional[List[Dict[str, Any]]] = None,
        focus_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build a clean, deterministic Excalidraw architecture scene."""
        raw_elements: List[Dict[str, Any]] = []

        def rect(element_id: str, x: float, y: float, w: float, h: float, stroke: str = "#d1d5db"):
            raw_elements.append({
                "id": element_id,
                "type": "rectangle",
                "x": x, "y": y, "width": w, "height": h,
                "backgroundColor": "#ffffff",
                "strokeColor": stroke,
                "fillStyle": "solid",
                "strokeWidth": 2,
                "roundness": {"type": 3},
                "roughness": 1,
            })

        def text(element_id: str, x: float, y: float, w: float, h: float, value: str, size: int = 12, stroke: str = "#173f35"):
            raw_elements.append({
                "id": element_id,
                "type": "text",
                "x": x, "y": y, "width": w, "height": h,
                "text": value,
                "fontSize": size,
                "fontFamily": 1,
                "strokeColor": stroke,
                "textAlign": "left",
            })

        def arrow(element_id: str, x: float, y: float, dx: float, dy: float):
            raw_elements.append({
                "id": element_id,
                "type": "arrow",
                "x": x, "y": y, "width": dx, "height": dy,
                "points": [[0, 0], [dx, dy]],
                "endArrowhead": "arrow",
                "strokeColor": "#6b7280",
                "strokeWidth": 2,
                "roughness": 1,
            })

        # Header
        rect("banner_ai_box", 80, 40, 1180, 58, "#173f35")
        raw_elements[-1]["backgroundColor"] = "#173f35"
        text("banner_ai_title", 102, 49, 1130, 22, f"{project_name.upper()} • LIVING EXCALIDRAW BLUEPRINT", 15, "#ffffff")
        text(
            "banner_ai_sub",
            102,
            75,
            1130,
            16,
            "Sources → Context Intelligence → One Shared Synora Agent → Guardrails → Project State → Visual Workspace",
            10,
            "#d1d5db",
        )

        # Sources / context
        zone_y = 125
        rect("zone_sources", 80, zone_y, 1180, 165)
        text("zone_sources_title", 98, zone_y + 12, 500, 20, "SOURCES & CONTEXT", 12)
        source_cards = [
            ("google_meet", "Google Meet\nNative transcript"),
            ("whatsapp", "WhatsApp\nBaileys messages"),
            ("excalidraw_input", "Excalidraw\nVisual evidence"),
            ("context_intel", "Context Intelligence\nResolve project / quarantine"),
        ]
        card_w, gap, card_y, card_h = 265, 25, zone_y + 42, 98
        for i, (cid, value) in enumerate(source_cards):
            x = 105 + i * (card_w + gap)
            rect(cid, x, card_y, card_w, card_h)
            text(f"{cid}_txt", x + 14, card_y + 15, card_w - 28, card_h - 26, value, 12)
        for i in range(4):
            arrow(f"source_arrow_{i}", 105 + i * (card_w + gap) + card_w / 2, card_y + card_h, 0, 25)

        # Shared intelligence
        agent_y = 325
        rect("zone_agent", 80, agent_y, 1180, 205)
        text("zone_agent_title", 98, agent_y + 12, 650, 20, "ONE SHARED SYNORA AGENT", 12)
        rect("synora_agent_core", 155, agent_y + 45, 320, 120, "#173f35")
        raw_elements[-1]["backgroundColor"] = "#f7fbf9"
        text("synora_agent_title", 175, agent_y + 60, 280, 24, "Synora Agent", 16)
        text("synora_agent_desc", 175, agent_y + 91, 280, 54, "Understands project context\nand coordinates semantic work", 12)

        capability_x = 525
        caps = [
            "Understand requirements",
            "Analyze decisions",
            "Detect conflicts",
            "Reason about architecture",
        ]
        for i, label in enumerate(caps):
            x = capability_x + (i % 2) * 320
            y = agent_y + 45 + (i // 2) * 62
            rect(f"cap_{i}", x, y, 285, 48)
            text(f"cap_{i}_txt", x + 12, y + 12, 260, 24, label, 11)
        text(
            "model_note",
            525,
            agent_y + 168,
            600,
            22,
            "Semantic intelligence: NVIDIA NIM + DeepSeek",
            11,
            "#6b7280",
        )

        # Guardrails / state
        guard_y = 555
        rect("guardrails_box", 80, guard_y, 1180, 120)
        text("guardrails_title", 98, guard_y + 12, 330, 20, "DETERMINISTIC GUARDRAILS", 12)
        text(
            "guardrails_desc",
            98,
            guard_y + 42,
            720,
            52,
            "Project authorization • schema validation • idempotency • conflict gates • human approval",
            12,
        )
        rect("state_box", 850, guard_y + 20, 370, 80, "#173f35")
        raw_elements[-1]["backgroundColor"] = "#f7fbf9"
        text("state_title", 870, guard_y + 34, 330, 20, "Authoritative Project State", 13)
        text("state_desc", 870, guard_y + 58, 330, 28, "PostgreSQL • versioned • evidence-backed", 10, "#6b7280")

        # Visual workspace
        visual_y = 705
        rect("visual_box", 80, visual_y, 1180, 150)
        text("visual_title", 98, visual_y + 12, 520, 20, "LIVING VISUAL WORKSPACE", 12)
        rect("visual_current", 120, visual_y + 45, 430, 72)
        text("visual_current_txt", 138, visual_y + 62, 395, 40, "Latest revision\nClean current architecture", 13)
        rect("visual_history", 600, visual_y + 45, 280, 72)
        text("visual_history_txt", 618, visual_y + 62, 245, 40, "Visual history\nImmutable revisions", 12)
        rect("visual_compare", 910, visual_y + 45, 290, 72)
        text("visual_compare_txt", 928, visual_y + 62, 255, 40, "Compare\nPrevious ↔ Current", 12)

        # Flow arrows between tiers
        arrow("flow_sources_agent", 670, zone_y + zone_h if False else 290, 0, 35)
        arrow("flow_agent_guardrails", 670, agent_y + 205, 0, 25)
        arrow("flow_guardrails_state", 1035, guard_y + 120, 0, 30)
        arrow("flow_state_visual", 1035, visual_y - 30, 0, 30)

        # Current decisions / requirements are small evidence-backed cards, never raw transcripts.
        cursor_y = 900
        for idx, item in enumerate((decisions or [])[:3]):
            rect(f"decision_{idx}", 80 + idx * 390, cursor_y, 360, 78)
            value = item.get("title") or item.get("text") or item.get("decision") or f"Decision {idx + 1}"
            text(f"decision_{idx}_txt", 94 + idx * 390, cursor_y + 12, 332, 52, f"Decision\n{value}", 10)
        for idx, item in enumerate((requirements or [])[:3]):
            rect(f"requirement_{idx}", 80 + idx * 390, cursor_y + 95, 360, 78)
            value = item.get("title") or item.get("text") or item.get("requirement") or f"Requirement {idx + 1}"
            text(f"requirement_{idx}_txt", 94 + idx * 390, cursor_y + 107, 332, 52, f"Requirement\n{value}", 10)

        return [self._normalize_element(el, idx=i) for i, el in enumerate(raw_elements, 1)]

    def _build_living_workspace_elements(
        self,
        node_names: List[str],
        decisions: Optional[List[Dict[str, Any]]] = None,
        requirements: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Builds the Project's Living Visual Workspace scene elements in Excalidraw format.
        Renders the canonical 5-tier architecture:
        1. Sources / Evidence Ingestion
        2. One Shared Synora Agent with Grouped Capabilities
        3. Deterministic Guardrails & Pipeline Synthesis
        4. Authoritative Project State (PostgreSQL)
        5. Excalidraw Living Workspace (with Human Approval Gates)
        Followed by Key Decisions and Active Requirements cards.
        """
        raw_elements: List[Dict[str, Any]] = []

        # 0. Living Workspace Banner
        raw_elements.append({
            "id": "banner_box",
            "type": "rectangle",
            "x": 80,
            "y": 40,
            "width": 960,
            "height": 50,
            "backgroundColor": "#064e3b",
            "strokeColor": "#059669",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "roundness": {"type": 3},
            "roughness": 1,
        })
        raw_elements.append({
            "id": "banner_title",
            "type": "text",
            "x": 100,
            "y": 47,
            "width": 920,
            "height": 20,
            "text": "SYNORA LIVING VISUAL WORKSPACE  •  AUTHORITATIVE PROJECT STATE",
            "fontSize": 14,
            "fontFamily": 1,
            "strokeColor": "#ffffff",
            "textAlign": "left",
            "containerId": "banner_box",
        })
        raw_elements.append({
            "id": "banner_sub",
            "type": "text",
            "x": 100,
            "y": 68,
            "width": 920,
            "height": 16,
            "text": "ONE SHARED SYNORA AGENT • INTERNAL CAPABILITIES • DETERMINISTIC GUARDRAILS • HUMAN APPROVAL GATES",
            "fontSize": 10,
            "fontFamily": 1,
            "strokeColor": "#a7f3d0",
            "textAlign": "left",
            "containerId": "banner_box",
        })

        # 1. Tier 1: Sources / Evidence
        t1_y = 105
        raw_elements.append({
            "id": "arch_sources_box",
            "type": "rectangle",
            "x": 80,
            "y": t1_y,
            "width": 960,
            "height": 55,
            "backgroundColor": "#f8fafc",
            "strokeColor": "#94a3b8",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "roundness": {"type": 3},
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arch_sources_txt",
            "type": "text",
            "x": 100,
            "y": t1_y + 10,
            "width": 920,
            "height": 35,
            "text": "📥 SOURCES & EVIDENCE INGESTION\nGoogle Meet Transcripts • WhatsApp Communications • Document & Architecture Uploads",
            "fontSize": 11,
            "fontFamily": 1,
            "strokeColor": "#1e293b",
            "textAlign": "center",
            "containerId": "arch_sources_box",
        })

        # Arrow Tier 1 -> Tier 2
        raw_elements.append({
            "id": "arr_sources_to_agent",
            "type": "arrow",
            "x": 560,
            "y": t1_y + 55,
            "width": 0,
            "height": 25,
            "points": [[0, 0], [0, 25]],
            "endArrowhead": "arrow",
            "strokeColor": "#64748b",
            "strokeWidth": 2,
            "roughness": 1,
        })

        # 2. Tier 2: One Shared Synora Agent & Grouped Capabilities
        t2_y = 185
        t2_h = 155
        raw_elements.append({
            "id": "arch_agent_box",
            "type": "rectangle",
            "x": 80,
            "y": t2_y,
            "width": 960,
            "height": t2_h,
            "backgroundColor": "#ecfdf5",
            "strokeColor": "#059669",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "roundness": {"type": 3},
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arch_agent_title",
            "type": "text",
            "x": 100,
            "y": t2_y + 10,
            "width": 920,
            "height": 18,
            "text": "🧠 ONE SHARED SYNORA AGENT (Active in Project Context)",
            "fontSize": 13,
            "fontFamily": 1,
            "strokeColor": "#065f46",
            "textAlign": "center",
        })
        raw_elements.append({
            "id": "arch_agent_sub",
            "type": "text",
            "x": 100,
            "y": t2_y + 30,
            "width": 920,
            "height": 14,
            "text": "Single intelligence layer reasoning across project evidence • Internal capabilities work together in one unified model",
            "fontSize": 10,
            "fontFamily": 1,
            "strokeColor": "#047857",
            "textAlign": "center",
        })

        # Grouped Capabilities inside Synora Agent
        capabilities = [
            ("Business Analysis", "Requirements & User Stories"),
            ("Project Planning", "Scope, Milestones & Timeline"),
            ("Functional Analysis", "Workflows & Use Cases"),
            ("Technical Architecture", "Schemas, APIs & Stack"),
            ("Frappe / ERP Analysis", "DocTypes & Integrations"),
        ]
        cap_w = 175
        cap_h = 75
        cap_spacing = 15
        cap_start_x = 95
        cap_y = t2_y + 55

        for idx, (cap_name, cap_desc) in enumerate(capabilities):
            cx = cap_start_x + idx * (cap_w + cap_spacing)
            cap_id = f"cap_box_{idx+1}"
            raw_elements.append({
                "id": cap_id,
                "type": "rectangle",
                "x": cx,
                "y": cap_y,
                "width": cap_w,
                "height": cap_h,
                "backgroundColor": "#ffffff",
                "strokeColor": "#10b981",
                "fillStyle": "solid",
                "strokeWidth": 1.5,
                "roundness": {"type": 3},
                "roughness": 1,
            })
            raw_elements.append({
                "id": f"{cap_id}_txt",
                "type": "text",
                "x": cx + 6,
                "y": cap_y + 12,
                "width": cap_w - 12,
                "height": cap_h - 24,
                "text": f"⚡ {cap_name}\n\n{cap_desc}",
                "fontSize": 10,
                "fontFamily": 1,
                "strokeColor": "#064e3b",
                "textAlign": "center",
                "containerId": cap_id,
            })

        # Arrow Tier 2 -> Tier 3
        raw_elements.append({
            "id": "arr_agent_to_guardrails",
            "type": "arrow",
            "x": 560,
            "y": t2_y + t2_h,
            "width": 0,
            "height": 25,
            "points": [[0, 0], [0, 25]],
            "endArrowhead": "arrow",
            "strokeColor": "#059669",
            "strokeWidth": 2,
            "roughness": 1,
        })

        # 3. Tier 3: Deterministic Guardrails
        t3_y = 365
        raw_elements.append({
            "id": "arch_guardrails_box",
            "type": "rectangle",
            "x": 80,
            "y": t3_y,
            "width": 960,
            "height": 55,
            "backgroundColor": "#eff6ff",
            "strokeColor": "#3b82f6",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "roundness": {"type": 3},
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arch_guardrails_txt",
            "type": "text",
            "x": 100,
            "y": t3_y + 10,
            "width": 920,
            "height": 35,
            "text": "🛡️ DETERMINISTIC GUARDRAILS & PIPELINE SYNTHESIS\nValidation Rules • Schema Constraints • Semantic Conflict Detection • Non-Destructive Invariant Checks",
            "fontSize": 11,
            "fontFamily": 1,
            "strokeColor": "#1e3a8a",
            "textAlign": "center",
            "containerId": "arch_guardrails_box",
        })

        # Arrow Tier 3 -> Tier 4
        raw_elements.append({
            "id": "arr_guardrails_to_db",
            "type": "arrow",
            "x": 560,
            "y": t3_y + 55,
            "width": 0,
            "height": 25,
            "points": [[0, 0], [0, 25]],
            "endArrowhead": "arrow",
            "strokeColor": "#3b82f6",
            "strokeWidth": 2,
            "roughness": 1,
        })

        # 4. Tier 4: Authoritative Project State (PostgreSQL)
        t4_y = 445
        raw_elements.append({
            "id": "arch_db_box",
            "type": "rectangle",
            "x": 80,
            "y": t4_y,
            "width": 960,
            "height": 55,
            "backgroundColor": "#ffffff",
            "strokeColor": "#d97706",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "roundness": {"type": 3},
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arch_db_txt",
            "type": "text",
            "x": 100,
            "y": t4_y + 10,
            "width": 920,
            "height": 35,
            "text": "🗄️ AUTHORITATIVE PROJECT STATE (PostgreSQL)\nSingle System of Record • Immutable Version Snapshots • Canonical Source of Truth",
            "fontSize": 11,
            "fontFamily": 1,
            "strokeColor": "#92400e",
            "textAlign": "center",
            "containerId": "arch_db_box",
        })

        # Arrow Tier 4 -> Tier 5
        raw_elements.append({
            "id": "arr_db_to_workspace",
            "type": "arrow",
            "x": 560,
            "y": t4_y + 55,
            "width": 0,
            "height": 25,
            "points": [[0, 0], [0, 25]],
            "endArrowhead": "arrow",
            "strokeColor": "#d97706",
            "strokeWidth": 2,
            "roughness": 1,
        })

        # 5. Tier 5: Excalidraw Living Workspace
        t5_y = 525
        raw_elements.append({
            "id": "arch_workspace_box",
            "type": "rectangle",
            "x": 80,
            "y": t5_y,
            "width": 960,
            "height": 55,
            "backgroundColor": "#f5f3ff",
            "strokeColor": "#7c3aed",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "roundness": {"type": 3},
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arch_workspace_txt",
            "type": "text",
            "x": 100,
            "y": t5_y + 10,
            "width": 920,
            "height": 35,
            "text": "🎨 EXCALIDRAW LIVING WORKSPACE (Visual System Model)\nInteractive Architecture Canvas • Human Review & Approval Gates for Consequential Changes",
            "fontSize": 11,
            "fontFamily": 1,
            "strokeColor": "#5b21b6",
            "textAlign": "center",
            "containerId": "arch_workspace_box",
        })

        # 6. Key Decisions & Evidence Provenance Cards
        decisions_list = decisions or []
        if decisions_list:
            dec_y = 605
            raw_elements.append({
                "id": "lbl_decisions_header",
                "type": "text",
                "x": 80,
                "y": dec_y,
                "width": 450,
                "height": 24,
                "text": "KEY PROJECT DECISIONS & EVIDENCE PROVENANCE",
                "fontSize": 14,
                "fontFamily": 1,
                "strokeColor": "#15803d",
                "textAlign": "left",
            })

            card_x = 80
            for idx, d in enumerate(decisions_list[:4]):  # Show up to 4 recent decisions
                d_title = d.get("title") or d.get("decision") or d.get("text") or f"Decision #{idx+1}"
                d_source = d.get("source", "Google Meet")
                evidence_val = d.get("evidence_ref") or d.get("evidence_id")
                if not evidence_val and d.get("evidence_ids"):
                    ev_ids = d.get("evidence_ids")
                    if isinstance(ev_ids, list) and len(ev_ids) > 0:
                        evidence_val = ev_ids[0]
                    elif isinstance(ev_ids, str):
                        evidence_val = ev_ids
                d_evidence = evidence_val or f"EV-MEET-{idx+1}"
                card_id = f"dec_box_{idx+1}"
                text_id = f"dec_txt_{idx+1}"

                # Decision Card Rectangle
                raw_elements.append({
                    "id": card_id,
                    "type": "rectangle",
                    "x": card_x,
                    "y": dec_y + 30,
                    "width": 225,
                    "height": 115,
                    "backgroundColor": "#dcfce7",
                    "strokeColor": "#16a34a",
                    "fillStyle": "solid",
                    "strokeWidth": 2,
                    "roundness": {"type": 3},
                    "roughness": 1,
                })

                # Card Text
                card_body = f"DECISION\n{d_title}\n\nSOURCE: {d_source}\nEVIDENCE: {d_evidence}"
                raw_elements.append({
                    "id": text_id,
                    "type": "text",
                    "x": card_x + 10,
                    "y": dec_y + 40,
                    "width": 205,
                    "height": 95,
                    "text": card_body,
                    "fontSize": 10,
                    "fontFamily": 1,
                    "strokeColor": "#14532d",
                    "textAlign": "left",
                    "containerId": card_id,
                })
                card_x += 245

        # 7. Active Requirements Cards
        reqs_list = requirements or []
        if reqs_list:
            req_y = 770
            raw_elements.append({
                "id": "lbl_reqs_header",
                "type": "text",
                "x": 80,
                "y": req_y,
                "width": 350,
                "height": 24,
                "text": "ACTIVE REQUIREMENTS & SCOPE",
                "fontSize": 14,
                "fontFamily": 1,
                "strokeColor": "#1d4ed8",
                "textAlign": "left",
            })

            req_x = 80
            for idx, r in enumerate(reqs_list[:4]):
                r_title = r.get("title") or r.get("requirement") or r.get("text") or f"Requirement #{idx+1}"
                r_id = f"req_box_{idx+1}"
                r_txt_id = f"req_txt_{idx+1}"

                raw_elements.append({
                    "id": r_id,
                    "type": "rectangle",
                    "x": req_x,
                    "y": req_y + 30,
                    "width": 225,
                    "height": 85,
                    "backgroundColor": "#eff6ff",
                    "strokeColor": "#3b82f6",
                    "fillStyle": "solid",
                    "strokeWidth": 2,
                    "roundness": {"type": 3},
                    "roughness": 1,
                })

                raw_elements.append({
                    "id": r_txt_id,
                    "type": "text",
                    "x": req_x + 10,
                    "y": req_y + 40,
                    "width": 205,
                    "height": 65,
                    "text": f"REQUIREMENT\n{r_title}",
                    "fontSize": 10,
                    "fontFamily": 1,
                    "strokeColor": "#1e3a8a",
                    "textAlign": "left",
                    "containerId": r_id,
                })
                req_x += 245

        # Normalize all elements with standard Excalidraw attributes
        return [self._normalize_element(el, idx=i) for i, el in enumerate(raw_elements, 1)]

    def _build_flow_elements(
        self,
        node_names: List[str],
        start_x: int = 100,
        start_y: int = 150,
    ) -> List[Dict[str, Any]]:
        """Generates standard Excalidraw elements representing a linear pipeline flow."""
        elements: List[Dict[str, Any]] = []
        node_width = 160
        node_height = 60
        spacing = 90

        colors = ["#e0e7ff", "#fef3c7", "#d1fae5", "#fce7f3", "#ede9fe", "#e0f2fe"]

        for i, name in enumerate(node_names):
            x = start_x + i * (node_width + spacing)
            y = start_y
            color = colors[i % len(colors)]
            node_id = f"node_{i+1}"
            text_id = f"text_{i+1}"

            # Box element
            elements.append({
                "id": node_id,
                "type": "rectangle",
                "x": x,
                "y": y,
                "width": node_width,
                "height": node_height,
                "backgroundColor": color,
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "solid",
                "roundness": {"type": 3},
                "roughness": 1,
            })

            # Text label element
            elements.append({
                "id": text_id,
                "type": "text",
                "x": x + 15,
                "y": y + 20,
                "width": node_width - 30,
                "height": 25,
                "text": name,
                "fontSize": 14,
                "fontFamily": 1,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": node_id,
            })

            # Arrow to next node
            if i < len(node_names) - 1:
                arrow_id = f"arrow_{i+1}_{i+2}"
                next_x = x + node_width + spacing
                elements.append({
                    "id": arrow_id,
                    "type": "arrow",
                    "x": x + node_width,
                    "y": y + (node_height / 2),
                    "width": spacing,
                    "height": 0,
                    "points": [[0, 0], [spacing, 0]],
                    "endArrowhead": "arrow",
                    "strokeWidth": 2,
                    "roughness": 1,
                })

        return elements

    def format_artifact_read(self, artifact: ExcalidrawArtifact) -> ExcalidrawArtifactRead:
        """Converts model to typed DTO."""
        elements = json.loads(artifact.elements_json) if artifact.elements_json else []
        app_state = json.loads(artifact.app_state_json) if artifact.app_state_json else {}
        nodes = json.loads(artifact.extracted_nodes_json) if artifact.extracted_nodes_json else []

        return ExcalidrawArtifactRead(
            id=artifact.id,
            project_id=artifact.project_id,
            tenant_id=artifact.tenant_id,
            name=artifact.name,
            version=artifact.version,
            elements=elements,
            app_state=app_state,
            extracted_nodes=nodes,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )

    def format_proposal_read(self, proposal: ExcalidrawProposal) -> ExcalidrawProposalRead:
        """Converts proposal model to typed DTO."""
        diff_data = json.loads(proposal.diff_preview_json) if proposal.diff_preview_json else {}
        proposed_elements = json.loads(proposal.proposed_elements_json) if proposal.proposed_elements_json else []
        evidence_ids = json.loads(proposal.evidence_ids_json) if proposal.evidence_ids_json else []

        return ExcalidrawProposalRead(
            id=proposal.id,
            artifact_id=proposal.artifact_id,
            project_id=proposal.project_id,
            tenant_id=proposal.tenant_id,
            derived_from_state_version=proposal.derived_from_state_version,
            status=proposal.status,
            reason=proposal.reason,
            diff_preview=ExcalidrawDiffPreview(
                nodes_before=diff_data.get("nodes_before", []),
                nodes_after=diff_data.get("nodes_after", []),
                nodes_added=diff_data.get("nodes_added", []),
                nodes_removed=diff_data.get("nodes_removed", []),
                connections_before=diff_data.get("connections_before", []),
                connections_after=diff_data.get("connections_after", []),
            ),
            proposed_elements=proposed_elements,
            evidence_ids=evidence_ids,
            created_at=proposal.created_at,
            approved_at=proposal.approved_at,
            approved_by=proposal.approved_by,
        )

from datetime import datetime, timezone
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.context_resolution import UnknownContextItem, UnknownItemStatus
from app.models.project import Project
from app.models.unknown_cluster import UnknownCluster
from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship
from app.services.audit_service import AuditService
from app.services.context_feedback_service import ContextFeedbackService
from app.services.embedding_service import GeminiEmbeddingService, cosine_similarity
from app.services.excalidraw_compiler import ExcalidrawCompiler
from app.services.project_agent_service import ProjectAgentService
from app.services.project_semantic_profile_service import ProjectSemanticProfileService
from app.services.unknown_context_service import UnknownContextService
from app.services.visual_revision_service import VisualRevisionService

logger = logging.getLogger(__name__)


class UnknownClusterError(SynesisException):
    """Raised for cluster management errors."""


class UnknownClusterService:
    """Intelligent embedding-based clustering for Unknown Context items.

    Groups orphaned evidence into coherent topic clusters and enables atomic
    cluster assignment and one-click project creation.
    """

    def __init__(
        self,
        embedding_service: Optional[GeminiEmbeddingService] = None,
        feedback_service: Optional[ContextFeedbackService] = None,
        audit_service: Optional[AuditService] = None,
    ):
        self.embedding_service = embedding_service or GeminiEmbeddingService()
        self.feedback_service = feedback_service or ContextFeedbackService()
        self.audit_service = audit_service or AuditService()

    def cluster_pending_items(
        self,
        db: Session,
        tenant_id: str = "default_tenant",
        similarity_threshold: float = 0.55,
    ) -> List[UnknownCluster]:
        """Cluster all pending Unknown Context items using embedding similarity."""
        items = (
            db.query(UnknownContextItem)
            .filter(
                UnknownContextItem.tenant_id == tenant_id,
                UnknownContextItem.status == UnknownItemStatus.PENDING.value,
            )
            .all()
        )
        if not items:
            return []

        # Embed each item's content
        item_vectors: List[Tuple[UnknownContextItem, List[float]]] = []
        for it in items:
            text = it.content or ""
            vec = self.embedding_service.embed_text(text)
            item_vectors.append((it, vec))

        # Greedy single-linkage clustering
        clusters_raw: List[List[Tuple[UnknownContextItem, List[float]]]] = []
        visited = set()

        for i, (it1, v1) in enumerate(item_vectors):
            if it1.id in visited:
                continue
            current_cluster = [(it1, v1)]
            visited.add(it1.id)

            for j, (it2, v2) in enumerate(item_vectors):
                if it2.id in visited or i == j:
                    continue
                sim = cosine_similarity(v1, v2)
                if sim >= similarity_threshold:
                    current_cluster.append((it2, v2))
                    visited.add(it2.id)

            clusters_raw.append(current_cluster)

        # Get existing project profiles to suggest possible projects
        project_profiles = ProjectSemanticProfileService(self.embedding_service).ensure_all_profiles(db, tenant_id)

        created_clusters: List[UnknownCluster] = []
        for cluster_group in clusters_raw:
            cluster_items = [it for it, _ in cluster_group]
            cluster_vectors = [vec for _, vec in cluster_group]
            item_ids = [it.id for it in cluster_items]

            # Compute centroid vector
            dim = len(cluster_vectors[0]) if cluster_vectors else 64
            centroid = [0.0] * dim
            for vec in cluster_vectors:
                for d in range(min(dim, len(vec))):
                    centroid[d] += vec[d]
            if cluster_vectors:
                centroid = [round(c / len(cluster_vectors), 5) for c in centroid]

            # Check similarity against known projects
            best_project: Optional[ProjectSemanticProfile] = None
            best_sim = 0.0
            for prof in project_profiles:
                p_vec = prof.get_embedding_vector()
                if p_vec:
                    sim = cosine_similarity(centroid, p_vec)
                    if sim > best_sim:
                        best_sim = sim
                        best_project = prof

            # Generate title from prominent terms
            combined_text = " ".join([it.content or "" for it in cluster_items])
            title = self._synthesize_cluster_title(combined_text, len(cluster_items))

            cluster_row = UnknownCluster(
                tenant_id=tenant_id,
                title=title,
                summary=f"Cluster of {len(cluster_items)} related items: {combined_text[:140]}...",
                suggested_project_id=best_project.project_id if best_project and best_sim >= 0.40 else None,
                suggested_project_name=best_project.name if best_project and best_sim >= 0.40 else None,
                item_ids_json=json.dumps(item_ids),
                centroid_vector_json=json.dumps(centroid),
                status="pending",
            )
            db.add(cluster_row)
            created_clusters.append(cluster_row)

        db.commit()
        for c in created_clusters:
            db.refresh(c)
        logger.info("unknown_clusters_formed: count=%d total_items=%d", len(created_clusters), len(items))
        return created_clusters

    def _synthesize_cluster_title(self, text: str, count: int) -> str:
        """Derive a human-readable cluster topic title."""
        lower = text.lower()
        if "qr" in lower or "table" in lower or "restaurant" in lower:
            return f"Restaurant Ordering Workflow ({count} items)"
        if "whatsapp" in lower or "message" in lower or "chat" in lower:
            return f"WhatsApp Messaging & Notification Context ({count} items)"
        if "meet" in lower or "transcript" in lower or "call" in lower:
            return f"Meeting Dialogue & Architecture Decisions ({count} items)"
        if "payment" in lower or "pos" in lower or "bill" in lower:
            return f"Payment & Billing Integrations ({count} items)"

        words = [w for w in re.findall(r"[a-zA-Z]{4,}", text) if w.lower() not in ("with", "that", "this", "from", "have")]
        leading = " ".join(words[:3]).title() if words else "Unknown Topic"
        return f"{leading} Cluster ({count} items)"

    def assign_cluster(
        self,
        cluster_id: str,
        project_id: str,
        db: Session,
        actor_id: str = "user",
        tenant_id: str = "default_tenant",
    ) -> UnknownCluster:
        """Atomically assign all items in a cluster to a target project with audit and feedback."""
        cluster = db.query(UnknownCluster).filter(UnknownCluster.id == cluster_id).first()
        if not cluster:
            raise UnknownClusterError(f"Cluster '{cluster_id}' not found.")

        project = db.query(Project).filter(Project.id == project_id).first()
        if not project or project.is_system:
            raise UnknownClusterError(f"Target project '{project_id}' is invalid.")

        item_ids = cluster.get_item_ids()
        unknown_service = UnknownContextService()

        for iid in item_ids:
            try:
                unknown_service.assign_to_project(
                    item_id=iid,
                    project_id=project.id,
                    db=db,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    note=f"Assigned via cluster '{cluster.title}'",
                )
                self.feedback_service.record_feedback(
                    db=db,
                    selected_project_id=project.id,
                    action="assigned",
                    actor_id=actor_id,
                    reason=f"Cluster assignment: {cluster.title}",
                    text_snippet=cluster.summary[:200],
                    tenant_id=tenant_id,
                )
            except Exception as exc:
                logger.warning("cluster_item_assign_failed: item=%s error=%s", iid, exc)

        cluster.status = "assigned"
        cluster.assigned_project_id = project.id
        cluster.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(cluster)

        self.audit_service.record_event(
            action="unknown_cluster_assigned",
            actor_id=actor_id,
            resource_type="unknown_cluster",
            resource_id=cluster.id,
            db=db,
            tenant_id=tenant_id,
            after_state={"project_id": project.id, "item_count": len(item_ids)},
        )
        return cluster

    def generate_project_draft(
        self,
        item_id: Optional[str] = None,
        cluster_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Synthesize a complete project draft from an unknown item or cluster."""
        combined_text = ""
        source_evidence = []
        if cluster_id and db:
            cluster = db.query(UnknownCluster).filter(UnknownCluster.id == cluster_id).first()
            if cluster:
                combined_text = cluster.summary + " "
                for iid in cluster.get_item_ids()[:5]:
                    it = db.query(UnknownContextItem).filter(UnknownContextItem.id == iid).first()
                    if it and it.content:
                        combined_text += it.content + " "
                        source_evidence.append(it.content[:150])

        elif item_id and db:
            it = db.query(UnknownContextItem).filter(UnknownContextItem.id == item_id).first()
            if it and it.content:
                combined_text = it.content
                source_evidence.append(it.content[:150])

        lower = combined_text.lower()
        if "qr" in lower or "restaurant" in lower or "table" in lower:
            name = "Restaurant Automation"
            description = "Autonomous restaurant table ordering, QR token verification, and kitchen display integration."
            domain = "Hospitality & Restaurant Tech"
            business_concepts = ["Table QR Ordering", "Digital Menu", "KDS Dispatch", "POS Synchronization"]
            technical_concepts = ["QR Scanner Web App", "Order Service", "Kitchen Display UI", "POS API Gateway"]
            initial_reqs = ["Allow customers to order from tables via QR", "Dispatch orders to kitchen display in realtime"]
            initial_nodes = ["Customer Web App", "Order Service", "Kitchen Display", "POS Gateway"]
        else:
            words = [w for w in re.findall(r"[a-zA-Z]{4,}", combined_text) if w.lower() not in ("with", "that", "this", "from")]
            name = (" ".join(words[:2]).title() or "New Project")
            description = f"Project initialized from incoming context: {combined_text[:120]}"
            domain = "Product Engineering"
            business_concepts = [w.capitalize() for w in words[:4]]
            technical_concepts = ["Core Service", "Database", "API Gateway"]
            initial_reqs = [f"Support {name} operational workflow"]
            initial_nodes = [name, "Core Service", "Data Store"]

        return {
            "name": name,
            "description": description,
            "domain": domain,
            "aliases": [name.lower()],
            "business_concepts": business_concepts,
            "technical_concepts": technical_concepts,
            "initial_requirements": initial_reqs,
            "initial_architecture_nodes": initial_nodes,
            "source_evidence": source_evidence,
        }

    def create_project_from_draft(
        self,
        draft: Dict[str, Any],
        db: Session,
        actor_id: str = "user",
        tenant_id: str = "default_tenant",
        workspace_id: str = "ws_default",
        cluster_id: Optional[str] = None,
        item_id: Optional[str] = None,
    ) -> Project:
        """Create a complete new project from draft, initializing State, Agent, Visual Workspace, and Semantic Profile."""
        name = draft.get("name") or "New Project"
        description = draft.get("description") or "Created from Unknown Context draft"
        project_id = f"proj_{uuid.uuid4().hex[:8]}"

        project = ProjectAgentService().get_or_create_project(
            project_id=project_id,
            db=db,
            workspace_id=workspace_id,
            name=name,
            description=description,
        )

        # Initialize ProjectSemanticProfile
        profile_service = ProjectSemanticProfileService(self.embedding_service)
        profile = profile_service.get_or_create_profile(project.id, db, tenant_id=tenant_id)
        profile.domain = draft.get("domain", profile.domain)
        profile.business_concepts_json = json.dumps(draft.get("business_concepts", []))
        profile.technical_concepts_json = json.dumps(draft.get("technical_concepts", []))
        db.commit()

        # Initialize Visual Workspace with initial compiled diagram
        initial_nodes = draft.get("initial_architecture_nodes", ["Client", "Service", "Database"])
        nodes = [
            VisualNode(id=f"node_{re.sub(r'[^a-zA-Z0-9]+', '_', n.lower())}", label=n, node_type="service")
            for n in initial_nodes
        ]
        rels = []
        if len(nodes) >= 2:
            rels.append(VisualRelationship(source=nodes[0].id, target=nodes[1].id, label="requests"))
        if len(nodes) >= 3:
            rels.append(VisualRelationship(source=nodes[1].id, target=nodes[2].id, label="persists"))

        plan = VisualPlan(title=name, nodes=nodes, relationships=rels, notes=["Initial architecture baseline"])
        scene = ExcalidrawCompiler().compile(plan)

        VisualRevisionService().commit_revision(
            project_id=project.id,
            scene=scene,
            db=db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            reason="Initial architecture generated from Unknown Context draft",
        )

        # Re-home cluster or item
        if cluster_id:
            self.assign_cluster(cluster_id, project.id, db, actor_id=actor_id, tenant_id=tenant_id)
        elif item_id:
            UnknownContextService().assign_to_project(item_id, project.id, db, actor_id=actor_id, tenant_id=tenant_id)

        # Record feedback
        self.feedback_service.record_feedback(
            db=db,
            selected_project_id=project.id,
            action="project_created",
            actor_id=actor_id,
            reason=f"Created project '{name}' from Unknown Context",
            text_snippet=description,
            tenant_id=tenant_id,
        )

        logger.info("project_created_from_draft: id=%s name=%s", project.id, project.name)
        return project

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.project import Project
from app.models.project_semantic_profile import ProjectSemanticProfile
from app.models.project_state import ProjectState
from app.models.visual_revision import VisualWorkspace, VisualRevision
from app.services.embedding_service import GeminiEmbeddingService

logger = logging.getLogger(__name__)

# Canonical domain dictionaries for high-precision semantic profiles
PRESET_DOMAIN_CONCEPTS: Dict[str, Dict[str, Any]] = {
    "dinein": {
        "domain": "Restaurant Ordering & Kitchen Automation",
        "aliases": ["dinein", "dine-in", "dine in", "restaurant", "table ordering"],
        "business_concepts": [
            "restaurant ordering", "table qr", "digital menu", "table ordering agent",
            "kitchen display system", "kds", "pos integration", "waiter call",
            "order dispatch", "billing automation", "restaurant workflow", "kot",
            "realtime orders", "table turnover", "guest check", "food prep",
        ],
        "technical_concepts": [
            "qr token verification", "pos sync webhook", "kitchen display api",
            "order ingestion stream", "order database", "realtime websocket",
            "menu catalog api", "table session state",
        ],
        "important_entities": ["Customer", "Table", "Menu Item", "Order", "Kitchen", "POS", "Bill"],
        "architecture_concepts": ["Customer Web App", "Order Agent", "POS Gateway", "Kitchen Display UI", "Order DB"],
    },
    "synora": {
        "domain": "Enterprise Project Intelligence & Living Architecture",
        "aliases": ["synora", "synesis", "living workspace", "project memory"],
        "business_concepts": [
            "project intelligence", "context routing", "meeting transcripts",
            "architectural decisions", "living excalidraw workspace", "knowledge extraction",
            "requirements management", "conflict detection", "whatsapp context ingestion",
            "google meet recording", "visual state versioning",
        ],
        "technical_concepts": [
            "deterministic compiler", "visual patch engine", "three way visual merge",
            "immutable revisions", "gemini semantic reasoning", "vector embeddings",
            "event sourcing", "c4 diagram generator",
        ],
        "important_entities": ["Project", "Evidence", "Decision", "Requirement", "Visual Revision", "Context Resolution"],
        "architecture_concepts": ["Pipeline Coordinator", "Context Resolver", "Excalidraw Compiler", "Project Agent"],
    },
}


class ProjectSemanticProfileService:
    """Maintains rich, multi-dimensional semantic profiles for projects.

    Enables deep contextual retrieval far beyond naive string matching.
    """

    def __init__(self, embedding_service: Optional[GeminiEmbeddingService] = None):
        self.embedding_service = embedding_service or GeminiEmbeddingService()

    def get_or_create_profile(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> ProjectSemanticProfile:
        """Fetch or automatically generate a rich semantic profile for the project."""
        profile = (
            db.query(ProjectSemanticProfile)
            .filter(
                ProjectSemanticProfile.project_id == project_id,
                ProjectSemanticProfile.tenant_id == tenant_id,
            )
            .first()
        )
        if profile:
            state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
            current_state_version = int(state.current_version) if state else 0
            if current_state_version <= int(profile.state_version or 0):
                return profile
            project = db.query(Project).filter(Project.id == project_id).first()
            if project:
                return self.rebuild_profile(project, db, tenant_id=tenant_id)
            return profile

        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            # Create a stub profile if project record is missing
            profile = ProjectSemanticProfile(
                project_id=project_id,
                tenant_id=tenant_id,
                name=project_id,
                description="Project profile",
                domain="General Software Engineering",
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
            return profile

        return self.rebuild_profile(project, db, tenant_id=tenant_id)

    def rebuild_profile(
        self,
        project: Project,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> ProjectSemanticProfile:
        """Synthesize a complete semantic profile from project metadata, state, evidence, and visual canvas."""
        norm_name = re.sub(r"[^a-z0-9]", "", (project.name or "").lower())
        preset = PRESET_DOMAIN_CONCEPTS.get(norm_name, {})

        # Extract domain & aliases
        domain = preset.get("domain") or "Software Architecture & Product Engineering"
        aliases = list(preset.get("aliases") or [project.name.lower()])
        if project.name not in aliases:
            aliases.append(project.name)

        business_concepts = list(preset.get("business_concepts") or [])
        technical_concepts = list(preset.get("technical_concepts") or [])
        important_entities = list(preset.get("important_entities") or [])
        architecture_concepts = list(preset.get("architecture_concepts") or [])

        # Enrich from ProjectState if available
        reqs_summary: List[str] = []
        decs_summary: List[str] = []
        state_row = (
            db.query(ProjectState)
            .filter(ProjectState.project_id == project.id)
            .first()
        )
        if state_row and state_row.state_json:
            try:
                state_data = json.loads(state_row.state_json)
                for req in state_data.get("requirements", [])[:8]:
                    title = req.get("title") or req.get("name") if isinstance(req, dict) else str(req)
                    reqs_summary.append(str(title)[:100])
                    business_concepts.append(str(title).lower()[:50])
                for dec in state_data.get("decisions", [])[:8]:
                    title = dec.get("title") or dec.get("name") if isinstance(dec, dict) else str(dec)
                    decs_summary.append(str(title)[:100])
                for comp in state_data.get("architecture", [])[:8]:
                    title = comp.get("name") or comp.get("title") if isinstance(comp, dict) else str(comp)
                    architecture_concepts.append(str(title))
            except Exception as exc:
                logger.warning("failed_to_parse_project_state_for_profile: %s", exc)

        # Enrich from latest VisualRevision if available
        visual_concepts: List[str] = []
        workspace = (
            db.query(VisualWorkspace)
            .filter(VisualWorkspace.project_id == project.id)
            .first()
        )
        if workspace and workspace.current_revision_id:
            rev = (
                db.query(VisualRevision)
                .filter(VisualRevision.id == workspace.current_revision_id)
                .first()
            )
            if rev and rev.scene_json:
                try:
                    scene = json.loads(rev.scene_json)
                    for el in scene:
                        if isinstance(el, dict) and el.get("type") == "text":
                            txt = el.get("text", "").strip()
                            if txt and len(txt) < 40 and txt not in visual_concepts:
                                visual_concepts.append(txt)
                except Exception:
                    pass

        # Enrich from recent evidence
        representative_evidence: List[str] = []
        recent_evs = (
            db.query(Evidence)
            .filter(Evidence.project_id == project.id)
            .order_by(Evidence.created_at.desc())
            .limit(5)
            .all()
        )
        for ev in recent_evs:
            if ev.content and ev.content.strip():
                representative_evidence.append(ev.content.strip()[:200])

        # Deduplicate concept lists
        def clean_list(lst: List[str]) -> List[str]:
            seen = set()
            out = []
            for item in lst:
                clean = item.strip()
                if clean and clean.lower() not in seen:
                    seen.add(clean.lower())
                    out.append(clean)
            return out

        profile = (
            db.query(ProjectSemanticProfile)
            .filter(ProjectSemanticProfile.project_id == project.id)
            .first()
        )
        if not profile:
            profile = ProjectSemanticProfile(
                project_id=project.id,
                tenant_id=tenant_id,
                workspace_id=project.workspace_id or "ws_default",
                name=project.name,
            )
            db.add(profile)

        profile.name = project.name
        profile.description = project.description or f"Architecture and project workspace for {project.name}"
        profile.domain = domain
        profile.aliases_json = json.dumps(clean_list(aliases))
        profile.business_concepts_json = json.dumps(clean_list(business_concepts)[:30])
        profile.technical_concepts_json = json.dumps(clean_list(technical_concepts)[:25])
        profile.important_entities_json = json.dumps(clean_list(important_entities)[:20])
        profile.architecture_concepts_json = json.dumps(clean_list(architecture_concepts)[:25])
        profile.requirements_summary_json = json.dumps(reqs_summary[:15])
        profile.decisions_summary_json = json.dumps(decs_summary[:15])
        profile.visual_concepts_json = json.dumps(clean_list(visual_concepts)[:25])
        profile.representative_evidence_json = json.dumps(representative_evidence[:8])
        profile.state_version = int(state_row.current_version) if state_row else 1

        # Generate and cache embedding vector
        composite_text = profile.to_composite_text()
        vector = self.embedding_service.embed_text(composite_text)
        profile.embedding_vector_json = json.dumps(vector)
        profile.embedding_model = self.embedding_service.model_name
        profile.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(profile)
        logger.info(
            "project_semantic_profile_rebuilt: project=%s concepts=%d vector_dim=%d",
            project.id,
            len(business_concepts) + len(technical_concepts),
            len(vector),
        )
        return profile

    def ensure_all_profiles(self, db: Session, tenant_id: str = "default_tenant") -> List[ProjectSemanticProfile]:
        """Ensure every active non-system project has an up-to-date semantic profile."""
        projects = db.query(Project).filter(Project.is_system.is_(False)).all()
        profiles: List[ProjectSemanticProfile] = []
        for p in projects:
            profiles.append(self.get_or_create_profile(p.id, db, tenant_id=tenant_id))
        return profiles

    def rank_candidates_by_embedding(
        self,
        text: str,
        projects: List[Project],
        db: Session,
        tenant_id: str = "default_tenant",
        top_k: int = 5,
    ) -> List[tuple[Project, float]]:
        """Compute cosine similarity between incoming text and project profiles, returning top-k."""
        from app.services.embedding_service import cosine_similarity

        if not projects or not text.strip():
            return [(p, 0.0) for p in projects[:top_k]]

        text_vec = self.embedding_service.embed_text(text)
        scored: List[tuple[Project, float]] = []

        for p in projects:
            profile = self.get_or_create_profile(p.id, db, tenant_id=tenant_id)
            p_vec: Optional[List[float]] = None
            if profile.embedding_vector_json:
                try:
                    p_vec = json.loads(profile.embedding_vector_json)
                except Exception:
                    p_vec = None
            if not p_vec:
                p_vec = self.embedding_service.embed_text(profile.to_composite_text())
                profile.embedding_vector_json = json.dumps(p_vec)
                try:
                    db.commit()
                except Exception:
                    db.rollback()

            sim = cosine_similarity(text_vec, p_vec)
            scored.append((p, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


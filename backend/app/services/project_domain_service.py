import hashlib
import json
import re
from collections import Counter
from typing import List

from sqlalchemy.orm import Session

from app.models.intelligence import CandidateKnowledge
from app.models.evidence import Evidence
from app.models.project import Project
from app.models.project_domain import ProjectDomainProfile
from app.models.project_state import ProjectState


class ProjectDomainKnowledgeService:
    """Build a compact, persisted project-domain profile from trusted knowledge."""

    STOPWORDS = {
        "the", "and", "for", "with", "from", "that", "this", "have", "has",
        "will", "shall", "into", "then", "than", "when", "where", "what",
        "which", "their", "they", "them", "are", "was", "were", "been",
        "being", "use", "using", "used", "need", "needs", "project", "system",
        "team", "should", "could", "would", "must", "can", "about", "only",
        "also", "very", "more", "less", "our", "your", "you", "we", "its",
    }

    @staticmethod
    def _safe_json(raw: str) -> list:
        try:
            value = json.loads(raw or "")
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def _state_text(self, state: ProjectState) -> List[str]:
        parts = [state.title or "", state.vision or ""]
        for raw in (
            state.requirements_json,
            state.architecture_json,
            state.decisions_json,
            state.constraints_json,
            state.assumptions_json,
        ):
            for item in self._safe_json(raw):
                if isinstance(item, dict):
                    parts.extend(
                        str(v) for v in item.values()
                        if isinstance(v, (str, int, float)) and str(v).strip()
                    )
                elif isinstance(item, (str, int, float)):
                    parts.append(str(item))
        return [p.strip() for p in parts if str(p).strip()]

    def _keywords(self, texts: List[str]) -> List[str]:
        counter = Counter()
        for text in texts:
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_+.-]{2,40}", text.lower()):
                if token not in self.STOPWORDS and not token.isdigit():
                    counter[token] += 1
        return [token for token, _ in counter.most_common(40)]

    def refresh(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        workspace_id: str = "ws_default",
    ) -> ProjectDomainProfile:
        project = (
            db.query(Project)
            .filter(Project.id == project_id, Project.is_system.is_(False))
            .first()
        )
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        approved = (
            db.query(CandidateKnowledge)
            .filter(
                CandidateKnowledge.project_id == project_id,
                CandidateKnowledge.status == "approved",
            )
            .order_by(CandidateKnowledge.updated_at.desc())
            .limit(40)
            .all()
        )

        texts = [project.name or "", project.description or ""]
        if state:
            texts.extend(self._state_text(state))

        evidence_ids: List[str] = []
        for candidate in approved:
            texts.extend([candidate.title or "", candidate.content or ""])
            for evidence_id in self._safe_json(candidate.evidence_ids_json):
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)

        if evidence_ids:
            evidence_rows = (
                db.query(Evidence)
                .filter(
                    Evidence.project_id == project_id,
                    Evidence.id.in_(evidence_ids),
                )
                .order_by(Evidence.created_at.desc())
                .limit(40)
                .all()
            )
            texts.extend(row.content or "" for row in evidence_rows)

        digest = hashlib.sha256(
            json.dumps(
                {
                    "state_version": state.current_version if state else 0,
                    "texts": texts,
                    "candidate_ids": [c.id for c in approved],
                    "evidence_ids": evidence_ids,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()

        profile = (
            db.query(ProjectDomainProfile)
            .filter(ProjectDomainProfile.project_id == project_id)
            .first()
        )
        if profile and profile.source_digest == digest:
            return profile

        keywords = self._keywords(texts)
        concepts = [k for k in keywords if len(k) >= 5][:25]

        summary_parts = []
        if project.description:
            summary_parts.append(project.description.strip())
        if state and state.vision:
            summary_parts.append(f"Vision: {state.vision.strip()}")
        if approved:
            summary_parts.append(
                "Approved knowledge: " + "; ".join(
                    f"{c.title}: {c.content}" for c in approved[:12]
                )
            )

        profile = profile or ProjectDomainProfile(
            project_id=project_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        profile.tenant_id = tenant_id
        profile.workspace_id = workspace_id
        profile.domain_summary = " ".join(summary_parts)[:5000]
        profile.keywords_json = json.dumps(keywords)
        profile.concepts_json = json.dumps(concepts)
        profile.evidence_ids_json = json.dumps(evidence_ids[:40])
        profile.state_version = state.current_version if state else 1
        profile.source_digest = digest
        profile.updated_at = datetime.utcnow()
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile

    def get_or_refresh(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        workspace_id: str = "ws_default",
    ) -> ProjectDomainProfile:
        return self.refresh(project_id, db, tenant_id=tenant_id, workspace_id=workspace_id)

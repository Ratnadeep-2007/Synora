from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.core.sanitizer import mask_sensitive_data

logger = logging.getLogger(__name__)


class AuditService:
    """
    Immutable audit logging service recording high-impact governance events:
    - Source connected/disconnected
    - Role/permission changes
    - State changes proposed, approved, or rejected
    - Conflict resolutions
    - Agent workforce execution
    - Authoritative Project State version increments
    """

    def record_event(
        self,
        action: str,
        actor_id: str,
        resource_type: str,
        db: Session,
        tenant_id: str = "default_tenant",
        actor_role: Optional[str] = None,
        resource_id: Optional[str] = None,
        before_state: Optional[Dict[str, Any]] = None,
        after_state: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        status: str = "success",
    ) -> AuditLog:
        """
        Appends an immutable audit log record. Sensitive tokens are automatically masked.
        """
        # Ensure any credentials or secrets are sanitized
        masked_before = mask_sensitive_data(before_state) if before_state else None
        masked_after = mask_sensitive_data(after_state) if after_state else None

        audit_entry = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_state_json=json.dumps(masked_before) if masked_before else None,
            after_state_json=json.dumps(masked_after) if masked_after else None,
            ip_address=ip_address,
            status=status,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(audit_entry)
        db.commit()
        db.refresh(audit_entry)

        logger.info(
            f"AUDIT LOG: action={action} actor={actor_id} resource={resource_type}:{resource_id} "
            f"tenant={tenant_id} status={status}"
        )
        return audit_entry

    def query_logs(
        self,
        db: Session,
        tenant_id: str = "default_tenant",
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AuditLog]:
        """
        Queries audit logs strictly scoped to the tenant.
        """
        query = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)
        if action:
            query = query.filter(AuditLog.action == action)
        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)

        return query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()

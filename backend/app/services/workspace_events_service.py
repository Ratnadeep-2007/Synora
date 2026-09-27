from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import SynesisException
from app.models.meet_subscription import (
    MeetSubscription,
    MeetSubscriptionStatus,
    MeetSubscriptionTarget,
)
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

SUBSCRIPTION_TTL_DAYS = 7
RENEWAL_THRESHOLD_DAYS = 2


class WorkspaceEventsError(SynesisException):
    pass


class DuplicateSubscriptionError(WorkspaceEventsError):
    pass


class WorkspaceEventsService:
    """Lifecycle manager for Google Workspace Events Meet subscriptions.

    Subscriptions are notification infrastructure only. They tell Synesis
    *when* a transcript artifact becomes available; transcript content is
    always fetched through the Google Meet REST API by the event worker.
    """

    def __init__(self):
        self.api_base = settings.WORKSPACE_EVENTS_API_BASE
        self.transcript_event_type = settings.MEET_TRANSCRIPT_EVENT_TYPE

    def _active_connection(self, user_id: str, db: Session) -> SourceConnection:
        connection = (
            db.query(SourceConnection)
            .filter(
                SourceConnection.user_id == user_id,
                SourceConnection.provider == "google",
                SourceConnection.status == ConnectionStatus.ACTIVE.value,
            )
            .first()
        )
        if not connection:
            metrics.increment("meet_sync_failed_total", labels={"reason": "no_connection"})
            logger.warning(
                "meet_subscription_failed: reason=no_connection user_id=%s",
                user_id,
            )
            raise WorkspaceEventsError(
                f"No active Google connection found for user '{user_id}'. "
                "Connect via /auth/google first."
            )
        return connection

    def create_subscription(
        self,
        user_id: str,
        target_resource: str,
        db: Session,
        workspace_id: str = "ws_default",
        project_id: Optional[str] = None,
        target_type: str = MeetSubscriptionTarget.MEETING_SPACE.value,
        event_types: Optional[List[str]] = None,
        pubsub_topic: Optional[str] = None,
    ) -> MeetSubscription:
        """Create (or return the existing) subscription for a target resource."""
        connection = self._active_connection(user_id, db)

        existing = (
            db.query(MeetSubscription)
            .filter(
                MeetSubscription.user_id == user_id,
                MeetSubscription.target_resource == target_resource,
            )
            .first()
        )
        if existing:
            if existing.status in (
                MeetSubscriptionStatus.ACTIVE.value,
                MeetSubscriptionStatus.EXPIRING.value,
            ):
                return existing
            if existing.status == MeetSubscriptionStatus.SUSPENDED.value:
                existing.status = MeetSubscriptionStatus.ACTIVE.value
                existing.last_error = None
                existing.expires_at = datetime.now(timezone.utc) + timedelta(days=SUBSCRIPTION_TTL_DAYS)
                existing.renewed_at = datetime.now(timezone.utc)
                existing.event_types = json.dumps(event_types or [self.transcript_event_type])
                if pubsub_topic:
                    existing.pubsub_topic = pubsub_topic
                if project_id:
                    existing.project_id = project_id
                db.commit()
                db.refresh(existing)
                metrics.increment("meet_subscription_renewed_total", labels={"provider": "google_meet"})
                logger.info(
                    "meet_subscription_renewed: subscription_id=%s target=%s user_id=%s",
                    existing.id,
                    target_resource,
                    user_id,
                )
                return existing
            raise DuplicateSubscriptionError(
                f"Subscription for target '{target_resource}' already exists "
                f"(status={existing.status}). Renew it instead of duplicating."
            )

        now = datetime.now(timezone.utc)
        subscription = MeetSubscription(
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            provider="google_meet",
            source_connection_id=connection.id,
            target_resource=target_resource,
            target_type=target_type,
            subscription_name=None,
            event_types=json.dumps(event_types or [self.transcript_event_type]),
            pubsub_topic=pubsub_topic,
            status=MeetSubscriptionStatus.ACTIVE.value,
            expires_at=now + timedelta(days=SUBSCRIPTION_TTL_DAYS),
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        metrics.increment("meet_subscription_created_total", labels={"provider": "google_meet"})
        logger.info(
            "meet_subscription_created: subscription_id=%s target=%s user_id=%s "
            "workspace_id=%s project_id=%s event_types=%s",
            subscription.id,
            target_resource,
            user_id,
            workspace_id,
            project_id,
            subscription.event_types,
        )
        return subscription

    def list_subscriptions(
        self,
        db: Session,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[MeetSubscription]:
        query = db.query(MeetSubscription)
        if user_id:
            query = query.filter(MeetSubscription.user_id == user_id)
        if project_id:
            query = query.filter(MeetSubscription.project_id == project_id)
        if status:
            query = query.filter(MeetSubscription.status == status)
        return query.order_by(MeetSubscription.created_at.desc()).all()

    def get_subscription(self, subscription_id: str, db: Session) -> Optional[MeetSubscription]:
        return db.query(MeetSubscription).filter(MeetSubscription.id == subscription_id).first()

    def renew_subscription(self, subscription_id: str, db: Session) -> MeetSubscription:
        subscription = self.get_subscription(subscription_id, db)
        if not subscription:
            raise WorkspaceEventsError(f"Subscription '{subscription_id}' not found.")
        now = datetime.now(timezone.utc)
        subscription.expires_at = now + timedelta(days=SUBSCRIPTION_TTL_DAYS)
        subscription.renewed_at = now
        subscription.status = MeetSubscriptionStatus.ACTIVE.value
        subscription.last_error = None
        db.commit()
        db.refresh(subscription)
        metrics.increment("meet_subscription_renewed_total", labels={"provider": "google_meet"})
        logger.info(
            "meet_subscription_renewed: subscription_id=%s target=%s",
            subscription.id,
            subscription.target_resource,
        )
        return subscription

    def mark_failed(self, subscription_id: str, error: str, db: Session) -> MeetSubscription:
        subscription = self.get_subscription(subscription_id, db)
        if not subscription:
            raise WorkspaceEventsError(f"Subscription '{subscription_id}' not found.")
        subscription.status = MeetSubscriptionStatus.FAILED.value
        subscription.last_error = error
        db.commit()
        db.refresh(subscription)
        metrics.increment("meet_sync_failed_total", labels={"reason": "subscription_failed"})
        logger.error(
            "meet_subscription_failed: subscription_id=%s error=%s",
            subscription.id,
            error,
        )
        return subscription

    def suspend_subscription(self, subscription_id: str, db: Session) -> MeetSubscription:
        subscription = self.get_subscription(subscription_id, db)
        if not subscription:
            raise WorkspaceEventsError(f"Subscription '{subscription_id}' not found.")
        subscription.status = MeetSubscriptionStatus.SUSPENDED.value
        db.commit()
        db.refresh(subscription)
        logger.info("meet_subscription_suspended: subscription_id=%s", subscription.id)
        return subscription

    def refresh_expiration_statuses(self, db: Session) -> Dict[str, int]:
        """Mark subscriptions near/past expiry. Returns counts by transition."""
        now = datetime.now(timezone.utc)
        expiring_cutoff = now + timedelta(days=RENEWAL_THRESHOLD_DAYS)
        transitions = {"expiring": 0, "expired": 0}
        active_subs = (
            db.query(MeetSubscription)
            .filter(
                MeetSubscription.status.in_(
                    [MeetSubscriptionStatus.ACTIVE.value, MeetSubscriptionStatus.EXPIRING.value]
                )
            )
            .all()
        )
        for sub in active_subs:
            if not sub.expires_at:
                continue
            expires_at = sub.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now and sub.status != MeetSubscriptionStatus.EXPIRED.value:
                sub.status = MeetSubscriptionStatus.EXPIRED.value
                transitions["expired"] += 1
            elif expires_at <= expiring_cutoff and sub.status == MeetSubscriptionStatus.ACTIVE.value:
                sub.status = MeetSubscriptionStatus.EXPIRING.value
                transitions["expiring"] += 1
        db.commit()
        if transitions["expiring"] or transitions["expired"]:
            logger.warning(
                "meet_subscription_expiration_scan: expiring=%d expired=%d",
                transitions["expiring"],
                transitions["expired"],
            )
        return transitions

    def to_read_dict(self, subscription: MeetSubscription) -> Dict[str, Any]:
        try:
            event_types = json.loads(subscription.event_types) if subscription.event_types else []
        except Exception:
            event_types = []
        return {
            "id": subscription.id,
            "workspace_id": subscription.workspace_id,
            "project_id": subscription.project_id,
            "user_id": subscription.user_id,
            "provider": subscription.provider,
            "source_connection_id": subscription.source_connection_id,
            "target_resource": subscription.target_resource,
            "target_type": subscription.target_type,
            "subscription_name": subscription.subscription_name,
            "event_types": event_types,
            "pubsub_topic": subscription.pubsub_topic,
            "status": subscription.status,
            "created_at": subscription.created_at.isoformat() if subscription.created_at else None,
            "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
            "renewed_at": subscription.renewed_at.isoformat() if subscription.renewed_at else None,
            "last_event_at": subscription.last_event_at.isoformat() if subscription.last_event_at else None,
            "last_error": subscription.last_error,
        }

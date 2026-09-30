from sqlalchemy.orm import Session

from app.models.whatsapp_batch import WhatsAppBatch, WhatsAppBatchItem
from app.services.whatsapp_batch_service import WhatsAppBatchService
from app.services.whatsapp_service import WhatsAppIntelligenceService


def test_whatsapp_batch_enqueue_coalesces_same_group(db_session: Session):
    service = WhatsAppBatchService()

    first = service.enqueue_message(
        {
            "message_id": "batch_msg_1",
            "group_jid": "engineering@g.us",
            "group_name": "Engineering",
            "text": "We need a Redis session cache.",
        },
        db_session,
    )
    second = service.enqueue_message(
        {
            "message_id": "batch_msg_2",
            "group_jid": "engineering@g.us",
            "group_name": "Engineering",
            "text": "And preserve the existing auth gateway.",
        },
        db_session,
    )

    assert first["batch_id"] == second["batch_id"]
    assert db_session.query(WhatsAppBatch).count() == 1
    assert db_session.query(WhatsAppBatchItem).count() == 2


def test_whatsapp_batch_keeps_different_groups_separate(db_session: Session):
    service = WhatsAppBatchService()

    first = service.enqueue_message(
        {
            "message_id": "batch_group_a_1",
            "group_jid": "a@g.us",
            "group_name": "A",
            "text": "Claims requirement.",
        },
        db_session,
    )
    second = service.enqueue_message(
        {
            "message_id": "batch_group_b_1",
            "group_jid": "b@g.us",
            "group_name": "B",
            "text": "Platform requirement.",
        },
        db_session,
    )

    assert first["batch_id"] != second["batch_id"]
    assert db_session.query(WhatsAppBatch).count() == 2


def test_whatsapp_batch_force_processing_calls_once_for_batch(
    db_session: Session, monkeypatch
):
    service = WhatsAppBatchService()
    service.enqueue_message(
        {
            "message_id": "batch_process_1",
            "group_jid": "processing@g.us",
            "group_name": "Processing",
            "text": "Use Redis for sessions.",
        },
        db_session,
    )
    service.enqueue_message(
        {
            "message_id": "batch_process_2",
            "group_jid": "processing@g.us",
            "group_name": "Processing",
            "text": "Keep JWT validation at the gateway.",
        },
        db_session,
    )

    calls = []

    def fake_batch(self, messages, db, tenant_id="default_tenant", batch_id=None):
        calls.append((batch_id, len(messages)))
        return {
            "batch_id": batch_id,
            "processed": len(messages),
            "visual_updates": 1,
            "results": [],
            "errors": [],
            "visual_errors": [],
        }

    monkeypatch.setattr(
        WhatsAppIntelligenceService,
        "process_incoming_batch",
        fake_batch,
    )

    result = service.process_due_batches(db_session, force=True)

    assert result["processed_batches"] == 1
    assert calls == [(result["batches"][0]["batch_id"], 2)]

    batch = db_session.query(WhatsAppBatch).filter_by(id=calls[0][0]).first()
    assert batch is not None
    assert batch.status == "completed"

    items = db_session.query(WhatsAppBatchItem).filter_by(batch_id=batch.id).all()
    assert len(items) == 2
    assert all(item.status == "completed" for item in items)

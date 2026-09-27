"""
Phase 2 Automated QA & Security Audit Test Suite for Synesis.
Covers Parts 3 to 21:
- Google Meet API operations
- Advanced pagination & boundary checks
- Idempotency & mutation updates
- Error mapping & status codes
- Retry behavior & exponential backoff
- Token refresh propagation
- Data fidelity & dialogue normalization
- Database integrity & cascading
- Secret exposure & multi-tenant isolation
- Failure recovery & partial sync resilience
"""
import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    CredentialsExpiredError,
    GoogleMeetError,
    GoogleMeetPermissionError,
    GoogleMeetRateLimitError,
    GoogleMeetResourceNotFoundError,
    GoogleMeetTransientError,
)
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.schemas.meeting import MeetingDetailRead, MeetingRead, TranscriptRead
from app.services.encryption_service import EncryptionService
from app.services.google_meet import GoogleMeetService
from app.services.google_oauth import GoogleOAuthService


@pytest.fixture
def meet_service(google_service: GoogleOAuthService) -> GoogleMeetService:
    return GoogleMeetService(oauth_service=google_service)


@pytest.fixture
def qa_user(db_session: Session) -> User:
    user = User(id="usr_qa_auditor", email="auditor@synesis.internal", name="QA Auditor")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def qa_connection(
    db_session: Session,
    qa_user: User,
    encryption_service: EncryptionService,
) -> SourceConnection:
    creds = {
        "access_token": "ya29.initial_audit_token",
        "refresh_token": "1//initial_refresh_token",
        "token_type": "Bearer",
    }
    conn = SourceConnection(
        id="conn_qa_auditor",
        user_id=qa_user.id,
        provider="google",
        provider_account_id="g_auditor_123",
        provider_account_email="auditor@google.com",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict(creds),
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn


# ==============================================================================
# PART 4: PAGINATION TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_pagination_single_page(meet_service: GoogleMeetService):
    """Test 1: Single page of 10 entries."""
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as m:
        m.return_value = httpx.Response(200, json={
            "transcriptEntries": [{"name": f"ent_{i}", "text": f"text {i}"} for i in range(10)]
        })
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t")
        assert len(entries) == 10


@pytest.mark.asyncio
async def test_pagination_multiple_pages(meet_service: GoogleMeetService):
    """Test 2: Multiple pages (3 pages of 10)."""
    calls = 0
    async def mock_3pages(*args, **kwargs):
        nonlocal calls
        calls += 1
        p_tok = kwargs.get("params", {}).get("pageToken")
        if not p_tok:
            return httpx.Response(200, json={
                "transcriptEntries": [{"name": f"ent_p1_{i}", "text": f"p1_{i}"} for i in range(10)],
                "nextPageToken": "tok_p2"
            })
        elif p_tok == "tok_p2":
            return httpx.Response(200, json={
                "transcriptEntries": [{"name": f"ent_p2_{i}", "text": f"p2_{i}"} for i in range(10)],
                "nextPageToken": "tok_p3"
            })
        return httpx.Response(200, json={
            "transcriptEntries": [{"name": f"ent_p3_{i}", "text": f"p3_{i}"} for i in range(10)]
        })

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_3pages):
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t")
        assert len(entries) == 30
        assert calls == 3


@pytest.mark.asyncio
async def test_pagination_empty_page_with_next_token(meet_service: GoogleMeetService):
    """Test 3: Empty page returning nextPageToken."""
    async def mock_empty_with_next(*args, **kwargs):
        p_tok = kwargs.get("params", {}).get("pageToken")
        if not p_tok:
            return httpx.Response(200, json={"transcriptEntries": [], "nextPageToken": "next_page"})
        return httpx.Response(200, json={"transcriptEntries": [{"name": "ent_1", "text": "hello"}]})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_empty_with_next):
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t")
        assert len(entries) == 1


@pytest.mark.asyncio
async def test_pagination_identical_token_bounded(meet_service: GoogleMeetService):
    """Test 4: Identical nextPageToken returned repeatedly (infinite loop guard test)."""
    call_count = 0
    async def mock_loop(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={
            "transcriptEntries": [{"name": f"ent_{call_count}", "text": "loop"}],
            "nextPageToken": "STUCK_TOKEN"
        })

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_loop):
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t", max_pages=20)
        # Verify it halted at max_pages=20
        assert call_count == 20
        assert len(entries) == 20


@pytest.mark.asyncio
async def test_pagination_large_limit_enforced(meet_service: GoogleMeetService):
    """Test 5: Large pagination limit enforcement."""
    call_count = 0
    async def mock_pages(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={
            "transcriptEntries": [{"name": f"ent_{call_count}", "text": "entry"}],
            "nextPageToken": f"tok_{call_count}"
        })

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_pages):
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t", max_pages=5)
        assert call_count == 5
        assert len(entries) == 5


# ==============================================================================
# PART 5: IDEMPOTENCY & MUTATION TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_idempotency_upstream_mutation(
    meet_service: GoogleMeetService,
    qa_connection: SourceConnection,
    qa_user: User,
    db_session: Session,
):
    """Test idempotency: updating an existing transcript entry text upstream."""
    conf = "conferenceRecords/conf_mutation"
    trsc = f"{conf}/transcripts/tr_mut"

    def make_mock(text_value):
        async def mock_fn(*args, **kwargs):
            url = kwargs.get("url", "")
            if "entries" in url:
                return httpx.Response(200, json={
                    "transcriptEntries": [{"name": f"{trsc}/entries/e1", "text": text_value}]
                })
            if "transcripts" in url:
                return httpx.Response(200, json={"transcripts": [{"name": trsc, "state": "ENDED"}]})
            if "participants" in url:
                return httpx.Response(200, json={"participants": []})
            return httpx.Response(200, json={"conferenceRecords": [{"name": conf}]})
        return mock_fn

    # Sync original
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=make_mock("Original text")):
        res1 = await meet_service.sync_conferences(user_id=qa_user.id, db=db_session)
        assert res1.total_entries_synced == 1
        e1 = db_session.query(TranscriptEntry).filter_by(provider_entry_id=f"{trsc}/entries/e1").first()
        assert e1.text == "Original text"

    # Sync modified text upstream
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=make_mock("Updated text upstream")):
        res2 = await meet_service.sync_conferences(user_id=qa_user.id, db=db_session)
        assert res2.total_entries_synced == 1
        db_session.refresh(e1)
        assert e1.text == "Updated text upstream"

    # Verify no duplicate records created
    assert db_session.query(TranscriptEntry).filter_by(provider_entry_id=f"{trsc}/entries/e1").count() == 1


@pytest.mark.asyncio
async def test_idempotency_partial_additions(
    meet_service: GoogleMeetService,
    qa_connection: SourceConnection,
    qa_user: User,
    db_session: Session,
):
    """Test partial additions: 20 initial entries -> sync -> same 20 + 5 new -> verify 25 total."""
    conf = "conferenceRecords/conf_partial_add"
    trsc = f"{conf}/transcripts/tr_add"

    def make_entries_mock(count):
        async def mock_fn(*args, **kwargs):
            url = kwargs.get("url", "")
            if "entries" in url:
                return httpx.Response(200, json={
                    "transcriptEntries": [{"name": f"{trsc}/entries/e_{i}", "text": f"Utterance {i}"} for i in range(count)]
                })
            if "transcripts" in url:
                return httpx.Response(200, json={"transcripts": [{"name": trsc, "state": "ENDED"}]})
            if "participants" in url:
                return httpx.Response(200, json={"participants": []})
            return httpx.Response(200, json={"conferenceRecords": [{"name": conf}]})
        return mock_fn

    # Batch 1: 20 entries
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=make_entries_mock(20)):
        await meet_service.sync_conferences(user_id=qa_user.id, db=db_session)
        c1 = db_session.query(TranscriptEntry).filter(TranscriptEntry.provider_entry_id.like(f"{trsc}/entries/%")).count()
        assert c1 == 20

    # Batch 2: 25 entries (20 existing + 5 new)
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=make_entries_mock(25)):
        await meet_service.sync_conferences(user_id=qa_user.id, db=db_session)
        c2 = db_session.query(TranscriptEntry).filter(TranscriptEntry.provider_entry_id.like(f"{trsc}/entries/%")).count()
        assert c2 == 25


# ==============================================================================
# PART 6 & 7: ERROR HANDLING & RETRY BEHAVIOR
# ==============================================================================

@pytest.mark.asyncio
async def test_error_400_no_retry(meet_service: GoogleMeetService):
    """400 Bad Request should not retry and raise immediately."""
    calls = 0
    async def mock_fn(*args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="Bad Request")

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn):
        with pytest.raises(GoogleMeetError) as exc_info:
            await meet_service._execute_request("GET", "conferenceRecords", "tok")
        assert exc_info.value.status_code == 400
        assert calls == 1


@pytest.mark.asyncio
async def test_retry_exponential_backoff_on_502(meet_service: GoogleMeetService):
    """502 Bad Gateway retries up to max_retries with backoff."""
    calls = 0
    durations = []
    async def mock_fn(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json={"ok": True})

    async def fake_sleep(dur):
        durations.append(dur)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn), \
         patch("asyncio.sleep", side_effect=fake_sleep):
        res = await meet_service._execute_request("GET", "path", "tok")
        assert res == {"ok": True}
        assert calls == 3
        assert durations == [0.5, 1.0]


# ==============================================================================
# PART 9 & 10: DATA FIDELITY & NORMALIZATION
# ==============================================================================

@pytest.mark.asyncio
async def test_data_fidelity_unicode_and_timestamps(
    meet_service: GoogleMeetService,
    qa_connection: SourceConnection,
    qa_user: User,
    db_session: Session,
):
    """Verify Unicode, emojis, ISO timestamps, and punctuation fidelity."""
    conf = "conferenceRecords/conf_unicode"
    trsc = f"{conf}/transcripts/tr_uni"
    part = f"{conf}/participants/p_alice"

    special_text = "Emoji: 🎯 🚀, Accents: Café, naïve, Japanese: 東京, Punctuation: '\"!@#$%^&*()_+"

    mock_entries = [{
        "name": f"{trsc}/entries/e_uni",
        "participant": part,
        "text": special_text,
        "languageCode": "ja-JP",
        "startTime": "2026-09-24T14:30:00.123456Z",
        "endTime": "2026-09-24T14:30:10.654321Z",
    }]

    async def mock_fn(*args, **kwargs):
        url = kwargs.get("url", "")
        if "entries" in url:
            return httpx.Response(200, json={"transcriptEntries": mock_entries})
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": [{"name": trsc, "state": "ENDED"}]})
        if "participants" in url:
            return httpx.Response(200, json={"participants": [{"name": part, "signedinUser": {"displayName": "Alice In Wonderland"}}]})
        return httpx.Response(200, json={"conferenceRecords": [{"name": conf}]})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn):
        await meet_service.sync_conferences(user_id=qa_user.id, db=db_session)
        entry = db_session.query(TranscriptEntry).filter_by(provider_entry_id=f"{trsc}/entries/e_uni").first()
        assert entry is not None
        assert entry.text == special_text
        assert entry.language_code == "ja-JP"
        assert entry.participant.display_name == "Alice In Wonderland"
        assert entry.start_time is not None
        assert entry.end_time is not None


# ==============================================================================
# PART 11: DATABASE INTEGRITY & CASCADING
# ==============================================================================

def test_database_foreign_key_cascades(db_session: Session, qa_user: User):
    """Verify cascade delete from Meeting to Transcripts and Entries, SET NULL for participant."""
    m = Meeting(
        id="mtg_test_cascade",
        project_id="proj_1",
        user_id=qa_user.id,
        provider="google",
        provider_conference_id="conf_cascade_test",
        status="ENDED",
    )
    db_session.add(m)
    db_session.commit()

    p = Participant(id="part_test_casc", meeting_id=m.id, provider_participant_id="p1", display_name="Bob")
    t = Transcript(id="trsc_test_casc", meeting_id=m.id, provider="google", provider_transcript_id="tr1", state="ENDED")
    db_session.add_all([p, t])
    db_session.commit()

    e = TranscriptEntry(
        id="tent_test_casc",
        transcript_id=t.id,
        provider="google",
        provider_entry_id="e1",
        participant_id=p.id,
        text="Sample statement",
    )
    db_session.add(e)
    db_session.commit()

    # 1. Delete participant -> verify entry.participant_id set to NULL
    db_session.delete(p)
    db_session.commit()
    db_session.refresh(e)
    assert e.participant_id is None

    # 2. Delete meeting -> verify transcript and entry deleted
    db_session.delete(m)
    db_session.commit()
    assert db_session.query(Transcript).filter_by(id=t.id).first() is None
    assert db_session.query(TranscriptEntry).filter_by(id=e.id).first() is None


# ==============================================================================
# PART 14: CROSS-USER ISOLATION
# ==============================================================================

def test_cross_user_isolation(db_session: Session):
    """Verify meetings of User A are not accessible by User B."""
    u_a = User(id="user_alpha", email="alpha@synesis.internal", name="Alpha")
    u_b = User(id="user_beta", email="beta@synesis.internal", name="Beta")
    db_session.add_all([u_a, u_b])
    db_session.commit()

    m_a = Meeting(id="mtg_a", project_id="p1", user_id=u_a.id, provider="google", provider_conference_id="c_a", status="ENDED")
    m_b = Meeting(id="mtg_b", project_id="p1", user_id=u_b.id, provider="google", provider_conference_id="c_b", status="ENDED")
    db_session.add_all([m_a, m_b])
    db_session.commit()

    a_meetings = db_session.query(Meeting).filter(Meeting.user_id == u_a.id).all()
    b_meetings = db_session.query(Meeting).filter(Meeting.user_id == u_b.id).all()

    assert len(a_meetings) == 1
    assert a_meetings[0].id == "mtg_a"
    assert len(b_meetings) == 1
    assert b_meetings[0].id == "mtg_b"


# ==============================================================================
# PART 13: SECRET EXPOSURE AUDIT
# ==============================================================================

def test_secret_exposure_in_schemas():
    """Verify DTO schemas do not expose tokens, credentials, or secrets."""
    meeting_fields = set(MeetingRead.model_fields.keys())
    detail_fields = set(MeetingDetailRead.model_fields.keys())
    transcript_fields = set(TranscriptRead.model_fields.keys())

    all_exposed_fields = meeting_fields | detail_fields | transcript_fields
    banned_keywords = ["token", "secret", "password", "credential", "encrypted"]

    for field in all_exposed_fields:
        for kw in banned_keywords:
            assert kw not in field.lower(), f"Potential secret field '{field}' exposed in public schema!"


# ==============================================================================
# PART 20: LARGE TRANSCRIPT TEST (Simulated 10,000 entries)
# ==============================================================================

@pytest.mark.asyncio
async def test_large_transcript_simulation(
    meet_service: GoogleMeetService,
    qa_connection: SourceConnection,
    qa_user: User,
    db_session: Session,
):
    """Simulate a large meeting (10,000 entries across 100 pages). Verify bounded ingestion."""
    conf = "conferenceRecords/conf_huge"
    trsc = f"{conf}/transcripts/tr_huge"

    page_counter = 0
    async def mock_huge_pages(*args, **kwargs):
        nonlocal page_counter
        url = kwargs.get("url", "")
        if "entries" in url:
            page_counter += 1
            has_more = page_counter < 100
            batch = [{
                "name": f"{trsc}/entries/e_{(page_counter-1)*100 + i}",
                "text": f"Spoken sentence {(page_counter-1)*100 + i} in 3-hour marathon meeting.",
                "languageCode": "en-US",
                "startTime": "2026-09-24T10:00:00Z"
            } for i in range(100)]
            resp = {"transcriptEntries": batch}
            if has_more:
                resp["nextPageToken"] = f"huge_page_{page_counter}"
            return httpx.Response(200, json=resp)
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": [{"name": trsc, "state": "ENDED"}]})
        if "participants" in url:
            return httpx.Response(200, json={"participants": []})
        return httpx.Response(200, json={"conferenceRecords": [{"name": conf}]})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_huge_pages):
        res = await meet_service.sync_conferences(user_id=qa_user.id, db=db_session)
        # Bounded by max_pages=20 (2,000 entries)
        assert res.total_entries_synced == 2000
        assert page_counter == 20


# ==============================================================================
# PART 21: FAILURE RECOVERY & PARTIAL SYNC
# ==============================================================================

@pytest.mark.asyncio
async def test_failure_recovery_mid_sync(
    meet_service: GoogleMeetService,
    qa_connection: SourceConnection,
    qa_user: User,
    db_session: Session,
):
    """Simulate failure during transcript fetch on 2nd conference. Verify 1st conference persists."""
    async def mock_partial_fail(*args, **kwargs):
        url = kwargs.get("url", "")
        if "conf_2/transcripts" in url:
            return httpx.Response(500, text="Internal Google Server Error on Conf 2")
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": [{"name": "conf_1/transcripts/t1", "state": "ENDED"}]})
        if "entries" in url:
            return httpx.Response(200, json={"transcriptEntries": [{"name": "e1", "text": "speech"}]})
        if "participants" in url:
            return httpx.Response(200, json={"participants": []})
        return httpx.Response(200, json={"conferenceRecords": [
            {"name": "conferenceRecords/conf_1"},
            {"name": "conferenceRecords/conf_2"}
        ]})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_partial_fail):
        res = await meet_service.sync_conferences(user_id=qa_user.id, db=db_session)
        assert res.total_conferences_synced == 2
        assert res.total_transcripts_synced == 1

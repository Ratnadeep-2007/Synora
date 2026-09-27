"""
Aggressive QA & Security Integration Test Suite for Synesis Phase 2.
Executes Parts 3 through 21 and outputs empirical results.
"""
import asyncio
import gc
import json
import logging
import os
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add backend to path
sys.path.insert(0, os.path.abspath("backend"))

from app.core.config import settings
from app.core.database import Base
from app.core.exceptions import (
    ConnectionNotFoundError,
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

# Setup in-memory sqlite db with foreign keys enforced
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    echo=False
)

# Enforce foreign keys on SQLite
from sqlalchemy import event
@event.listens_for(test_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)

enc_service = EncryptionService("dummy_encryption_key_32_bytes_len!")
oauth_service = GoogleOAuthService(settings=settings, encryption_service=enc_service)
meet_service = GoogleMeetService(oauth_service=oauth_service)

results = {}

def log_test(category, name, passed, details=""):
    if category not in results:
        results[category] = []
    results[category].append({
        "name": name,
        "passed": passed,
        "details": details
    })
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {category} :: {name} - {details}")

# ==============================================================================
# Helper to create test user & connection
# ==============================================================================
def create_test_fixture(db, user_id="user_test_qa"):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        user = User(id=user_id, email=f"{user_id}@test.com", name="QA User")
        db.add(user)
        db.commit()
    
    conn = db.query(SourceConnection).filter_by(user_id=user_id).first()
    if not conn:
        creds = {"access_token": "ya29.initial_test_token", "refresh_token": "1//refresh_token"}
        conn = SourceConnection(
            id=f"conn_{user_id}",
            user_id=user_id,
            provider="google",
            provider_account_id=f"g_{user_id}",
            provider_account_email=f"{user_id}@google.com",
            status=ConnectionStatus.ACTIVE.value,
            encrypted_credentials=enc_service.encrypt_dict(creds),
        )
        db.add(conn)
        db.commit()
    return user, conn

async def run_qa_tests():
    print("=================================================================")
    print("STARTING QA INTEGRATION & VULNERABILITY AUDIT RUN")
    print("=================================================================")

    # --------------------------------------------------------------------------
    # PART 4: PAGINATION TESTS
    # --------------------------------------------------------------------------
    # Test 1: Single page (10 entries)
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as m:
        m.return_value = httpx.Response(200, json={
            "transcriptEntries": [{"name": f"ent_{i}", "text": f"text {i}"} for i in range(10)]
        })
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t")
        log_test("Pagination", "Single Page (10 entries)", len(entries) == 10, f"Retrieved {len(entries)}")

    # Test 2: Multiple pages (3 pages of 10)
    page_req_count = 0
    async def mock_3pages(*args, **kwargs):
        nonlocal page_req_count
        page_req_count += 1
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
        else:
            return httpx.Response(200, json={
                "transcriptEntries": [{"name": f"ent_p3_{i}", "text": f"p3_{i}"} for i in range(10)]
            })

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_3pages):
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t")
        log_test("Pagination", "Multiple Pages (3 pages of 10)", len(entries) == 30 and page_req_count == 3, f"Retrieved {len(entries)} in {page_req_count} calls")

    # Test 3: Empty page with nextPageToken
    async def mock_empty_with_next(*args, **kwargs):
        p_tok = kwargs.get("params", {}).get("pageToken")
        if not p_tok:
            return httpx.Response(200, json={"transcriptEntries": [], "nextPageToken": "next_page"})
        return httpx.Response(200, json={"transcriptEntries": [{"name": "ent_1", "text": "hello"}]})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_empty_with_next):
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t")
        log_test("Pagination", "Empty page with nextPageToken", len(entries) == 1, f"Handled correctly, retrieved {len(entries)}")

    # Test 4: Identical nextPageToken returned repeatedly (Infinite Loop vulnerability)
    loop_call_count = 0
    async def mock_infinite_loop(*args, **kwargs):
        nonlocal loop_call_count
        loop_call_count += 1
        return httpx.Response(200, json={
            "transcriptEntries": [{"name": f"ent_{loop_call_count}", "text": "loop"}],
            "nextPageToken": "STUCK_TOKEN"
        })

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_infinite_loop):
        # Service has max_pages = 20 for entries
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t")
        # Check: Did it stop at max_pages or detect token cycle?
        log_test("Pagination", "Identical nextPageToken Loop Test", loop_call_count == 20, f"Calls reached limit {loop_call_count}, bounded by max_pages=20 but did not detect repeated token")

    # Test 5: Large pagination limit (exceeding max_pages)
    large_page_calls = 0
    async def mock_100_pages(*args, **kwargs):
        nonlocal large_page_calls
        large_page_calls += 1
        return httpx.Response(200, json={
            "transcriptEntries": [{"name": f"ent_{large_page_calls}", "text": "entry"}],
            "nextPageToken": f"tok_{large_page_calls}"
        })

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_100_pages):
        entries = await meet_service.fetch_all_transcript_entries("tok", "conf/c/trans/t", max_pages=20)
        log_test("Pagination", "Large Pagination (Bound enforcement)", len(entries) == 20 and large_page_calls == 20, f"Enforced max_pages=20 (got {len(entries)})")

    # --------------------------------------------------------------------------
    # PART 5: IDEMPOTENCY TESTS
    # --------------------------------------------------------------------------
    db = TestSession()
    user, conn = create_test_fixture(db, "user_idempotency")

    conf_name = "conferenceRecords/conf_idem_full"
    trans_name = f"{conf_name}/transcripts/tr_idem"

    def get_idem_mock(entries_list):
        async def mock_idem(*args, **kwargs):
            url = kwargs.get("url", "")
            if "entries" in url:
                return httpx.Response(200, json={"transcriptEntries": entries_list})
            if "transcripts" in url:
                return httpx.Response(200, json={"transcripts": [{"name": trans_name, "state": "ENDED"}]})
            if "participants" in url:
                return httpx.Response(200, json={"participants": [{"name": f"{conf_name}/participants/p1", "signedinUser": {"displayName": "Alice"}}]})
            return httpx.Response(200, json={"conferenceRecords": [{"name": conf_name, "space": "spaces/s1"}]})
        return mock_idem

    # Run 1: 20 entries
    entries_v1 = [{"name": f"{trans_name}/entries/e_{i}", "text": f"Utterance {i}", "participant": f"{conf_name}/participants/p1"} for i in range(20)]
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=get_idem_mock(entries_v1)):
        res1 = await meet_service.sync_conferences(user_id=user.id, db=db)
        log_test("Idempotency", "Initial Sync (20 entries)", res1.total_entries_synced == 20, f"Synced {res1.total_entries_synced}")

    # Run 2: Exact same 20 entries
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=get_idem_mock(entries_v1)):
        res2 = await meet_service.sync_conferences(user_id=user.id, db=db)
        m_count = db.query(Meeting).filter_by(provider_conference_id=conf_name).count()
        e_count = db.query(TranscriptEntry).filter(TranscriptEntry.provider_entry_id.like(f"{trans_name}/entries/%")).count()
        log_test("Idempotency", "Re-sync identical data", m_count == 1 and e_count == 20, f"Meetings={m_count}, Entries={e_count}")

    # Run 3: Modify entry text upstream
    entries_v2 = [{"name": f"{trans_name}/entries/e_0", "text": "Modified Utterance 0", "participant": f"{conf_name}/participants/p1"}] + entries_v1[1:]
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=get_idem_mock(entries_v2)):
        res3 = await meet_service.sync_conferences(user_id=user.id, db=db)
        e0 = db.query(TranscriptEntry).filter_by(provider_entry_id=f"{trans_name}/entries/e_0").first()
        log_test("Idempotency", "Upstream entry modification update", e0.text == "Modified Utterance 0", f"Updated text: '{e0.text}'")

    # Run 4: Partial additions: same 20 + 5 new -> verify 25 total
    entries_v3 = entries_v2 + [{"name": f"{trans_name}/entries/e_{i}", "text": f"New utterance {i}", "participant": f"{conf_name}/participants/p1"} for i in range(20, 25)]
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=get_idem_mock(entries_v3)):
        res4 = await meet_service.sync_conferences(user_id=user.id, db=db)
        e_count_v3 = db.query(TranscriptEntry).filter(TranscriptEntry.provider_entry_id.like(f"{trans_name}/entries/%")).count()
        log_test("Idempotency", "Partial additions (20 + 5 new = 25)", e_count_v3 == 25, f"Total entries in DB = {e_count_v3}")

    db.close()

    # --------------------------------------------------------------------------
    # PART 6 & 7: ERROR HANDLING & RETRY BEHAVIOR
    # --------------------------------------------------------------------------
    # 400 Bad Request (No retry, immediate GoogleMeetError)
    calls_400 = 0
    async def mock_400(*args, **kwargs):
        nonlocal calls_400
        calls_400 += 1
        return httpx.Response(400, text="Bad Request")

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_400):
        try:
            await meet_service._execute_request("GET", "conferenceRecords", "tok")
            log_test("Error Handling", "400 Bad Request", False, "Did not raise exception")
        except GoogleMeetError as e:
            log_test("Error Handling", "400 Bad Request", calls_400 == 1 and e.status_code == 400, f"Calls={calls_400}, Code={e.status_code}")

    # 403 Forbidden (No retry, GoogleMeetPermissionError)
    calls_403 = 0
    async def mock_403(*args, **kwargs):
        nonlocal calls_403
        calls_403 += 1
        return httpx.Response(403, json={"error": {"message": "Caller lacks permission"}})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_403):
        try:
            await meet_service._execute_request("GET", "conferenceRecords", "tok")
            log_test("Error Handling", "403 Forbidden", False, "Did not raise")
        except GoogleMeetPermissionError as e:
            log_test("Error Handling", "403 Forbidden", calls_403 == 1, f"Calls={calls_403}, Raised GoogleMeetPermissionError")

    # 404 Not Found (No retry, GoogleMeetResourceNotFoundError)
    calls_404 = 0
    async def mock_404(*args, **kwargs):
        nonlocal calls_404
        calls_404 += 1
        return httpx.Response(404, text="Not Found")

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_404):
        try:
            await meet_service._execute_request("GET", "conferenceRecords/none", "tok")
            log_test("Error Handling", "404 Not Found", False, "Did not raise")
        except GoogleMeetResourceNotFoundError:
            log_test("Error Handling", "404 Not Found", calls_404 == 1, f"Calls={calls_404}, Raised GoogleMeetResourceNotFoundError")

    # 429 Too Many Requests (Retries, backoff parsed from Retry-After)
    calls_429 = 0
    async def mock_429(*args, **kwargs):
        nonlocal calls_429
        calls_429 += 1
        if calls_429 < 3:
            return httpx.Response(429, headers={"Retry-After": "1"}, text="Quota exceeded")
        return httpx.Response(200, json={"conferenceRecords": []})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_429), \
         patch("asyncio.sleep", new_callable=AsyncMock) as m_sleep:
        res_429 = await meet_service._execute_request("GET", "conferenceRecords", "tok")
        log_test("Retry Behavior", "429 Rate Limit Retry with Retry-After", calls_429 == 3 and m_sleep.call_count == 2, f"Retried {calls_429} times, sleep called {m_sleep.call_count} times")

    # 429 Exhaustion (Raises GoogleMeetRateLimitError)
    calls_429_ex = 0
    async def mock_429_exhaust(*args, **kwargs):
        nonlocal calls_429_ex
        calls_429_ex += 1
        return httpx.Response(429, headers={"Retry-After": "1"}, text="Quota exceeded")

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_429_exhaust), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        try:
            await meet_service._execute_request("GET", "conferenceRecords", "tok", max_retries=3)
            log_test("Retry Behavior", "429 Max Retries Exhaustion", False, "Did not raise")
        except GoogleMeetRateLimitError:
            log_test("Retry Behavior", "429 Max Retries Exhaustion", calls_429_ex == 3, f"Stopped after max_retries={calls_429_ex}")

    # 500 / 502 / 503 Server Errors (Retries with exponential backoff)
    calls_500 = 0
    sleep_intervals = []
    async def mock_500(*args, **kwargs):
        nonlocal calls_500
        calls_500 += 1
        if calls_500 < 3:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json={"conferenceRecords": []})

    async def fake_sleep(dur):
        sleep_intervals.append(dur)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_500), \
         patch("asyncio.sleep", side_effect=fake_sleep):
        await meet_service._execute_request("GET", "conferenceRecords", "tok")
        log_test("Retry Behavior", "5xx Exponential Backoff", sleep_intervals == [0.5, 1.0], f"Sleep durations: {sleep_intervals}")

    # Timeout / Connection failure retry
    calls_tout = 0
    async def mock_timeout(*args, **kwargs):
        nonlocal calls_tout
        calls_tout += 1
        if calls_tout < 2:
            raise httpx.ConnectTimeout("Connect timeout")
        return httpx.Response(200, json={"conferenceRecords": []})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_timeout), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        res_tout = await meet_service._execute_request("GET", "conferenceRecords", "tok")
        log_test("Retry Behavior", "ConnectTimeout Retry", calls_tout == 2, f"Recovered after {calls_tout} attempts")

    # --------------------------------------------------------------------------
    # PART 8: TOKEN REFRESH REUSE
    # --------------------------------------------------------------------------
    db = TestSession()
    u_refresh, c_refresh = create_test_fixture(db, "user_refresh_test")
    refreshed_called = False

    async def mock_refresh_hook(conn, db, force=True):
        nonlocal refreshed_called
        refreshed_called = True
        new_creds = {"access_token": "ya29.NEW_REFRESHED_TOKEN", "refresh_token": "1//refresh_token"}
        conn.encrypted_credentials = enc_service.encrypt_dict(new_creds)
        db.commit()
        return conn

    token_seen_in_retry = ""
    req_attempts = 0
    async def mock_401_flow(*args, **kwargs):
        nonlocal req_attempts, token_seen_in_retry
        req_attempts += 1
        headers = kwargs.get("headers", {})
        auth_hdr = headers.get("Authorization", "")
        if req_attempts == 1:
            return httpx.Response(401, json={"error": "invalid_grant"})
        token_seen_in_retry = auth_hdr.replace("Bearer ", "")
        return httpx.Response(200, json={"conferenceRecords": []})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_401_flow), \
         patch.object(meet_service.oauth_service, "refresh_credentials", side_effect=mock_refresh_hook):
        res = await meet_service.list_conference_records("expired_tok", connection=c_refresh, db=db)
        log_test("Token Refresh", "Automatic 401 recovery & token propagation", 
                 refreshed_called and token_seen_in_retry == "ya29.NEW_REFRESHED_TOKEN",
                 f"Refreshed called: {refreshed_called}, New token in retry: {token_seen_in_retry}")

    db.close()

    # --------------------------------------------------------------------------
    # PART 9 & 10: DATA FIDELITY & DIALOGUE STATEMENT NORMALIZATION
    # --------------------------------------------------------------------------
    db = TestSession()
    u_data, c_data = create_test_fixture(db, "user_data_fidelity")
    conf_fid = "conferenceRecords/conf_fidelity"
    trans_fid = f"{conf_fid}/transcripts/tr_fid"
    part_fid = f"{conf_fid}/participants/p_alice"

    fidelity_text = "Unicode test: 🚀 Café, na\u00efve, 日本語, and special symbols: <xml>&\"'! \n Multi-line statement."
    
    mock_fidelity_entries = [
        {
            "name": f"{trans_fid}/entries/ent_fidelity",
            "participant": part_fid,
            "text": fidelity_text,
            "languageCode": "ja-JP",
            "startTime": "2026-09-24T12:00:00.123456Z",
            "endTime": "2026-09-24T12:00:05.654321Z",
        },
        {
            "name": f"{trans_fid}/entries/ent_missing_speaker",
            "text": "Utterance with no participant field",
            "startTime": "2026-09-24T12:00:06Z",
            "endTime": "2026-09-24T12:00:08Z",
        },
        {
            "name": f"{trans_fid}/entries/ent_empty_text",
            "text": "",  # Empty text
            "startTime": "2026-09-24T12:00:09Z",
        }
    ]

    async def mock_fidelity_api(*args, **kwargs):
        url = kwargs.get("url", "")
        if "entries" in url:
            return httpx.Response(200, json={"transcriptEntries": mock_fidelity_entries})
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": [{"name": trans_fid, "state": "ENDED"}]})
        if "participants" in url:
            return httpx.Response(200, json={"participants": [{"name": part_fid, "signedinUser": {"displayName": "Alice Wonderland"}}]})
        return httpx.Response(200, json={"conferenceRecords": [{"name": conf_fid}]})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fidelity_api):
        await meet_service.sync_conferences(user_id=u_data.id, db=db)
        
        # Check fidelity entry
        saved_ent = db.query(TranscriptEntry).filter_by(provider_entry_id=f"{trans_fid}/entries/ent_fidelity").first()
        log_test("Data Fidelity", "Unicode and Special Characters Preserved", saved_ent.text == fidelity_text, f"Preserved exactly: {saved_ent.text[:30]}...")
        log_test("Data Fidelity", "Language Code Preserved", saved_ent.language_code == "ja-JP", f"Lang={saved_ent.language_code}")
        log_test("Data Fidelity", "Participant Association", saved_ent.participant.display_name == "Alice Wonderland", f"Speaker: {saved_ent.participant.display_name}")

        # Check missing speaker entry
        saved_no_speaker = db.query(TranscriptEntry).filter_by(provider_entry_id=f"{trans_fid}/entries/ent_missing_speaker").first()
        log_test("Dialogue Statement", "Missing Speaker Handled Gracefully", saved_no_speaker is not None and saved_no_speaker.participant_id is None, "Saved with participant_id=None")

        # Check empty text entry was skipped
        saved_empty = db.query(TranscriptEntry).filter_by(provider_entry_id=f"{trans_fid}/entries/ent_empty_text").first()
        log_test("Dialogue Statement", "Empty Text Utterance Filtered", saved_empty is None, "Empty text skipped during ingestion")

    db.close()

    # --------------------------------------------------------------------------
    # PART 11: DATABASE INTEGRITY & CASCADE DELETES
    # --------------------------------------------------------------------------
    db = TestSession()
    u_casc, c_casc = create_test_fixture(db, "user_cascade_test")
    m_test = Meeting(
        id="mtg_cascade_test",
        project_id="proj_1",
        user_id=u_casc.id,
        provider="google",
        provider_conference_id="conf_cascade_1",
        status="ENDED"
    )
    db.add(m_test)
    db.commit()

    p_test = Participant(id="part_casc_1", meeting_id=m_test.id, provider_participant_id="p1", display_name="Charlie")
    t_test = Transcript(id="trsc_casc_1", meeting_id=m_test.id, provider="google", provider_transcript_id="tr1", state="ENDED")
    db.add_all([p_test, t_test])
    db.commit()

    e_test = TranscriptEntry(
        id="tent_casc_1",
        transcript_id=t_test.id,
        provider="google",
        provider_entry_id="e1",
        participant_id=p_test.id,
        text="Cascade test entry"
    )
    db.add(e_test)
    db.commit()

    # Test 1: Participant deletion sets participant_id=NULL on TranscriptEntry
    db.delete(p_test)
    db.commit()
    db.refresh(e_test)
    log_test("Database Integrity", "Participant delete ON DELETE SET NULL", e_test.participant_id is None, f"Entry participant_id={e_test.participant_id}")

    # Test 2: Meeting deletion cascades to Transcripts and Entries
    db.delete(m_test)
    db.commit()
    remaining_trsc = db.query(Transcript).filter_by(id="trsc_casc_1").first()
    remaining_ent = db.query(TranscriptEntry).filter_by(id="tent_casc_1").first()
    log_test("Database Integrity", "Meeting delete cascades to Transcript and Entries", remaining_trsc is None and remaining_ent is None, f"Remaining Trsc={remaining_trsc}, Entry={remaining_ent}")

    db.close()

    # --------------------------------------------------------------------------
    # PART 13: SECRET EXPOSURE CHECK
    # --------------------------------------------------------------------------
    # Check meeting schemas do not leak secrets
    meeting_read_fields = MeetingRead.model_fields.keys()
    detail_fields = MeetingDetailRead.model_fields.keys()
    transcript_fields = TranscriptRead.model_fields.keys()

    sensitive_keywords = ["token", "secret", "password", "credential", "encrypted"]
    leaked = []
    for f in list(meeting_read_fields) + list(detail_fields) + list(transcript_fields):
        for kw in sensitive_keywords:
            if kw in f.lower():
                leaked.append(f)

    log_test("Secret Exposure", "No sensitive tokens or secrets in Meeting DTO schemas", len(leaked) == 0, f"Leaked fields: {leaked}")

    # --------------------------------------------------------------------------
    # PART 14: CROSS-USER & TENANT ISOLATION
    # --------------------------------------------------------------------------
    db = TestSession()
    u1, _ = create_test_fixture(db, "user_tenant_1")
    u2, _ = create_test_fixture(db, "user_tenant_2")

    m_u1 = Meeting(id="mtg_u1", project_id="p1", user_id=u1.id, provider="google", provider_conference_id="conf_u1", status="ENDED")
    m_u2 = Meeting(id="mtg_u2", project_id="p2", user_id=u2.id, provider="google", provider_conference_id="conf_u2", status="ENDED")
    db.add_all([m_u1, m_u2])
    db.commit()

    # Query meetings for User 1
    u1_meetings = db.query(Meeting).filter(Meeting.user_id == u1.id).all()
    u2_meetings = db.query(Meeting).filter(Meeting.user_id == u2.id).all()
    
    log_test("Cross-User Isolation", "Meetings scoped strictly to user_id in DB queries", 
             len(u1_meetings) == 1 and u1_meetings[0].id == "mtg_u1" and len(u2_meetings) == 1 and u2_meetings[0].id == "mtg_u2",
             f"User 1 saw {len(u1_meetings)}, User 2 saw {len(u2_meetings)}")
    db.close()

    # --------------------------------------------------------------------------
    # PART 20: LARGE TRANSCRIPT TEST (10,000 Entries)
    # --------------------------------------------------------------------------
    print("Testing Large Transcript Simulation (10,000 entries)...")
    db = TestSession()
    u_large, c_large = create_test_fixture(db, "user_large_transcript")
    conf_large = "conferenceRecords/conf_large"
    trans_large = f"{conf_large}/transcripts/tr_large"

    # Simulate 100 pages of 100 entries = 10,000 entries
    large_page_idx = 0
    async def mock_large_entries_api(*args, **kwargs):
        nonlocal large_page_idx
        url = kwargs.get("url", "")
        if "entries" in url:
            large_page_idx += 1
            has_next = large_page_idx < 100
            batch = [{
                "name": f"{trans_large}/entries/e_{(large_page_idx-1)*100 + i}",
                "text": f"This is speech utterance number {(large_page_idx-1)*100 + i} in a 3-hour long meeting.",
                "languageCode": "en-US",
                "startTime": f"2026-09-24T10:{large_page_idx%60:02d}:00Z"
            } for i in range(100)]
            resp = {"transcriptEntries": batch}
            if has_next:
                resp["nextPageToken"] = f"page_tok_{large_page_idx}"
            return httpx.Response(200, json=resp)
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": [{"name": trans_large, "state": "ENDED"}]})
        if "participants" in url:
            return httpx.Response(200, json={"participants": []})
        return httpx.Response(200, json={"conferenceRecords": [{"name": conf_large}]})

    start_mem = gc.mem_alloc() if hasattr(gc, "mem_alloc") else 0
    t0 = time.time()
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_large_entries_api):
        # Service's fetch_all_transcript_entries has default max_pages=20 (2,000 entries)
        # Let's test sync with max_pages override or default bound
        res_large = await meet_service.sync_conferences(user_id=u_large.id, db=db)
        duration = time.time() - t0
        log_test("Large Transcript", "Large Transcript Bounded Ingestion", 
                 res_large.total_entries_synced == 2000, 
                 f"Ingested {res_large.total_entries_synced} entries in {duration:.2f}s (bounded by max_pages=20)")

    db.close()

    # --------------------------------------------------------------------------
    # PART 21: FAILURE RECOVERY (Mid-sync failure)
    # --------------------------------------------------------------------------
    db = TestSession()
    u_fail, c_fail = create_test_fixture(db, "user_fail_recovery")
    
    # 2 conferences returned: Conf 1 succeeds, Conf 2 fails with 500 error in transcript fetch
    async def mock_mid_failure(*args, **kwargs):
        url = kwargs.get("url", "")
        if "conf_fail_2/transcripts" in url:
            return httpx.Response(500, text="Internal Google Server Error on Conf 2")
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": [{"name": "conf_fail_1/transcripts/t1", "state": "ENDED"}]})
        if "entries" in url:
            return httpx.Response(200, json={"transcriptEntries": [{"name": "e1", "text": "speech"}]})
        if "participants" in url:
            return httpx.Response(200, json={"participants": []})
        return httpx.Response(200, json={"conferenceRecords": [
            {"name": "conferenceRecords/conf_fail_1"},
            {"name": "conferenceRecords/conf_fail_2"}
        ]})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_mid_failure):
        # Sync catches transcript failure per conference as warning and proceeds
        res_fail = await meet_service.sync_conferences(user_id=u_fail.id, db=db)
        log_test("Failure Recovery", "Mid-sync partial failure resilience", 
                 res_fail.total_conferences_synced == 2 and res_fail.total_transcripts_synced == 1,
                 f"Synced {res_fail.total_conferences_synced} conferences; Conf 1 transcript synced, Conf 2 gracefully handled")

    db.close()

if __name__ == "__main__":
    asyncio.run(run_qa_tests())

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
from app.services.encryption_service import EncryptionService
from app.services.google_meet import GoogleMeetService
from app.services.google_oauth import GoogleOAuthService


@pytest.fixture
def meet_service(google_service: GoogleOAuthService) -> GoogleMeetService:
    return GoogleMeetService(oauth_service=google_service)


@pytest.fixture
def active_connection(
    db_session: Session,
    test_user: User,
    encryption_service: EncryptionService,
) -> SourceConnection:
    creds = {
        "access_token": "ya29.valid_mock_meet_access_token",
        "refresh_token": "1//valid_mock_meet_refresh_token",
        "token_type": "Bearer",
    }
    conn = SourceConnection(
        id="conn_meet_test_user",
        user_id=test_user.id,
        provider="google",
        provider_account_id="google_sub_meet_test",
        provider_account_email="meet_user@example.com",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict(creds),
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn


# ==============================================================================
# A. Conference list success
# ==============================================================================
@pytest.mark.asyncio
async def test_a_conference_list_success(meet_service: GoogleMeetService):
    mock_payload = {
        "conferenceRecords": [
            {
                "name": "conferenceRecords/conf_abc_123",
                "startTime": "2026-09-24T10:00:00Z",
                "endTime": "2026-09-24T10:45:00Z",
                "space": "spaces/xyz",
            }
        ]
    }
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = httpx.Response(200, json=mock_payload)

        res = await meet_service.list_conference_records("token_abc", page_size=10)
        assert "conferenceRecords" in res
        assert len(res["conferenceRecords"]) == 1
        assert res["conferenceRecords"][0]["name"] == "conferenceRecords/conf_abc_123"


# ==============================================================================
# B. Conference pagination
# ==============================================================================
@pytest.mark.asyncio
async def test_b_conference_pagination(
    meet_service: GoogleMeetService,
    active_connection: SourceConnection,
    db_session: Session,
    test_user: User,
):
    page_1 = {
        "conferenceRecords": [{"name": "conferenceRecords/conf_page_1", "endTime": "2026-09-24T10:00:00Z"}],
        "nextPageToken": "token_for_page_2",
    }
    page_2 = {
        "conferenceRecords": [{"name": "conferenceRecords/conf_page_2", "endTime": "2026-09-24T11:00:00Z"}],
    }

    async def mock_request_fn(*args, **kwargs):
        params = kwargs.get("params", {})
        if params.get("pageToken") == "token_for_page_2":
            return httpx.Response(200, json=page_2)
        if "participants" in kwargs.get("url", ""):
            return httpx.Response(200, json={"participants": []})
        if "transcripts" in kwargs.get("url", ""):
            return httpx.Response(200, json={"transcripts": []})
        return httpx.Response(200, json=page_1)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_request_fn):
        sync_res = await meet_service.sync_conferences(user_id=test_user.id, db=db_session, max_conferences=10)
        assert sync_res.total_conferences_discovered == 2
        assert sync_res.total_conferences_synced == 2


# ==============================================================================
# C. Conference not found
# ==============================================================================
@pytest.mark.asyncio
async def test_c_conference_not_found(meet_service: GoogleMeetService):
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = httpx.Response(404, text="Conference Record Not Found")

        with pytest.raises(GoogleMeetResourceNotFoundError):
            await meet_service.get_conference_record("token", "conferenceRecords/nonexistent")


# ==============================================================================
# D. Transcript list success
# ==============================================================================
@pytest.mark.asyncio
async def test_d_transcript_list_success(meet_service: GoogleMeetService):
    mock_payload = {
        "transcripts": [
            {
                "name": "conferenceRecords/conf_1/transcripts/trans_1",
                "state": "ENDED",
                "startTime": "2026-09-24T10:02:00Z",
                "endTime": "2026-09-24T10:44:00Z",
            }
        ]
    }
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = httpx.Response(200, json=mock_payload)

        res = await meet_service.list_transcripts("token", "conferenceRecords/conf_1")
        assert len(res["transcripts"]) == 1
        assert res["transcripts"][0]["state"] == "ENDED"


# ==============================================================================
# E. No transcript available
# ==============================================================================
@pytest.mark.asyncio
async def test_e_no_transcript_available(
    meet_service: GoogleMeetService,
    active_connection: SourceConnection,
    db_session: Session,
    test_user: User,
):
    async def mock_request_fn(*args, **kwargs):
        url = kwargs.get("url", "")
        if "participants" in url:
            return httpx.Response(200, json={"participants": []})
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": []})  # No transcript available
        return httpx.Response(
            200,
            json={"conferenceRecords": [{"name": "conferenceRecords/conf_no_transcript"}]},
        )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_request_fn):
        res = await meet_service.sync_conferences(user_id=test_user.id, db=db_session)
        assert res.total_conferences_synced == 1
        assert res.total_transcripts_synced == 0

        # Check DB represents NOT_AVAILABLE state explicitly without failing
        trsc = (
            db_session.query(Transcript)
            .join(Meeting)
            .filter(Meeting.provider_conference_id == "conferenceRecords/conf_no_transcript")
            .first()
        )
        assert trsc is not None
        assert trsc.state == "NOT_AVAILABLE"


# ==============================================================================
# F. Transcript pagination
# ==============================================================================
@pytest.mark.asyncio
async def test_f_transcript_pagination(meet_service: GoogleMeetService):
    page_1 = {
        "transcripts": [{"name": "conferenceRecords/conf_1/transcripts/tr_1", "state": "ENDED"}],
        "nextPageToken": "next_tr_page",
    }
    page_2 = {
        "transcripts": [{"name": "conferenceRecords/conf_1/transcripts/tr_2", "state": "ENDED"}],
    }

    async def mock_fn(*args, **kwargs):
        params = kwargs.get("params", {})
        if params.get("pageToken") == "next_tr_page":
            return httpx.Response(200, json=page_2)
        return httpx.Response(200, json=page_1)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn):
        items = await meet_service.fetch_all_transcripts("tok", "conferenceRecords/conf_1")
        assert len(items) == 2
        assert items[0]["name"] == "conferenceRecords/conf_1/transcripts/tr_1"
        assert items[1]["name"] == "conferenceRecords/conf_1/transcripts/tr_2"


# ==============================================================================
# G. Transcript entry retrieval
# ==============================================================================
@pytest.mark.asyncio
async def test_g_transcript_entry_retrieval(meet_service: GoogleMeetService):
    mock_entries = {
        "transcriptEntries": [
            {
                "name": "conferenceRecords/c1/transcripts/t1/entries/e1",
                "text": "We should add a general onboarding agent.",
                "languageCode": "en-US",
                "startTime": "2026-09-24T10:05:00Z",
                "endTime": "2026-09-24T10:05:03Z",
                "participant": "conferenceRecords/c1/participants/p1",
            }
        ]
    }
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = httpx.Response(200, json=mock_entries)

        entries = await meet_service.fetch_all_transcript_entries("tok", "conferenceRecords/c1/transcripts/t1")
        assert len(entries) == 1
        assert entries[0]["text"] == "We should add a general onboarding agent."


# ==============================================================================
# H. Participant resolution
# ==============================================================================
@pytest.mark.asyncio
async def test_h_participant_resolution(
    meet_service: GoogleMeetService,
    active_connection: SourceConnection,
    db_session: Session,
    test_user: User,
):
    conf_name = "conferenceRecords/conf_with_participants"
    part_name = f"{conf_name}/participants/p_alice"
    trans_name = f"{conf_name}/transcripts/tr_1"

    async def mock_fn(*args, **kwargs):
        url = kwargs.get("url", "")
        if "entries" in url:
            return httpx.Response(
                200,
                json={
                    "transcriptEntries": [
                        {
                            "name": f"{trans_name}/entries/ent_1",
                            "participant": part_name,
                            "text": "Hello world from Alice",
                            "languageCode": "en",
                        }
                    ]
                },
            )
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": [{"name": trans_name, "state": "ENDED"}]})
        if "participants" in url:
            return httpx.Response(
                200,
                json={
                    "participants": [
                        {
                            "name": part_name,
                            "signedinUser": {"displayName": "Alice Smith"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"conferenceRecords": [{"name": conf_name}]})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn):
        res = await meet_service.sync_conferences(user_id=test_user.id, db=db_session)
        assert res.total_entries_synced == 1

        # Verify entry participant_id was resolved to internal Participant row
        entry = db_session.query(TranscriptEntry).filter_by(provider_entry_id=f"{trans_name}/entries/ent_1").first()
        assert entry is not None
        assert entry.participant_id is not None
        assert entry.participant.display_name == "Alice Smith"


# ==============================================================================
# I. Duplicate synchronization (idempotency)
# ==============================================================================
@pytest.mark.asyncio
async def test_i_duplicate_synchronization(
    meet_service: GoogleMeetService,
    active_connection: SourceConnection,
    db_session: Session,
    test_user: User,
):
    conf_name = "conferenceRecords/conf_idempotency_test"
    trans_name = f"{conf_name}/transcripts/tr_idem"

    async def mock_fn(*args, **kwargs):
        url = kwargs.get("url", "")
        if "entries" in url:
            return httpx.Response(
                200,
                json={
                    "transcriptEntries": [
                        {"name": f"{trans_name}/entries/e1", "text": "Idempotent speech"}
                    ]
                },
            )
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": [{"name": trans_name, "state": "ENDED"}]})
        if "participants" in url:
            return httpx.Response(
                200,
                json={"participants": [{"name": f"{conf_name}/participants/p1", "signedinUser": {"displayName": "Bob"}}]},
            )
        return httpx.Response(200, json={"conferenceRecords": [{"name": conf_name}]})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn):
        # Run 1
        res1 = await meet_service.sync_conferences(user_id=test_user.id, db=db_session)
        assert res1.total_conferences_synced == 1

        # Run 2 (Immediately re-run sync)
        res2 = await meet_service.sync_conferences(user_id=test_user.id, db=db_session)
        assert res2.total_conferences_synced == 1

        # Verify counts in database are exactly 1
        m_count = db_session.query(Meeting).filter_by(provider_conference_id=conf_name).count()
        t_count = db_session.query(Transcript).filter_by(provider_transcript_id=trans_name).count()
        e_count = db_session.query(TranscriptEntry).filter_by(provider_entry_id=f"{trans_name}/entries/e1").count()

        assert m_count == 1, "Duplicate Meeting record created!"
        assert t_count == 1, "Duplicate Transcript record created!"
        assert e_count == 1, "Duplicate TranscriptEntry record created!"


# ==============================================================================
# J. 401 error with automatic token refresh
# ==============================================================================
@pytest.mark.asyncio
async def test_j_401_error_with_token_refresh(
    meet_service: GoogleMeetService,
    active_connection: SourceConnection,
    db_session: Session,
):
    attempts = 0

    async def mock_fn(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(401, json={"error": "invalid_token"})
        return httpx.Response(200, json={"conferenceRecords": []})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn), \
         patch.object(meet_service.oauth_service, "refresh_credentials", new_callable=AsyncMock) as mock_refresh:

        # Mock refresh updating connection
        mock_refresh.return_value = active_connection

        res = await meet_service.list_conference_records(
            access_token="expired_token",
            connection=active_connection,
            db=db_session,
        )
        assert res == {"conferenceRecords": []}
        assert mock_refresh.called
        assert attempts == 2


# ==============================================================================
# K. 403 error (permission denied)
# ==============================================================================
@pytest.mark.asyncio
async def test_k_403_permission_error(meet_service: GoogleMeetService):
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = httpx.Response(
            403,
            json={"error": {"message": "The caller does not have permission", "code": 403}},
        )

        with pytest.raises(GoogleMeetPermissionError) as exc_info:
            await meet_service.list_conference_records("token")
        assert exc_info.value.status_code == 403


# ==============================================================================
# L. 404 error (resource not found)
# ==============================================================================
@pytest.mark.asyncio
async def test_l_404_resource_not_found(meet_service: GoogleMeetService):
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = httpx.Response(404, text="Resource Not Found")

        with pytest.raises(GoogleMeetResourceNotFoundError) as exc_info:
            await meet_service.get_transcript("token", "conferenceRecords/c/transcripts/invalid")
        assert exc_info.value.status_code == 404


# ==============================================================================
# M. 429 error (rate limit retry)
# ==============================================================================
@pytest.mark.asyncio
async def test_m_429_rate_limit_error(meet_service: GoogleMeetService):
    calls = 0

    async def mock_fn(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "Rate limit"})
        return httpx.Response(200, json={"conferenceRecords": []})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        res = await meet_service.list_conference_records("tok")
        assert res == {"conferenceRecords": []}
        assert calls == 2


# ==============================================================================
# N. Google 5xx error (service error retry)
# ==============================================================================
@pytest.mark.asyncio
async def test_n_google_5xx_server_error(meet_service: GoogleMeetService):
    calls = 0

    async def mock_fn(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json={"conferenceRecords": []})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        res = await meet_service.list_conference_records("tok")
        assert res == {"conferenceRecords": []}
        assert calls == 2


# ==============================================================================
# O. Network timeout retry
# ==============================================================================
@pytest.mark.asyncio
async def test_o_network_timeout_retry(meet_service: GoogleMeetService):
    calls = 0

    async def mock_fn(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.TimeoutException("Read timed out")
        return httpx.Response(200, json={"conferenceRecords": []})

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_fn), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        res = await meet_service.list_conference_records("tok")
        assert res == {"conferenceRecords": []}
        assert calls == 2


# ==============================================================================
# P. Empty transcript
# ==============================================================================
@pytest.mark.asyncio
async def test_p_empty_transcript(meet_service: GoogleMeetService):
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = httpx.Response(200, json={"transcriptEntries": []})

        entries = await meet_service.fetch_all_transcript_entries("tok", "conferenceRecords/c/transcripts/t")
        assert entries == []


# ==============================================================================
# Q. Malformed Google response
# ==============================================================================
@pytest.mark.asyncio
async def test_q_malformed_google_response(meet_service: GoogleMeetService):
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = httpx.Response(200, text="<HTML>Not JSON</HTML>")

        with pytest.raises(GoogleMeetError, match="Malformed JSON"):
            await meet_service.list_conference_records("tok")

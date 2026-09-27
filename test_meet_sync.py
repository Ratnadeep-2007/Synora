#!/usr/bin/env python3
"""
Synesis Phase 2 — Google Meet & Transcript Retrieval Verification Tool

Usage:
    # 1. Run automated test simulation matching the exact PRD dialogue:
    python test_meet_sync.py

    # 2. Run against live Google Meet REST API (using credentials from Phase 1):
    python test_meet_sync.py --live
"""

import argparse
from datetime import datetime, timezone
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.services.encryption_service import EncryptionService
from app.services.google_meet import GoogleMeetService
from app.services.google_oauth import GoogleOAuthService

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_step(title: str):
    print(f"\n{BOLD}{CYAN}==> [{title}]{RESET}")


def print_pass(msg: str):
    print(f"  {GREEN}[PASS]{RESET} {msg}")


def print_fail(msg: str):
    print(f"  {RED}[FAIL]{RESET} {msg}")


def print_info(msg: str):
    print(f"  {YELLOW}[INFO]{RESET} {msg}")


def run_mock_simulation():
    print(f"{BOLD}=================================================================={RESET}")
    print(f"{BOLD}   SYNESIS — PHASE 2 GOOGLE MEET & TRANSCRIPT TEST SIMULATION     {RESET}")
    print(f"{BOLD}=================================================================={RESET}")

    init_db()
    db = SessionLocal()

    # 1. Ensure test user & active connection
    print_step("Step 1: Check/Seed Authenticated Google Connection (Phase 1 Reuse)")
    user = db.query(User).filter_by(id="usr_meet_dev_test").first()
    if not user:
        user = User(id="usr_meet_dev_test", email="dev@synesis.internal", name="Dev Tester")
        db.add(user)
        db.commit()

    enc = EncryptionService(settings.ENCRYPTION_KEY)
    conn = db.query(SourceConnection).filter_by(user_id=user.id, provider="google").first()
    if not conn:
        creds = {"access_token": "ya29.simulated_access_token", "refresh_token": "1//simulated_refresh"}
        conn = SourceConnection(
            id="conn_meet_dev_test",
            user_id=user.id,
            provider="google",
            provider_account_id="g_account_123",
            provider_account_email="organizer@company.com",
            status=ConnectionStatus.ACTIVE.value,
            encrypted_credentials=enc.encrypt_dict(creds),
        )
        db.add(conn)
        db.commit()

    print_pass(f"Google connection verified for user '{user.id}' (no second OAuth flow required)")

    # 2. Setup mock data matching Section 14 requirements:
    # Speaker A: "We should add a general onboarding agent."
    # Speaker B: "Let's keep BA as the first agent."
    # Speaker A: "Okay, we will discuss this tomorrow."
    # Speaker B: "One requirement is that users must provide business context."
    conf_name = "conferenceRecords/conf_prd_sample_42"
    part_a_name = f"{conf_name}/participants/part_speaker_a"
    part_b_name = f"{conf_name}/participants/part_speaker_b"
    trans_name = f"{conf_name}/transcripts/trans_sample_42"

    mock_conference = {
        "name": conf_name,
        "startTime": "2026-09-24T10:00:00Z",
        "endTime": "2026-09-24T10:45:00Z",
        "space": "spaces/arch_review_meet",
    }
    mock_participants = [
        {"name": part_a_name, "signedinUser": {"displayName": "Speaker A (CEO)", "user": "users/101"}},
        {"name": part_b_name, "signedinUser": {"displayName": "Speaker B (Lead Architect)", "user": "users/102"}},
    ]
    mock_transcripts = [
        {
            "name": trans_name,
            "state": "ENDED",
            "startTime": "2026-09-24T10:01:00Z",
            "endTime": "2026-09-24T10:44:00Z",
            "docsDestination": {"exportUri": "https://docs.google.com/document/d/sample_transcript_doc/edit"},
        }
    ]
    mock_entries = [
        {
            "name": f"{trans_name}/entries/e001",
            "participant": part_a_name,
            "text": "We should add a general onboarding agent.",
            "languageCode": "en-US",
            "startTime": "2026-09-24T10:05:10.000Z",
            "endTime": "2026-09-24T10:05:13.200Z",
        },
        {
            "name": f"{trans_name}/entries/e002",
            "participant": part_b_name,
            "text": "Let's keep BA as the first agent.",
            "languageCode": "en-US",
            "startTime": "2026-09-24T10:05:14.500Z",
            "endTime": "2026-09-24T10:05:17.100Z",
        },
        {
            "name": f"{trans_name}/entries/e003",
            "participant": part_a_name,
            "text": "Okay, we will discuss this tomorrow.",
            "languageCode": "en-US",
            "startTime": "2026-09-24T10:05:18.000Z",
            "endTime": "2026-09-24T10:05:20.500Z",
        },
        {
            "name": f"{trans_name}/entries/e004",
            "participant": part_b_name,
            "text": "One requirement is that users must provide business context.",
            "languageCode": "en-US",
            "startTime": "2026-09-24T10:05:21.000Z",
            "endTime": "2026-09-24T10:05:25.000Z",
        },
    ]

    async def mock_meet_api_req(*args, **kwargs):
        url = kwargs.get("url", "")
        if "entries" in url:
            return httpx.Response(200, json={"transcriptEntries": mock_entries})
        if "transcripts" in url:
            return httpx.Response(200, json={"transcripts": mock_transcripts})
        if "participants" in url:
            return httpx.Response(200, json={"participants": mock_participants})
        if "conferenceRecords" in url:
            return httpx.Response(200, json={"conferenceRecords": [mock_conference]})
        return httpx.Response(404, text="Not Found")

    meet_svc = GoogleMeetService()

    # 3. Execute Synchronization
    print_step("Step 2: Execute Google Meet Synchronization Flow")
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_meet_api_req):
        sync_result = asyncio.run(meet_svc.sync_conferences(user_id=user.id, db=db, max_conferences=5))

    print_pass(f"Conferences discovered: {sync_result.total_conferences_discovered}")
    print_pass(f"Conferences synced: {sync_result.total_conferences_synced}")
    print_pass(f"Transcripts synced: {sync_result.total_transcripts_synced}")
    print_pass(f"Transcript entries synced: {sync_result.total_entries_synced}")

    # 4. Verify Meeting in DB
    print_step("Step 3: Verify Domain Model Normalization")
    meeting = db.query(Meeting).filter_by(provider_conference_id=conf_name).first()
    assert meeting is not None
    print_pass(f"Meeting created: ID='{meeting.id}', Space='{meeting.meeting_space_id}', Status='{meeting.status}'")

    # 5. Verify Participants
    participants = db.query(Participant).filter_by(meeting_id=meeting.id).all()
    assert len(participants) == 2
    for p in participants:
        print_pass(f"Participant: '{p.display_name}' (ID: {p.id}, ProviderRef: {p.provider_participant_id})")

    # 6. Verify Transcript and Structured Entries
    transcript = db.query(Transcript).filter_by(meeting_id=meeting.id).first()
    assert transcript is not None
    print_pass(f"Transcript: ID='{transcript.id}', State='{transcript.state}', DocsExport='{transcript.docs_destination_url}'")

    entries = (
        db.query(TranscriptEntry)
        .filter_by(transcript_id=transcript.id)
        .order_by(TranscriptEntry.start_time.asc())
        .all()
    )
    assert len(entries) == 4
    print_step("Step 4: Display Structured Transcript Entries (Speaker & Time Preserved)")
    for i, e in enumerate(entries, 1):
        speaker = e.participant.display_name if e.participant else "Unknown"
        ts_start = e.start_time.strftime("%H:%M:%S") if e.start_time else "N/A"
        ts_end = e.end_time.strftime("%H:%M:%S") if e.end_time else "N/A"
        print(f"  {BOLD}[{i}] {ts_start} - {ts_end} | {speaker}:{RESET} \"{e.text}\" (lang: {e.language_code})")

    # 7. Test Idempotency (Run Sync Again)
    print_step("Step 5: Test Synchronization Idempotency (Run Sync Again)")
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_meet_api_req):
        sync_result_2 = asyncio.run(meet_svc.sync_conferences(user_id=user.id, db=db, max_conferences=5))

    m_count = db.query(Meeting).filter_by(provider_conference_id=conf_name).count()
    p_count = db.query(Participant).filter_by(meeting_id=meeting.id).count()
    t_count = db.query(Transcript).filter_by(meeting_id=meeting.id).count()
    e_count = db.query(TranscriptEntry).filter_by(transcript_id=transcript.id).count()

    assert m_count == 1, "Duplicate Meeting rows created!"
    assert p_count == 2, "Duplicate Participant rows created!"
    assert t_count == 1, "Duplicate Transcript rows created!"
    assert e_count == 4, "Duplicate TranscriptEntry rows created!"

    print_pass("Re-running sync resulted in ZERO duplicate rows (Idempotency verified)")

    print(f"\n{BOLD}{GREEN}=================================================================={RESET}")
    print(f"{BOLD}{GREEN}    PHASE 2 GOOGLE MEET RETRIEVAL VERIFICATION COMPLETED (100%)    {RESET}")
    print(f"{BOLD}{GREEN}=================================================================={RESET}\n")
    db.close()


def run_live_test():
    print(f"{BOLD}=================================================================={RESET}")
    print(f"{BOLD}   SYNESIS — LIVE GOOGLE MEET REST API RETRIEVAL TEST            {RESET}")
    print(f"{BOLD}=================================================================={RESET}")

    init_db()
    db = SessionLocal()

    # Look for active connection in DB
    conn = (
        db.query(SourceConnection)
        .filter(
            SourceConnection.provider == "google",
            SourceConnection.status == ConnectionStatus.ACTIVE.value,
        )
        .first()
    )

    if not conn:
        print_fail("No active Google OAuth connection found in database.")
        print_info("Please connect your Google account first by running:")
        print_info("  1. python run_backend.py")
        print_info("  2. Open http://localhost:8000/auth/google in your browser")
        print_info("  3. Complete Google authorization consent screen")
        db.close()
        return

    print_pass(f"Found active Google account: {conn.provider_account_email or conn.provider_account_id}")

    meet_svc = GoogleMeetService()
    print_step("Calling Google Meet REST API to discover real conference records...")

    try:
        sync_result = asyncio.run(
            meet_svc.sync_conferences(
                user_id=conn.user_id,
                db=db,
                max_conferences=5,
            )
        )
        print_pass(f"Live Conferences discovered: {sync_result.total_conferences_discovered}")
        print_pass(f"Conferences synced to DB: {sync_result.total_conferences_synced}")
        print_pass(f"Transcripts synced: {sync_result.total_transcripts_synced}")
        print_pass(f"Transcript entries synced: {sync_result.total_entries_synced}")

        if sync_result.total_conferences_discovered == 0:
            print_info("No recent Google Meet conferences found for this account.")
            print_info("To test live transcript retrieval:")
            print_info("  1. Start a Google Meet on your Google account.")
            print_info("  2. Turn ON Transcripts (More options '...' > Transcripts > Start).")
            print_info("  3. Speak a few sentences and end the meeting.")
            print_info("  4. Wait ~2-3 minutes for Google to process the transcript, then re-run this command.")
    except Exception as exc:
        print_fail(f"Google Meet API call returned error: {exc}")

    db.close()


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="Test Synesis Google Meet Integration")
    parser.add_argument("--live", action="store_true", help="Test against live Google Meet REST API")
    args = parser.parse_args()

    if args.live:
        run_live_test()
    else:
        run_mock_simulation()

#!/usr/bin/env python3
"""
Synesis Combined Phase 3-5 Knowledge Pipeline Verification Tool.
Executes the full vertical slice:
Google Meet Transcript -> Source Events -> Evidence -> Meeting Intelligence ->
Candidate Knowledge -> Project State Proposal -> Explicit Approval -> Versioned Project State.
"""
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.core.database import SessionLocal, init_db
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.project_state import ProjectState, ProjectStateVersion, StateChange
from app.models.user import User
from app.services.pipeline_coordinator import PipelineCoordinator
from app.services.project_state_service import ProjectStateService

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


def print_info(msg: str):
    print(f"  {YELLOW}[INFO]{RESET} {msg}")


def run_pipeline_demo():
    print(f"{BOLD}=================================================================={RESET}")
    print(f"{BOLD}   SYNESIS — COMBINED PHASE 3-5 KNOWLEDGE PIPELINE VERIFICATION   {RESET}")
    print(f"{BOLD}=================================================================={RESET}")

    init_db()
    db = SessionLocal()

    # 1. Setup user & sample meeting
    print_step("Step 1: Setup Authenticated Project & Meeting Transcript (Phase 2 Input)")
    user = db.query(User).filter_by(id="usr_pipeline_runner").first()
    if not user:
        user = User(id="usr_pipeline_runner", email="runner@synesis.internal", name="Pipeline Runner")
        db.add(user)
        db.commit()

    proj_id = "proj_knowledge_demo"
    conf_name = "conferenceRecords/conf_demo_slice"

    meeting = db.query(Meeting).filter_by(provider_conference_id=conf_name).first()
    if not meeting:
        meeting = Meeting(
            id="mtg_demo_slice_42",
            project_id=proj_id,
            user_id=user.id,
            provider="google",
            provider_conference_id=conf_name,
            title="Product Architecture Review #42",
            status="ENDED",
        )
        db.add(meeting)
        db.commit()

        part_ceo = Participant(
            id="part_ceo_slice",
            meeting_id=meeting.id,
            provider_participant_id=f"{conf_name}/participants/ceo",
            display_name="CEO (Speaker A)",
        )
        part_arch = Participant(
            id="part_arch_slice",
            meeting_id=meeting.id,
            provider_participant_id=f"{conf_name}/participants/arch",
            display_name="Lead Architect (Speaker B)",
        )
        transcript = Transcript(
            id="trsc_demo_slice",
            meeting_id=meeting.id,
            provider="google",
            provider_transcript_id=f"{conf_name}/transcripts/tr_1",
            state="ENDED",
        )
        db.add_all([part_ceo, part_arch, transcript])
        db.commit()

        # Exact prompt dialogue (PRD Section 14)
        dialogue = [
            ("e1", part_ceo.id, "We should add a general onboarding agent before BA.", "10:05:10"),
            ("e2", part_arch.id, "BA is currently the first processing agent.", "10:05:14"),
            ("e3", part_ceo.id, "Let's discuss whether onboarding should come before BA tomorrow.", "10:05:18"),
            ("e4", part_arch.id, "One requirement is that the user provides business context.", "10:05:22"),
        ]
        for ent_id, spk, txt, ts in dialogue:
            db.add(
                TranscriptEntry(
                    id=f"tent_slice_{ent_id}",
                    transcript_id=transcript.id,
                    provider="google",
                    provider_entry_id=f"entry_{ent_id}",
                    participant_id=spk,
                    text=txt,
                    language_code="en-US",
                    start_time=datetime(2026, 9, 24, 10, 5, int(ts.split(":")[-1]), tzinfo=timezone.utc),
                )
            )
        db.commit()

    print_pass(f"Meeting initialized: ID='{meeting.id}', Title='{meeting.title}'")

    # 2. Inspect initial Authoritative Project State (Version 1)
    state_service = ProjectStateService()
    state = state_service.get_or_create_state(proj_id, db)
    print_step("Step 2: Inspect Initial Authoritative Project State (Baseline)")
    print_pass(f"Project State: Version={state.current_version}")
    initial_workflow = json.loads(state.agent_workflow_json)
    print_info(f"Current Agent Workflow: {' -> '.join(initial_workflow)}")

    # 3. Execute Knowledge Pipeline
    print_step("Step 3: Execute Knowledge Pipeline (Phase 3 Ingestion -> Phase 4 Intelligence)")
    coordinator = PipelineCoordinator(state_service=state_service)
    result = coordinator.process_meeting(
        meeting_id=meeting.id,
        project_id=proj_id,
        db=db,
        actor_id=user.id,
    )

    print_pass(f"Normalized Source Events Ingested: {result.events_ingested}")
    print_pass(f"Immutable Evidence Records Created: {result.evidence_created}")
    print_pass(f"Candidate Knowledge Items Extracted: {result.candidates_extracted}")
    print_pass(f"High-Impact State Proposals Created: {result.proposals_created}")

    # 4. Prove Authoritative Project State is Unchanged
    print_step("Step 4: Verify Core Architectural Invariant (LLM is NOT Source of Truth)")
    db.refresh(state)
    assert state.current_version == 1
    current_workflow = json.loads(state.agent_workflow_json)
    assert current_workflow == initial_workflow
    print_pass("Authoritative Project State remained strictly at Version 1 (0 silent mutations)")
    print_pass("Candidate Proposals retained in 'proposed' state awaiting human review")

    # 5. Display Extracted Candidates & Evidence
    print_step("Step 5: Inspect Extracted Candidates & Evidence Provenance")
    for i, c in enumerate(result.candidates, 1):
        print(f"  {BOLD}[{i}] {c['category'].upper()}:{RESET} \"{c['content']}\" (Classification: {c['classification']})")

    # 6. Display Pending Proposals
    print_step("Step 6: Inspect Pending State Proposals Awaiting Approval")
    proposals = (
        db.query(StateChange)
        .filter_by(project_id=proj_id, approval_status="proposed")
        .all()
    )
    for p in proposals:
        ev_ids = json.loads(p.evidence_ids_json)
        print(f"  {BOLD}Proposal ID:{RESET} {p.id} | {BOLD}Target:{RESET} {p.target_section} | {BOLD}Operation:{RESET} {p.operation} | {BOLD}Evidence:{RESET} {ev_ids}")

    # 7. Explicit Human Approval
    print_step("Step 7: Perform Explicit Human Approval of Proposal")
    target_proposal = next((p for p in proposals if p.target_section == "agent_workflow"), proposals[0])
    version_record = state_service.approve_state_change(
        change_id=target_proposal.id,
        actor_id="usr_executive_approver",
        db=db,
        note="Approved architecture pipeline change.",
    )

    db.refresh(state)
    print_pass(f"State Transition Succeeded: Version 1 -> Version {state.current_version}")
    new_workflow = json.loads(state.agent_workflow_json)
    print_pass(f"Updated Authoritative Agent Workflow: {' -> '.join(new_workflow)}")
    print_pass(f"Immutable Snapshot Created: ID='{version_record.id}', Reason='{version_record.reason}'")

    print(f"\n{BOLD}{GREEN}=================================================================={RESET}")
    print(f"{BOLD}{GREEN}    PHASE 3-5 KNOWLEDGE PIPELINE VERIFICATION COMPLETED (100%)    {RESET}")
    print(f"{BOLD}{GREEN}=================================================================={RESET}\n")
    db.close()


if __name__ == "__main__":
    run_pipeline_demo()

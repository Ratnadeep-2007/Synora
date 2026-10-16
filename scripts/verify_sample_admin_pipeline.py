"""Exercise the deployed pipeline as the sample owner; never log credentials."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time

from dotenv import dotenv_values
import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://synora-oduz.onrender.com"
AUTH = "https://ep-hidden-star-b30n47zs.neonauth.c-4.ap-southeast-1.aws.neon.tech/neondb/auth"
REPORT = ROOT / "SAMPLE_ADMIN_PIPELINE_REPORT.md"


def main():
    credentials = dotenv_values(ROOT / ".env.sample-admin")
    results = []
    session = requests.Session()
    auth = session.post(AUTH + "/sign-in/email", headers={"Origin": credentials["SAMPLE_FRONTEND_URL"]}, json={"email": credentials["SAMPLE_ADMIN_EMAIL"], "password": credentials["SAMPLE_ADMIN_PASSWORD"]}, timeout=60)
    auth.raise_for_status()
    session.headers["Authorization"] = "Bearer " + auth.json()["token"]

    def call(method, path, body=None, **kwargs):
        start = time.monotonic()
        response = session.request(method, API + path, json=body, timeout=180, **kwargs)
        try:
            data = response.json()
        except ValueError:
            data = response.text[:300]
        results.append({"request": method + " " + path, "status": response.status_code, "seconds": round(time.monotonic()-start, 2), "data": data})
        print(method, path, response.status_code, flush=True)
        response.raise_for_status()
        return data

    try:
        access = call("GET", "/auth/workspace-access")
        assert access["status"] == "active" and access["role"] == "owner"
        current_user = call("GET", "/auth/me")
        call("GET", "/health/ready")
        call("GET", "/connectors")
        projects = call("GET", "/projects")
        project = next((p for p in projects if p["name"] == "Harbor Inventory Demo"), None)
        if not project:
            project = call("POST", "/projects", {"name": "Harbor Inventory Demo", "description": "Sample project: warehouse inventory, stock movements, supplier intake, and low-stock alerts.", "workspace_id": "ws_default"})
        project_id = project["id"]
        if not any(p["name"] == "Orion Water Demo" for p in projects):
            call("POST", "/projects", {"name": "Orion Water Demo", "description": "Separate sample context for village water tank sensors, pump scheduling, and water level alerts.", "workspace_id": "ws_default"})
        entries = [
            {"speaker": "SPEAKER_00", "text": "For Harbor Inventory Demo, we have decided to use PostgreSQL as the primary inventory database."},
            {"speaker": "SPEAKER_01", "text": "Harbor Inventory Demo requires stock movement audit logs and low-stock alerts for warehouse managers."},
            {"speaker": "SPEAKER_02", "text": "I will build the Harbor Inventory Demo stock dashboard by 30 October 2026."},
            {"speaker": "SPEAKER_00", "text": "The Harbor Inventory Demo API will use FastAPI and expose authenticated endpoints for inventory adjustments."},
            {"speaker": "SPEAKER_01", "text": "We must block shipping in Harbor Inventory Demo until inventory reconciliation passes."},
            {"speaker": "SPEAKER_02", "text": "The Harbor Inventory Demo frontend will use React. A warehouse manager must approve every manual stock correction."},
        ]
        transcript = ROOT / "SAMPLE_ADMIN_MEETING_TRANSCRIPT.txt"
        transcript.write_text("\n".join(e["speaker"] + ": " + e["text"] for e in entries) + "\n", encoding="utf-8")
        meeting_title = "Harbor Inventory Demo - sample admin acceptance meeting"
        meetings = call("GET", "/meetings")
        existing_meeting = next((m for m in meetings if m["title"] == meeting_title and m["project_id"] == project_id), None)
        if existing_meeting:
            meeting_id = existing_meeting["id"]
            call("POST", f"/projects/{project_id}/meetings/{meeting_id}/process")
        else:
            meeting = call("POST", "/meetings/ingest-transcript", {"project_id": project_id, "title": meeting_title, "entries": entries, "auto_process": True})
            assert meeting.get("pipeline_result"), "Meeting persisted but automatic processing did not return a result."
            meeting_id = meeting["meeting_id"]
        call("GET", "/meetings/" + meeting_id)
        call("GET", f"/projects/{project_id}/meetings/{meeting_id}/intelligence")
        knowledge = call("GET", f"/projects/{project_id}/knowledge")
        assert any(item.get("evidence_ids") for item in knowledge), "No provenance-linked candidate knowledge was produced."
        proposals = call("GET", f"/projects/{project_id}/state/proposals")
        # Approve only the synthetic meeting's proposals to verify canonical memory.
        for proposal in proposals:
            state = call("GET", f"/projects/{project_id}/state")
            if proposal["state_version_before"] != state["current_version"]:
                results.append({"request": "Stale proposal remains pending for re-evaluation", "status": "EXPECTED_REVIEW", "data": {"proposal_id": proposal["id"], "proposed_version": proposal["state_version_before"], "current_version": state["current_version"]}})
                continue
            call("POST", f"/projects/{project_id}/state/proposals/{proposal['id']}/approve", {"actor_id": current_user["id"], "note": "Approve synthetic sample meeting acceptance data."})
        context = "Harbor Inventory Demo requires supplier delivery CSV import with a preview before committing stock adjustments."
        call("POST", "/connectors/manual/text", {"project_id": project_id, "title": "Sample admin project context", "text": context})
        duplicate = call("POST", "/connectors/manual/text", {"project_id": project_id, "title": "Sample admin duplicate context", "text": context})
        assert duplicate.get("outcome") == "duplicate", "Repeated context was not deduplicated."
        call("POST", "/connectors/manual/upload", files={"file": ("harbor-context.txt", b"Harbor Inventory Demo requires the audit log to retain a reference to the original supplier delivery CSV.", "text/plain")}, data={"project_id": project_id, "title": "Sample context file"})
        call("GET", f"/projects/{project_id}/memory/briefing")
        state = call("GET", f"/projects/{project_id}/state")
        assert state["current_version"] > 1, "Approved memory did not advance its canonical version."
        call("GET", f"/projects/{project_id}/state/history")
        call("POST", f"/projects/{project_id}/agent/sync-excalidraw")
        artifact = call("GET", f"/projects/{project_id}/excalidraw")
        assert artifact.get("elements"), "Canvas artifact is empty."
        call("GET", "/workspace/atlas")
        call("GET", "/projects")
    except Exception as exc:
        results.append({"request": "Acceptance assertion", "status": "FAIL", "data": str(exc)})
        print(type(exc).__name__, str(exc), flush=True)
    finally:
        lines = ["# Sample admin live pipeline report", "", "Time: " + datetime.now(timezone.utc).isoformat(), "", "Frontend: https://synora-frontend.onrender.com", "", "Backend: " + API, "", "Sample credentials: local ignored `.env.sample-admin` (excluded from this report).", "", "| Request | HTTP status | Seconds |", "| --- | --- | --- |"]
        for result in results:
            lines.append(f"| {result['request']} | {result['status']} | {result.get('seconds', '-')} |")
        lines += ["", "## Responses", ""]
        for result in results:
            lines += ["### " + result["request"], "", "```json", json.dumps(result["data"], ensure_ascii=True, indent=2), "```", ""]
        REPORT.write_text("\n".join(lines), encoding="utf-8")
        print("Report:", REPORT, flush=True)
    return 1 if any(r["status"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

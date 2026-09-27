import requests

BASE = "http://localhost:8000"
headers = {"X-User-ID": "usr_synesis_default"}

# 1. System Health
r = requests.get(f"{BASE}/health")
assert r.status_code == 200, f"Health failed: {r.text}"
print("[PASS] 1. System Health:", r.json()["status"])

# 2. Project State
r = requests.get(f"{BASE}/projects/proj_default/state", headers=headers)
assert r.status_code == 200, f"Project state failed: {r.text}"
state = r.json()
print("[PASS] 2. Project State: v" + str(state["current_version"]) + " for " + state["project_id"])

# 3. Meetings List
r = requests.get(f"{BASE}/meetings", headers=headers)
assert r.status_code == 200
meetings = r.json()
print(f"[PASS] 3. Meetings List: {len(meetings)} meeting(s) retrieved")

# 4. Ingest Transcript & Auto-Pipeline Execution
r = requests.post(
    f"{BASE}/meetings/ingest-transcript",
    headers=headers,
    json={
        "project_id": "proj_default",
        "title": "End-to-End Loop Validation Meeting",
        "provider": "google",
        "raw_transcript": "CTO: We have decided to enforce strict PostgreSQL row level security.\nSecurity Lead: Confirmed. All customer tenant data must be completely partitioned.",
        "auto_process": True
    }
)
assert r.status_code == 200, f"Ingest failed: {r.text}"
res = r.json()
print(f"[PASS] 4. Transcript Ingest & Extraction: Ingested {res['entries_count']} entries (Meeting ID: {res['meeting_id']})")

# 5. Check Proposals Created
r = requests.get(f"{BASE}/projects/proj_default/state/proposals", headers=headers)
assert r.status_code == 200
proposals = r.json()
print(f"[PASS] 5. State Change Proposals: {len(proposals)} proposal(s) available")

# 6. Excalidraw Living Workspace
r = requests.get(f"{BASE}/projects/proj_default/excalidraw", headers=headers)
assert r.status_code == 200
art = r.json()
elements_count = len(art.get("elements", []))
print(f"[PASS] 6. Excalidraw Visual Architecture: Artifact v{art['version']} ({elements_count} visual elements)")

# 7. AI Workforce Coordinator Briefing
r = requests.get(f"{BASE}/projects/proj_default/agents/coordinator-briefing", headers=headers)
assert r.status_code == 200
briefing = r.json()
print(f"[PASS] 7. AI Workforce Coordinator Briefing: {briefing['project_title']} | Status: {briefing['status']}")


# 8. WhatsApp Simulated Ingestion & Intent Filter
# Test 8a: Casual banter / Chit-chat filtering (Should be ignored safely)
r_chitchat = requests.post(
    f"{BASE}/connectors/whatsapp/simulate",
    headers=headers,
    json={
        "sender_jid": "919876543210@s.whatsapp.net",
        "sender_name": "Marcus Lead",
        "group_name": "Synesis Project",
        "text": "ok sounds good thanks"
    }
)
assert r_chitchat.status_code == 200
assert r_chitchat.json()["processed"] is False
print("[PASS] 8a. WhatsApp Chit-Chat Filter: Correctly ignored casual banter ('ok sounds good thanks')")

# Test 8b: Project Architectural Decision & Living Whiteboard Sync
r_match = requests.post(
    f"{BASE}/connectors/whatsapp/simulate",
    headers=headers,
    json={
        "sender_jid": "919876543210@s.whatsapp.net",
        "sender_name": "Marcus Lead",
        "group_name": "Synesis Project",
        "text": "In Synesis Project, we decided to deploy Redis for sub-millisecond caching."
    }
)
assert r_match.status_code == 200
wa_res = r_match.json()
assert wa_res["processed"] is True
print(f"[PASS] 8b. WhatsApp Architectural Ingestion: Matched '{wa_res['matched_project']['name']}' ({int(wa_res['confidence']*100)}% conf) | Whiteboard Updated={wa_res['excalidraw_updated']} (v{wa_res['artifact_version']})")


# 9. Frontend SSR & Shell Response
r_ui = requests.get("http://localhost:3000")
assert r_ui.status_code == 200
print(f"[PASS] 9. Frontend Next.js 14 UI: HTTP 200 OK ({len(r_ui.text)} bytes rendered)")

print("\n=======================================================")
print("[SUCCESS] ALL 9 SYSTEM CAPABILITIES AND DATA FLOWS PASSING IN REAL LOOP")
print("=======================================================")


"""Write a source-backed report only after final snapshots and browser checks."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "artifacts/render_meeting_retest_20261018"
def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))

e = read("evaluation.json")
status = read("latest_status.json")
browser = read("browser_verification.json")
canvas = e["canvas_metadata"]
verification = canvas.get("verification", {})
healthy = (status.get("status") == "completed" and e["source_hashes_unchanged"]
           and not e["unknown_discussion_misfiled_entries"] and not e["active_candidate_scope_violations"]
           and not e["nimbus_in_current_harbor_memory"] and not e["nimbus_project_created"]
           and not e["pending_translation_entries"] and not e["indic_canvas_fields"] and not e["roman_canvas_fields"]
           and e["canvas_types"].get("arrow", 0) > 0 and e["note_block_types"].get("bullet", 0) > 0
           and browser.get("canvas_seen", {}).get("version") == e["canvas_version"] and not browser.get("error"))
verdict = "Functional output verified; semantic quality still requires review" if healthy else "PARTIAL / FAIL: see evaluation.json before treating this as a pass"
counts = e["session_counts"]
flagged = verification.get("unverified", [])
flag_text = "\n".join("- " + item.get("excerpt", "").replace("\n", " ") for item in flagged) or "- None flagged by the automated check. This is not proof of complete factual accuracy."
report = f"""# Render meeting retest — 18 October 2026

## Verdict

**{verdict}.** This verifies recovery of the saved Render meeting, not a fresh Vexa recording or a new diarization test.

- Meeting: `mtg_1e3590b49b4b`; recording: `250675296384`.
- Frontend: https://synora-frontend.onrender.com
- Backend: https://synora-oduz.onrender.com
- Backend code deployed: `3f11571588df37d64a11693eb8402a9a05075621`.
- Reasoning/translation fallback: `openai/gpt-oss-20b`. Sarvam still has no credits; it was not restored.

## Before and after

| Check | Before | Final saved result |
|---|---|---|
| Original transcript / evidence | 43 / 43 | {e['entry_count']} / {e['evidence_count']}, source hashes unchanged |
| English presentation | Translation missing; pending markers | {canvas.get('translation_pending_count')} pending canvas entries; no detected Indic or recognized Roman Hindi/Marathi in canvas text |
| Canvas | Deterministic; 39 elements | v{e['canvas_version']}, `{canvas.get('ai_status')}`, {e['canvas_elements']} elements |
| AI canvas batches | 0 | {canvas.get('batches_ai')} / {canvas.get('batches')} |
| Bullet notes / connectors | Stacked transcript fallback | {e['note_block_types'].get('bullet', 0)} bullet blocks; {e['canvas_types'].get('arrow', 0)} arrows |
| Session projection | No decisions / requirements / actions | {counts['decisions']} decisions, {counts['requirements']} requirements, {counts['action_items']} actions, {counts['open_questions']} questions |
| Known project evidence | 1 Harbor row; 42 unknown | {e['evidence_by_project'].get('proj_e42a80c4', 0)} Harbor; {e['evidence_by_project'].get('proj_unknown_context', 0)} unknown |
| Explicit unknown-project discussion | Not safely recognized | All {e['unknown_discussion_entries']} entries quarantined; misfiled: {len(e['unknown_discussion_misfiled_entries'])} |
| Current Harbor memory | v1, empty | v{e['memory_version']}; Nimbus contamination absent |
| Browser | User reported transcript-only output | Sign-in, workspace access, meeting and canvas returned 200; no JS exceptions; v{browser.get('canvas_seen', {}).get('version')} rendered |

## Fixes deployed

1. Independent English translation fallback after Sarvam quota failure, including recognized Roman Hindi/Marathi and regional English STT tags. Partial malformed model items no longer discard the valid batch.
2. Saved-transcript reanalysis without repeating STT or importing a fixture. Accepted translations are reused on routing retries.
3. Routing consumes English text, honors explicit project exclusions, and carries a project switch across short fragments until a known project is explicitly reintroduced.
4. Misplaced automatic assignments can be corrected. Derived candidates are superseded, affected claims are retracted into a new memory version, and prior versions remain available.
5. Short fragments and later rejection context are preserved for canvas planning. Meeting notes request concise English bullets and diagrams grounded in the actual discussion.
6. Project canvas sync consumes English evidence and reuses unchanged inputs, with a bounded retry window after fallback output.

## Honest findings during repair

The first fallback implementation rejected a whole translation batch because the provider returned bare empty strings for unclear fragments. A subsequent routing pass then incorrectly filed Nimbus budget/success/automation content under Harbor, and two Nimbus heading/sensor entries still slipped through a later pass. These were real failures discovered by auditing actual source IDs, not passing runs.

The final boundary test checks the entire 13-entry unknown discussion, not only the word “Nimbus.” Active candidate evidence scopes also agree with their assigned project. Incorrect derived rows remain in the historical ledger as superseded. No Nimbus project was initialized. Transcript/evidence content remained unchanged throughout.

## Remaining limits

- Automated canvas verification: {verification.get('verified')} / {verification.get('checked')} checked items; {verification.get('unverified_total', len(flagged))} flagged. This checks source overlap, not semantic proof. Flagged items:

{flag_text}

- Source STT contains ambiguous phrases such as “temporary sensor,” “Passed API,” and “inventory connection.” Generated diagrams and action classification still need human review; do not silently substitute the original script for captured speech.
- Manual review found a qualification error: the canvas says “No manual stock correction allowed,” while adjacent translated source fragments say **without warehouse-manager approval**. Treat this as an approval requirement, not an unconditional ban. The automated overlap check did not catch that loss of meaning. The exported scene is left unchanged so this report does not disguise the generated result.
- The dashboard deadline appears in the canvas, but the final structured action-item list is empty. Structured action extraction therefore remains incomplete. Repeated bullets across chronological batches are not distinct verified facts.
- Native-script and known phonetic markers are checked. A script detector cannot prove every Latin-script fragment is fluent English. The original transcript intentionally remains in its captured language.
- Decisions and requirements remain subject to the existing approval policy. This test did not force approval or claim that every extracted note became authoritative memory.
- Historical candidates from retries can overlap. The {e['candidate_count']} ledger rows are not a count of distinct verified facts; statuses: `{json.dumps(e['candidate_statuses'])}`.
- The initial canvas overview fits the full scene at a small zoom. Zoom in or use fullscreen to read individual notes. Layout remains dense across three chronological batches.
- No new call was joined and no fresh audio/STT/three-speaker diarization test was performed in this repair. The saved capture has generic speaker labels.
- Initial browser verification timed out during deployment; the final stable browser verification passed. Free-tier availability and provider quotas are not guaranteed by one retest.

## Evidence and outputs

- [English notes](ENGLISH_NOTES.md): exported from actual canvas blocks with their section headings.
- [Excalidraw scene](meeting_canvas.excalidraw): exported from the live cached API response.
- [Rendered canvas screenshot](render_meeting_canvas.png), [intelligence screenshot](render_meeting_intelligence.png).
- [Evaluation](evaluation.json), [database audit before](audit-before.json), [database audit after](audit-after.json).
- [Original meeting snapshot](before_meeting.json), [final meeting snapshot](after_meeting.json), [English metadata](english_translations.json).
- [Final capture status](latest_status.json), [browser requests](browser_verification.json), [deployment verification](deployment_verified.json).
- [Focused tests](focused_tests.txt): **82 passed**, one existing Starlette/httpx deprecation warning. External provider calls are mocked in unit tests; the live outputs above are separate evidence.

## View it

Open Synora → Meetings → the captured Google Meet → **Meeting Canvas**. Use **Meeting Intelligence** for the source transcript and extracted candidates. Nimbus material belongs in Unknown Context until you explicitly initialize or assign that project.
"""
(OUT / "REPORT.md").write_text(report, encoding="utf-8")
print(json.dumps({"report": str(OUT / "REPORT.md"), "functional_checks_pass": healthy, "canvas_version": e["canvas_version"], "flagged_items": len(flagged)}))

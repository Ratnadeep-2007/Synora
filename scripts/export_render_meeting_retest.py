"""Export only the saved live response and database audit; no synthetic evidence."""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/render_meeting_retest_20261018"


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def main():
    before, after = read("audit-before.json"), read("audit-after.json")
    artifact = read("after_canvas.json")["artifact"]
    elements = [element for element in artifact["elements"] if not element.get("isDeleted")]
    meta = artifact["app_state"].get("meeting_canvas", {})
    intelligence = read("after_intelligence.json")
    texts = [element for element in elements if element["type"] == "text"]
    translations = []
    pending = []
    roman = re.compile(r"\b(?:chahiye|chaiye|dikha(?:yega|ayega)|honne|turanth|pahije|aahe|aapan|karunga|karenge|banayenge|banaunga)\b", re.I)
    for entry in after["entries"]:
        item_meta = json.loads(entry["metadata_json"] or "{}")
        english = item_meta.get("text_en") or ""
        translations.append({"id": entry["id"], "source": entry["text"], "english": english})
        if item_meta.get("translation_required") and not english:
            pending.append(entry["id"])
    scene = {"type": "excalidraw", "version": 2, "source": "Synora Render live cached meeting canvas API",
             "elements": artifact["elements"], "appState": artifact["app_state"], "files": {}}
    (OUT / "meeting_canvas.excalidraw").write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "english_translations.json").write_text(json.dumps(translations, ensure_ascii=False, indent=2), encoding="utf-8")
    notes = ["# Notes from the deployed meeting canvas", "", "Exported from the actual Render scene; these are generated notes, not approved project memory.", ""]
    block_counts = Counter()
    note_elements = [element for element in texts if ((element.get("customData") or {}).get("visual") or {}).get("type") in {"note_block", "note_section_header"}]
    for element in sorted(note_elements, key=lambda item: (item.get("y", 0), item.get("x", 0))):
        visual = (element.get("customData") or {}).get("visual") or {}
        if visual.get("type") == "note_section_header":
            notes += ["## " + " ".join(element["text"].split()), ""]
        if visual.get("type") == "note_block":
            block_counts[visual.get("block_type")] += 1
            notes += ["- " + " ".join(element["text"].split()), ""]
    (OUT / "ENGLISH_NOTES.md").write_text("\n".join(notes), encoding="utf-8")
    contamination = []
    scopes = {row["id"]: row["project_id"] for row in after["evidence"]}
    scope_violations = []
    for candidate in after["candidates"]:
        if candidate["status"] not in {"superseded", "rejected"}:
            references = json.loads(candidate["evidence_ids_json"] or "[]")
            if any(scopes.get(reference) != candidate["project_id"] for reference in references):
                scope_violations.append(candidate["id"])
        if candidate["status"] not in {"superseded", "rejected"} and candidate["project_id"] == "proj_e42a80c4" and "nimbus" in (candidate["title"] + candidate["content"]).lower():
            contamination.append(candidate["id"])
    original = read("before_meeting.json")
    ordered = sorted([entry for transcript in original["transcripts"] for entry in transcript["entries"]], key=lambda entry: entry.get("start_time") or "")
    start = next(index for index, entry in enumerate(ordered) if entry["text"].lower().startswith("now switching to different project"))
    end = next(index for index, entry in enumerate(ordered) if index > start and entry["text"].lower().startswith("harbor inventory demo"))
    destinations = {row["transcript_entry_id"]: row["project_id"] for row in after["evidence"]}
    unknown_misfiled = [entry["id"] for entry in ordered[start:end] if destinations.get(entry["id"]) != "proj_unknown_context"]
    summary = {
        "source_hashes_unchanged": before["source_hashes"] == after["source_hashes"],
        "entry_count": len(after["entries"]), "evidence_count": len(after["evidence"]),
        "evidence_by_project": dict(Counter(row["project_id"] for row in after["evidence"])),
        "unknown_by_status": dict(Counter(row["status"] for row in after["unknown"])),
        "candidate_count": len(after["candidates"]),
        "candidate_statuses": dict(Counter(row["status"] for row in after["candidates"])),
        "candidate_categories": dict(Counter(row["category"] for row in after["candidates"])),
        "session_counts": {key: len(intelligence.get(key, [])) for key in ("decisions", "requirements", "action_items", "open_questions")},
        "memory_version": after["states"][0]["current_version"],
        "canvas_version": artifact["version"], "canvas_elements": len(elements),
        "canvas_types": dict(Counter(element["type"] for element in elements)), "canvas_metadata": meta,
        "note_block_types": dict(block_counts),
        "indic_canvas_fields": [e["id"] for e in texts if re.search(r"[\u0900-\u097f]", e["text"])],
        "roman_canvas_fields": [e["id"] for e in texts if roman.search(e["text"])],
        "pending_translation_entries": pending,
        "missing_fixed_text_dimensions": [e["id"] for e in texts if e.get("autoResize") is not False or not e.get("width") or not e.get("height")],
        "nimbus_candidates_in_harbor": contamination,
        "active_candidate_scope_violations": scope_violations,
        "unknown_discussion_entries": end - start,
        "unknown_discussion_misfiled_entries": unknown_misfiled,
        "nimbus_in_current_harbor_memory": "nimbus" in json.dumps(after["states"]).lower(),
        "nimbus_project_created": any("nimbus" in project["name"].lower() for project in after["projects"]),
    }
    (OUT / "evaluation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "canvas_metadata"}))


if __name__ == "__main__":
    main()

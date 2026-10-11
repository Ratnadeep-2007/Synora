#!/usr/bin/env python3
"""Synora reset-retest helper: fresh randomized fixtures + wipe verification.

Never the same twice: project names, domains, speaker turns, and timestamps
are randomized per run. The seed is printed so a run is reproducible after
the fact, but never identical beforehand.

Examples:
  python scripts/reset_retest.py --list-mediqueue --db ..\\..\\..\\synora.db
  python scripts/reset_retest.py --verify-wipe proj_XXX --db ..\\..\\..\\synora.db
  python scripts/reset_retest.py --new-fixture --speakers 4 --utterances 18 --seed 123
"""
import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WIPE_TABLES_PROJECT = [
    ("evidence", "project_id"),
    ("candidate_knowledge", "project_id"),
    ("agent_runs", "project_id"),
    ("agent_executions", "project_id"),
    ("conflicts", "project_id"),
    ("context_resolutions", "project_id"),
    ("source_events", "project_id"),
    ("task_jobs", "project_id"),
    ("meet_event_records", "project_id"),
    ("meet_subscriptions", "project_id"),
    ("project_domain_profiles", "project_id"),
    ("meetings", "project_id"),
    ("visual_workspaces", "project_id"),
    ("visual_patches", "project_id"),
    ("project_states", "project_id"),
    ("project_semantic_profiles", "project_id"),
    ("excalidraw_artifacts", "project_id"),
    ("projects", "id"),
]

DOMAINS = [
    ("MediQueue", "Hospital outpatient queue management", [
        "numbered tokens with live position tracking",
        "paper plus digital QR tokens",
        "trilingual kiosk interface",
        "ten percent priority quota per hour",
        "SMS alerts at five tokens away",
        "offline kiosk queue with server sync",
    ]),
    ("CampusAttend", "College attendance with face recognition", [
        "face recognition for lecture halls",
        "proxy attendance detection",
        "HOD daily summary email",
        "offline classroom buffer",
        "privacy-preserving embeddings only",
    ]),
    ("CafeFlow", "Cafe ordering via WhatsApp and QR", [
        "QR table ordering",
        "kitchen display tickets in realtime",
        "POS settlement consistency",
        "peak-hour throttling",
    ]),
    ("FleetTrack", "Delivery fleet live tracking", [
        "driver live positions every 10 seconds",
        "geofence arrival alerts",
        "offline GPS buffer with replay",
        "customer ETA SMS",
    ]),
]

CASUAL = [
    "My chai is getting cold, anyway moving on.",
    "Can everyone hear me? My network dropped yesterday.",
    "Sorry, was on mute. Going again.",
]

UNKNOWN_PROBE = "Do penguins prefer room temperature server rooms?"


def list_mediqueue(db_path: Path):
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT id, name, created_at FROM projects WHERE name LIKE '%medique%' COLLATE NOCASE ORDER BY created_at"
        ).fetchall()
    except Exception as exc:
        print(f"ERROR listing projects: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()
    if not rows:
        print("No MediQueue versions found.")
        return 0
    print(f"Found {len(rows)} MediQueue version(s):")
    for pid, name, created in rows:
        print(f"  {pid} | {name} | {created}")
    print("Confirm these IDs with the user before any delete. Never delete system projects.")
    return 0


def verify_wipe(db_path: Path, project_id: str):
    con = sqlite3.connect(str(db_path))
    leftover = {}
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for table, col in WIPE_TABLES_PROJECT:
            if table not in tables:
                print(f"  {table:28} (no such table, skipped)")
                continue
            try:
                n = con.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{col}"=?', (project_id,)
                ).fetchone()[0]
            except Exception as exc:
                print(f"  {table:28} ERROR: {exc}")
                continue
            print(f"  {table:28} {n}")
            if n:
                leftover[table] = n
    finally:
        con.close()
    if leftover:
        print(f"WIPE INCOMPLETE: {len(leftover)} table(s) still hold rows for {project_id}")
        return 2
    print(f"WIPE CLEAN: zero rows for {project_id}")
    return 0


def new_fixture(speakers: int, utterances: int, seed=None):
    rng = random.Random(seed if seed is not None else int(datetime.now().timestamp() * 1000) % (2 ** 31))
    actual_seed = seed if seed is not None else rng.randint(1, 999999)
    rng = random.Random(actual_seed)
    domain_name, domain_desc, topics = rng.choice(DOMAINS)
    stamp = datetime.now(timezone.utc).strftime("%m%d-%H%M")
    suffix = "".join(rng.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(4))
    project = {
        "name": f"{domain_name}-{stamp}-{suffix}",
        "description": f"{domain_desc} (reset-retest seed {actual_seed})",
        "workspace_id": "ws_default",
    }
    labels = [f"SPEAKER_{i:02d}" for i in range(speakers)]
    decisions = [f"Decision: {t} for the pilot." for t in rng.sample(topics, min(3, len(topics)))]
    requirements = [
        f"The system must handle {rng.choice([100, 500, 1000])} {rng.choice(['tokens', 'check-ins', 'orders'])} per day.",
        f"Requirement: automated daily report with {rng.choice(['wait times', 'attendance', 'sales'])} metrics.",
    ]
    questions = [
        "Which provider do we use for SMS alerts, and who pays per message?",
        "Do we need health-ID integration in phase one or phase two?",
    ]
    pool = decisions + requirements + questions + CASUAL + [UNKNOWN_PROBE]
    base = datetime.now(timezone.utc).replace(microsecond=0)
    total_span = 30 * 60
    entries = []
    cursor = base
    for i in range(utterances):
        text = rng.choice(pool)
        speaker = rng.choice(labels)
        dur = rng.randint(10, 20)
        start = cursor
        end = cursor + timedelta(seconds=dur)
        entries.append({
            "speaker": speaker,
            "text": text,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        })
        gap = max(4, (total_span - utterances * 15) // max(utterances, 1))
        cursor = end + timedelta(seconds=rng.randint(4, gap + 8))
    fixture = {
        "seed": actual_seed,
        "project": project,
        "meeting": {
            "title": f"{project['name']} planning - {speakers} member review",
            "provider": "google_meet",
            "entries": entries,
            "auto_process": True,
        },
    }
    out = Path(f"reset-fixture-{actual_seed}.json")
    out.write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    print(f"seed={actual_seed} project={project['name']} entries={len(entries)} speakers={speakers}")
    print(f"wrote {out.resolve()}")
    print("Next: POST /projects, then POST /meetings/ingest-transcript with meeting payload.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Synora reset-retest helper (dry-run safe).")
    ap.add_argument("--db", default="synora.db")
    ap.add_argument("--list-mediqueue", action="store_true")
    ap.add_argument("--verify-wipe", metavar="PROJECT_ID")
    ap.add_argument("--new-fixture", action="store_true")
    ap.add_argument("--speakers", type=int, default=4)
    ap.add_argument("--utterances", type=int, default=18)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    if args.list_mediqueue:
        return list_mediqueue(Path(args.db))
    if args.verify_wipe:
        return verify_wipe(Path(args.db), args.verify_wipe)
    if args.new_fixture:
        return new_fixture(args.speakers, args.utterances, args.seed)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

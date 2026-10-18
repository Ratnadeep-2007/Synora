"""Live repair retest. Credentials are read privately; source snapshots stay local."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/render_meeting_retest_20261018"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://synora-oduz.onrender.com"
ORIGIN = "https://synora-frontend.onrender.com"
MEETING = "mtg_1e3590b49b4b"
SERVICE = "srv-db85cm5g1s2s7393sd20"


def env_file(name):
    result = {}
    for line in (ROOT / name).read_text(encoding="utf-8-sig").splitlines():
        if re.match(r"^[A-Z_]+=", line):
            key, value = line.split("=", 1)
            result[key] = value.strip().strip("\"'")
    return result


def render_headers():
    raw = (Path.home() / ".render/cli.yaml").read_text()
    key = re.search(r"^\s+key:\s*(\S+)", raw, re.M).group(1)
    return {"Authorization": "Bearer " + key}


def auth_headers():
    credentials = env_file(".env.sample-admin")
    config = env_file(".env.vexa-live-test")
    response = requests.post(config["NEON_AUTH_BASE_URL"] + "/sign-in/email", headers={"Origin": ORIGIN},
        json={"email": credentials["SAMPLE_ADMIN_EMAIL"], "password": credentials["SAMPLE_ADMIN_PASSWORD"]}, timeout=45)
    response.raise_for_status()
    return {"Origin": ORIGIN, "Authorization": "Bearer " + response.json()["token"]}


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["model", "deploy", "start", "status", "snapshot", "audit-before", "audit-after"])
    args = parser.parse_args()
    if args.action.startswith("audit-"):
        from sqlalchemy import create_engine, text
        response = requests.get(f"https://api.render.com/v1/services/{SERVICE}/env-vars?limit=100", headers=render_headers(), timeout=45)
        response.raise_for_status()
        config = {item["envVar"]["key"]: item["envVar"]["value"] for item in response.json()}
        url = config["DATABASE_URL"].replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            queries = {
                "entries": "SELECT e.id, e.text, e.language_code, e.metadata_json FROM transcript_entries e JOIN transcripts t ON e.transcript_id=t.id WHERE t.meeting_id=:meeting ORDER BY e.id",
                "evidence": "SELECT id, content, project_id, transcript_entry_id, metadata_json FROM evidence WHERE meeting_id=:meeting ORDER BY id",
                "candidates": "SELECT id, project_id, category, classification, title, content, evidence_ids_json, status FROM candidate_knowledge WHERE meeting_id=:meeting ORDER BY created_at",
                "unknown": "SELECT u.id, u.evidence_id, u.status, u.assigned_project_id FROM unknown_context_items u JOIN evidence e ON e.id=u.evidence_id WHERE e.meeting_id=:meeting",
                "states": "SELECT project_id, current_version, requirements_json, architecture_json, decisions_json, constraints_json, assumptions_json, open_questions_json FROM project_states WHERE project_id='proj_e42a80c4'",
                "projects": "SELECT id,name FROM projects",
            }
            result = {name: [dict(row) for row in conn.execute(text(sql), {"meeting": MEETING}).mappings()] for name, sql in queries.items()}
            result["source_hashes"] = {name: hashlib.sha256(json.dumps([(row["id"], row[field]) for row in result[name]], ensure_ascii=False).encode()).hexdigest() for name, field in (("entries", "text"), ("evidence", "content"))}
            save(args.action + ".json", result)
            print(json.dumps({"audit": args.action, "counts": {key: len(value) for key, value in result.items() if isinstance(value, list)}, "hashes": result["source_hashes"]}))
        engine.dispose()
        return
    if args.action in {"model", "deploy"}:
        headers = render_headers()
        if args.action == "model":
            response = requests.put(f"https://api.render.com/v1/services/{SERVICE}/env-vars/GROQ_MODEL", headers=headers,
                                     json={"value": "openai/gpt-oss-20b"}, timeout=45)
            response.raise_for_status()
            print(json.dumps({"updated": "GROQ_MODEL", "value": "openai/gpt-oss-20b", "status": response.status_code}))
        else:
            for service in (SERVICE, "srv-db860bgm7kps73d74ffg"):
                response = requests.get(f"https://api.render.com/v1/services/{service}/deploys?limit=1", headers=headers, timeout=45)
                response.raise_for_status()
                deploy = response.json()[0]["deploy"]
                print(json.dumps({"service": service, "status": deploy["status"], "commit": deploy.get("commit", {}).get("id"), "deploy": deploy["id"]}))
        return
    headers = auth_headers()
    if args.action == "start":
        response = requests.post(f"{BASE}/vexa/meetings/{MEETING}/reanalyze", headers=headers, timeout=90)
        print(json.dumps({"http": response.status_code, "body": response.json()}))
        save("reanalysis_receipt.json", response.json())
        response.raise_for_status()
    elif args.action == "status":
        response = requests.get(f"{BASE}/vexa/meetings/{MEETING}", headers=headers, timeout=45)
        response.raise_for_status()
        value = response.json()
        save("latest_status.json", value)
        print(json.dumps(value))
    else:
        for name, endpoint in {
            "meeting": f"/meetings/{MEETING}", "intelligence": f"/meetings/{MEETING}/intelligence",
            "canvas": f"/meetings/{MEETING}/canvas", "projects": "/projects",
            "harbor_state": "/projects/proj_e42a80c4/state",
            "harbor_candidates": "/projects/proj_e42a80c4/intelligence/candidates",
        }.items():
            response = requests.get(BASE + endpoint, headers=headers, timeout=90)
            response.raise_for_status()
            value = response.json()
            save("after_" + name + ".json", value)
            print(json.dumps({"snapshot": name, "bytes": len(response.content), "http": response.status_code}))
        save("checked_at.json", {"utc": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    main()

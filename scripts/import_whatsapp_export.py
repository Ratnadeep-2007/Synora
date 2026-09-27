#!/usr/bin/env python3
"""
Bulk WhatsApp Chat Export Importer for Synora.

Parses WhatsApp chat export archives (.zip or .txt), extracts messages,
associates media attachments (voice notes .opus, diagrams/screenshots .png/.jpg),
and streams them into Synora for Context Intelligence, Knowledge Extraction,
and Living Workspace (Excalidraw) proposals.

Usage:
    # 1. Quick dry-run inspection (no database changes):
    python scripts/import_whatsapp_export.py --dry-run

    # 2. Test the first 25 messages via live running API (http://localhost:8000):
    python scripts/import_whatsapp_export.py --limit 25

    # 3. Import chat targeting a specific project:
    python scripts/import_whatsapp_export.py --target-project proj_default --limit 50

    # 4. Ingest with multimodal audio (Groq Whisper) and images (Llama Vision):
    python scripts/import_whatsapp_export.py --include-media --limit 30

    # 5. Full in-process direct database ingestion (fastest):
    python scripts/import_whatsapp_export.py --mode direct
"""

import argparse
import base64
from datetime import datetime, timezone
import functools
import json
from pathlib import Path
import re
import sys
import time
import urllib.request
import zipfile
from typing import Any, Dict, List, Optional, Tuple

print = functools.partial(print, flush=True)

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

try:
    from app.services.whatsapp_export_parser import WhatsAppZipParser
except ImportError:
    pass


# WhatsApp timestamp matching pattern
# Examples: "7/8/26, 10:13 AM - Varun: Message" or "08/07/2026, 22:13 - Varun: Message"
LINE_PATTERN = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s+[AP]M)?)\s*-\s*([^:]+):\s*(.*)$",
    re.IGNORECASE,
)

SYSTEM_PATTERNS = [
    "Messages and calls are end-to-end encrypted",
    "created group",
    "added you",
    "changed the subject",
    "changed this group's icon",
    "left",
    "joined using this group's invite link",
]


class WhatsAppZipParser:
    """Extracts messages and attachments from an exported WhatsApp .zip archive."""

    def __init__(self, zip_path: Path):
        self.zip_path = zip_path
        if not self.zip_path.exists():
            raise FileNotFoundError(f"WhatsApp zip file not found: {zip_path}")
        self.zf = zipfile.ZipFile(self.zip_path, "r")
        self.file_list = set(self.zf.namelist())

        # Locate the chat text file
        txt_candidates = [n for n in self.file_list if n.endswith(".txt")]
        if not txt_candidates:
            raise ValueError(f"No .txt chat export found inside {zip_path}")
        self.txt_filename = txt_candidates[0]

    def parse_messages(self) -> List[Dict[str, Any]]:
        with self.zf.open(self.txt_filename) as f:
            raw_content = f.read().decode("utf-8", errors="ignore")

        messages: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None

        for line in raw_content.splitlines():
            clean = line.replace("\u202f", " ").replace("\xa0", " ").strip()
            if not clean:
                continue

            match = LINE_PATTERN.match(clean)
            if match:
                if current:
                    messages.append(current)
                ts_str, sender, content = match.groups()
                sender = sender.strip()

                # Filter out WhatsApp system notifications
                if any(sp.lower() in content.lower() for sp in SYSTEM_PATTERNS):
                    current = None
                    continue

                current = {
                    "raw_timestamp": ts_str,
                    "sender": sender,
                    "text": content.strip(),
                    "attachment": None,
                }
            elif current:
                # Continuation of multiline message
                current["text"] += "\n" + clean

        if current:
            messages.append(current)

        # Match referenced attachments
        for msg in messages:
            text = msg["text"]
            for fn in self.file_list:
                if fn == self.txt_filename:
                    continue
                if fn in text or f"{fn} (file attached)" in text:
                    msg["attachment"] = fn
                    break

        return messages

    def read_attachment_bytes(self, filename: str) -> Optional[bytes]:
        if filename in self.file_list:
            with self.zf.open(filename) as f:
                return f.read()
        return None


def run_import(
    zip_path: Path,
    target_project: Optional[str] = None,
    limit: Optional[int] = None,
    include_media: bool = False,
    mode: str = "api",
    api_url: str = "http://localhost:8000/connectors/whatsapp/webhook",
    delay: float = 0.05,
    dry_run: bool = False,
) -> None:
    print(f"\n==============================================================================")
    print(f"               SYNORA BULK WHATSAPP CHAT EXPORT IMPORTER                      ")
    print(f"==============================================================================")
    print(f" Archive:        {zip_path.name}")
    print(f" Target Project: {target_project or 'Auto-Detect (Context Intelligence)'}")
    print(f" Limit:          {limit or 'All messages'}")
    print(f" Media Analysis: {'Enabled (Groq Whisper + Llama Vision)' if include_media else 'Text only'}")
    print(f" Execution Mode: {mode.upper()} {'(DRY RUN - No DB writes)' if dry_run else ''}")
    print(f"==============================================================================\n")

    parser = WhatsAppZipParser(zip_path)
    messages = parser.parse_messages()
    print(f" Found {len(messages)} chat messages inside '{parser.txt_filename}'.")

    if limit and limit > 0:
        messages = messages[:limit]
        print(f" Processing first {limit} messages as requested.\n")

    if dry_run:
        print("Dry run summary:")
        media_count = sum(1 for m in messages if m["attachment"])
        audio_count = sum(
            1 for m in messages if m["attachment"] and m["attachment"].endswith((".opus", ".ogg"))
        )
        img_count = sum(
            1
            for m in messages
            if m["attachment"]
            and m["attachment"].endswith((".jpg", ".png", ".jpeg", ".webp"))
        )
        print(f" - Total messages in batch: {len(messages)}")
        print(f" - Attachments referenced:  {media_count} (Voice notes: {audio_count}, Images: {img_count})")
        print("\nSample message:")
        if messages:
            print(f"   [{messages[0]['raw_timestamp']}] {messages[0]['sender']}: {messages[0]['text'][:80]}")
        print("\n[DRY RUN COMPLETE] Use without --dry-run to execute ingestion.")
        return

    # Direct mode setup
    direct_service = None
    direct_db = None
    if mode == "direct":
        from app.core.database import SessionLocal, init_db
        from app.services.whatsapp_service import WhatsAppIntelligenceService
        init_db()
        direct_db = SessionLocal()
        direct_service = WhatsAppIntelligenceService()

    success_count = 0
    unknown_count = 0
    decision_proposals = 0
    audio_transcriptions = 0
    images_analyzed = 0

    t_start = time.time()

    for idx, msg in enumerate(messages, 1):
        sender = msg["sender"]
        text = msg["text"]
        attachment = msg["attachment"]

        # Append explicit project tag if specified
        if target_project:
            text = f"[{target_project}] {text}"

        sender_jid = f"{re.sub(r'[^a-zA-Z0-9]', '', sender).lower() or 'user'}@s.whatsapp.net"
        message_id = f"wamid_bulk_{int(time.time()*1000)}_{idx}"

        payload: Dict[str, Any] = {
            "message_id": message_id,
            "sender_jid": sender_jid,
            "sender_name": sender,
            "group_jid": "120363025812345678@g.us",
            "group_name": "Trial Project",
            "text": text,
        }

        # Attach media if requested and present
        if include_media and attachment:
            raw_media = parser.read_attachment_bytes(attachment)
            if raw_media:
                b64 = base64.b64encode(raw_media).decode("utf-8")
                if attachment.endswith((".opus", ".ogg", ".mp3", ".m4a")):
                    payload["audio_base64"] = b64
                    payload["media_type"] = "audio"
                    payload["filename"] = attachment
                    audio_transcriptions += 1
                elif attachment.endswith((".jpg", ".png", ".jpeg", ".webp")):
                    payload["image_base64"] = b64
                    payload["media_type"] = "image"
                    payload["filename"] = attachment
                    images_analyzed += 1

        # Execute ingestion
        try:
            if mode == "direct" and direct_service and direct_db:
                result = direct_service.process_incoming_message(payload, direct_db)
            else:
                req = urllib.request.Request(
                    api_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    result = json.loads(resp.read().decode())

            status = result.get("status")
            matched = result.get("matched_project")
            proposal_pending = result.get("visual_proposal_pending")

            if status == "unknown_context":
                unknown_count += 1
                dest = "Unknown Context (Quarantine)"
            elif matched:
                dest = matched.get("name", matched.get("id"))
                success_count += 1
            else:
                dest = "Filtered / Duplicate"

            if proposal_pending:
                decision_proposals += 1

            clean_sender = sender.encode("ascii", "replace").decode("ascii")
            snippet = text.splitlines()[0][:45].encode("ascii", "replace").decode("ascii")
            print(f"[{idx:4d}/{len(messages)}] {clean_sender:<22} -> {dest:<30} ({snippet}...)")

            if delay > 0 and mode != "direct":
                time.sleep(delay)

        except Exception as exc:
            print(f"[{idx:4d}/{len(messages)}] Error ingesting message: {exc}")

    if direct_db:
        direct_db.close()

    elapsed = time.time() - t_start
    print(f"\n==============================================================================")
    print(f"                        INGESTION COMPLETE SUMMARY                            ")
    print(f"==============================================================================")
    print(f" Total Processed:          {len(messages)} messages in {elapsed:.1f}s")
    print(f" Project Matched:          {success_count}")
    print(f" Unknown Context (Triage): {unknown_count}")
    print(f" Visual Proposals Created: {decision_proposals}")
    if include_media:
        print(f" Audio Notes Processed:    {audio_transcriptions} (via Groq Whisper)")
        print(f" Diagrams/Images Analyzed: {images_analyzed} (via Llama 3.2 Vision)")
    print(f"==============================================================================\n")
    print(" View results in the Synora Web UI (http://localhost:3000):")
    print("  - Evidence tab: Inspect immutable chat provenance & messages")
    print("  - Unknown Context tab: Triage unresolved messages and assign to projects")
    print("  - Architecture tab: Review proposals generated from chat decisions\n")


def main() -> None:
    arg_parser = argparse.ArgumentParser(description="Bulk WhatsApp Chat Export Importer for Synora")
    arg_parser.add_argument(
        "--zip",
        type=Path,
        default=ROOT_DIR / "WhatsApp Chat with Trial Project.zip",
        help="Path to WhatsApp Chat .zip archive",
    )
    arg_parser.add_argument(
        "--target-project",
        type=str,
        default=None,
        help="Explicit project ID to target (e.g. proj_default)",
    )
    arg_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of messages to process (e.g. 25)",
    )
    arg_parser.add_argument(
        "--include-media",
        action="store_true",
        help="Extract & process voice notes (Groq Whisper) and whiteboard images (Llama Vision)",
    )
    arg_parser.add_argument(
        "--mode",
        choices=["api", "direct"],
        default="api",
        help="'api' streams to running backend; 'direct' writes directly to database",
    )
    arg_parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000/connectors/whatsapp/webhook",
        help="Backend webhook URL",
    )
    arg_parser.add_argument(
        "--delay",
        type=float,
        default=0.02,
        help="Delay in seconds between API requests",
    )
    arg_parser.add_argument(
        "--llm",
        action="store_true",
        help="Use external LLM semantic extraction (slower due to remote API calls)",
    )
    arg_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and print summary without ingesting",
    )

    args = arg_parser.parse_args()

    import os
    if not args.llm:
        # Use high-speed deterministic extraction for bulk imports
        os.environ["LLM_PROVIDER"] = "rule"
        try:
            from app.core.config import settings
            settings.LLM_PROVIDER = "rule"
        except Exception:
            pass

    run_import(
        zip_path=args.zip,
        target_project=args.target_project,
        limit=args.limit,
        include_media=args.include_media,
        mode=args.mode,
        api_url=args.api_url,
        delay=args.delay,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

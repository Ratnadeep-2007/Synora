import base64
import io
import logging
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import zipfile

logger = logging.getLogger(__name__)

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
    """Extracts messages and attachments from an exported WhatsApp .zip archive or byte buffer."""

    def __init__(self, source: Union[Path, str, bytes, io.BytesIO]):
        if isinstance(source, (str, Path)):
            p = Path(source)
            if not p.exists():
                raise FileNotFoundError(f"WhatsApp zip file not found: {p}")
            self.zf = zipfile.ZipFile(p, "r")
        elif isinstance(source, bytes):
            self.zf = zipfile.ZipFile(io.BytesIO(source), "r")
        elif isinstance(source, io.BytesIO):
            self.zf = zipfile.ZipFile(source, "r")
        else:
            raise TypeError(f"Unsupported source type for WhatsAppZipParser: {type(source)}")

        self.file_list = set(self.zf.namelist())

        # Locate the chat text file. WhatsApp always names it `_chat.txt`; prefer
        # that over any other .txt in the archive.
        txt_candidates = [n for n in self.file_list if n.endswith(".txt")]
        if not txt_candidates:
            raise ValueError("No .txt chat export file found inside the zip archive.")
        preferred = [
            n for n in txt_candidates if Path(n).name == "_chat.txt"
        ] or [
            n for n in txt_candidates if "whatsapp chat" in Path(n).name.lower()
        ]
        self.txt_filename = (preferred or txt_candidates)[0]

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

        # Match referenced attachments. WhatsApp references media by its base
        # filename (e.g. "PTT-20260912-WA0001.opus" or "<attached: ...>"), so
        # match on both the basename and the full archive path.
        for msg in messages:
            text = msg["text"]
            for fn in sorted(self.file_list, key=len, reverse=True):
                if fn == self.txt_filename:
                    continue
                basename = Path(fn).name
                if basename and basename in text:
                    msg["attachment"] = fn
                    break

        return messages

    def read_attachment_bytes(self, filename: str) -> Optional[bytes]:
        if filename in self.file_list:
            with self.zf.open(filename) as f:
                return f.read()
        return None

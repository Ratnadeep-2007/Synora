"""Repeatable checks for Synora's canonical enterprise architecture.

Dependency-free: runs in CI or locally. It guards the PRODUCT-FACING layers
(documentation and frontend) against regressing to the old multi-agent /
workforce architecture, and against re-introducing forbidden ingestion paths.

Backend shim note: ProjectAgent/WorkspaceAgent remain ONLY as labelled,
deprecated compatibility shims (additive migration decision). They are therefore
intentionally exempt from this scan, which targets user-visible and state-model
architecture rather than those compatibility records.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Directories scanned for product-facing architecture regressions.
SCAN_TARGETS = ("doc", "frontend/src", "SYNORA_COMPLETE_SYSTEM_ARCHITECTURE.md")

EXEMPT_DIRS = (".git", "node_modules", ".next", "dist", "build", "coverage")

FORBIDDEN_PATTERNS = {
    "multi-agent product framing": [
        "Workforce Agent",
        "AI Workforce",
        "Central Workspace Super-Agent",
        "Central Workspace Agent",
        "specialist_workforce",
        "BA Agent",
        "Project Planner Agent",
        "Functional Agent",
        "Tech Agent",
        "Frappe Agent",
    ],
    "sequential agent pipeline as architecture": [
        "BA \u2192 Project \u2192 Functional \u2192 Tech \u2192 Frappe",
        "BA -> Project -> Functional -> Tech -> Frappe",
    ],
    # Note: prose prohibitions such as "no raw audio capture" or "never request
    # meetings.conference.readonly" are legitimate documentation and are not
    # scanned for here. Actual enforcement lives in Settings.GOOGLE_OAUTH_SCOPES
    # validation and its tests.
    "forbidden Meet ingestion implementations": [
        "Tampermonkey",
        "synora-meet-captions.user.js",
        "faster-whisper",
    ],
}

CANONICAL_TEXT = (
    "one shared Synora Agent",
    "project-scoped context",
    "PostgreSQL",
    "NVIDIA NIM",
    "google.workspace.meet.transcript.v2.fileGenerated",
    "deterministic validation",
    "propose",
    "visual diff",
    "human approval",
)


def iter_text_files():
    """Yield files under the product-facing scan targets only."""
    for target in SCAN_TARGETS:
        base = ROOT / target
        if not base.exists():
            continue
        if base.is_file():
            yield base
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in EXEMPT_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in {".md", ".py", ".ts", ".tsx", ".json", ".yml", ".yaml"}:
                yield path


def main() -> int:
    files = list(iter_text_files())
    md_files = [p for p in files if p.suffix.lower() == ".md"]

    print(f"Scanned {len(files)} files under {', '.join(SCAN_TARGETS)}; {len(md_files)} markdown files.")

    failures = 0
    for label, patterns in FORBIDDEN_PATTERNS.items():
        hits = []
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern in patterns:
                if pattern in text:
                    hits.append((path.relative_to(ROOT), pattern))
        if hits:
            failures += 1
            print(f"[FAIL] {label}")
            for path, pattern in hits:
                print(f"  {path}: {pattern}")
        else:
            print(f"[OK] {label}")

    canonical_hits = []
    for path in md_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        canonical_hits.append(
            (path.relative_to(ROOT), sum(token.lower() in text for token in CANONICAL_TEXT))
        )

    print("\nMarkdown alignment coverage:")
    for path, count in canonical_hits:
        print(f"  {path}: {count}/{len(CANONICAL_TEXT)} canonical concepts present")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Repeatable checks for Synora's canonical enterprise architecture.

This script is intentionally dependency-free and can be run in CI or locally.
It verifies that the repository does not regress to multi-agent/workspace-agent
architecture, cloud-LLM-by-default settings, insecure database examples, or
Google Meet browser-scraper ingestion.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PATTERNS = {
    "workspace agent model": [
        "WorkspaceAgent",
        "workspace_agents",
        "Central Workspace Super-Agent",
    ],
    "per-project agent model": [
        "ProjectAgent",
        "project_agents",
        "ONE PROJECT = ONE LOGICAL PROJECT AGENT",
    ],
    "cloud LLM default": [
        'LLM_PROVIDER="nvidia"',
        'LLM_PROVIDER="groq"',
        "default="nvidia"",
        "NVIDIA_API_KEY=",
    ],
    "meet browser scraper": [
        "Tampermonkey",
        "synora-meet-captions.user.js",
        "faster-whisper",
        "raw audio capture",
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
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        if path.suffix.lower() in {".md", ".py", ".ts", ".tsx", ".json", ".yml", ".yaml", ".env"}:
            yield path


def main():
    files = list(iter_text_files())
    md_files = [p for p in files if p.suffix.lower() == ".md"]

    print(f"Scanned {len(files)} text files; {len(md_files)} markdown files.")

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


if __name__ == "__main__":
    main()

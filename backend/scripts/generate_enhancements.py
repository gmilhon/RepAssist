"""Regenerate the "What's new in Rep Assist" card from recent git commits.

Reads the repo's commit history since the last time this ran (tracked via
`last_commit_sha` in the output file), asks Claude to turn rep-visible changes
into plain-language enhancement cards (merging with what's already published),
and writes `app/mcp/enhancements_data.json` — which is checked into git so it
ships inside the Docker image and is available with zero setup in local dev.

Run manually:
    python scripts/generate_enhancements.py

Runs automatically on every `./deploy.sh` (see deploy.sh step 3.5), so the
card stays in sync with what actually shipped instead of a hand-maintained
mock list. Skips (leaves the existing file untouched) when no
ANTHROPIC_API_KEY is configured, or when there are no new commits — it never
overwrites good curated content with nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import llm  # noqa: E402
from app.config import get_settings  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUT_FILE = Path(__file__).resolve().parents[1] / "app" / "mcp" / "enhancements_data.json"
_MAX_COMMITS_FIRST_RUN = 40


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=_REPO_ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _current_sha() -> str:
    return _git("rev-parse", "HEAD")


def _commit_log(since_sha: str | None) -> str:
    fmt = "--pretty=format:%h %s%n%b%n---"
    if since_sha:
        return _git("log", f"{since_sha}..HEAD", fmt)
    return _git("log", f"-{_MAX_COMMITS_FIRST_RUN}", fmt)


def main() -> int:
    if not get_settings().llm_enabled:
        print("Skipping enhancements regeneration — no ANTHROPIC_API_KEY configured. "
              "Existing enhancements_data.json left unchanged.")
        return 0

    existing: dict = {}
    if _OUT_FILE.exists():
        try:
            existing = json.loads(_OUT_FILE.read_text())
        except Exception:
            existing = {}

    last_sha = existing.get("last_commit_sha")
    head_sha = _current_sha()

    if last_sha == head_sha:
        print(f"No new commits since last run ({head_sha[:8]}). Nothing to do.")
        return 0

    log = _commit_log(last_sha)
    if not log:
        print("No commit history in range. Nothing to do.")
        return 0

    print(f"Analyzing commits {last_sha[:8] if last_sha else '(initial)'}..{head_sha[:8]} "
          f"with {get_settings().anthropic_model}...")

    try:
        result = llm.generate_system_enhancements(log, existing.get("enhancements"))
    except Exception as exc:  # noqa: BLE001
        print(f"Generation failed ({exc}); existing enhancements_data.json left unchanged.")
        return 1

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_commit_sha": head_sha,
        "enhancements": result["enhancements"],
        "suggestions": result["suggestions"],
    }
    _OUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")

    print(f"Wrote {len(result['enhancements'])} enhancements to {_OUT_FILE}")
    for e in result["enhancements"]:
        print(f"  [{e['tag']}] {e['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

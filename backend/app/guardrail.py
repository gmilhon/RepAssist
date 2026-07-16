"""Prompt-injection pattern detection — log-only (see docs/16-observability.md).

A cheap regex first pass, not an LLM classifier — mirrors the existing
entity-extraction approach in `llm.py` (deterministic, zero added cost/latency).
Detections are recorded to `GuardrailEvent` for the CX Monitor guardrail panel
and never block or alter a turn. If the false-positive rate proves low enough
in practice, upgrading to block-on-detection (or a model-based classifier for
the ambiguous cases) is a natural follow-up — not built here.

Two call sites, matching the two vectors OWASP LLM01 describes:
  - direct:   the rep's own typed message (llm.classify)
  - indirect: data assembled into a prompt from elsewhere — order context,
              ticket/conversation history — that the rep never typed
              (llm.compose_reply)
"""
from __future__ import annotations

import re

# (pattern name, compiled regex) — checked in order, first match wins per call.
# Deliberately broad/cheap; false positives are fine since detection is
# log-only. Not exhaustive — a real trust & safety pass would use a
# maintained ruleset or a classifier, not a fixed list in source.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_instructions", re.compile(
        r"\bignore\s+(all\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)\b",
        re.IGNORECASE)),
    ("disregard_instructions", re.compile(
        r"\bdisregard\s+(all\s+|the\s+|your\s+)?(instructions?|prompts?|rules?|system)\b",
        re.IGNORECASE)),
    ("new_instructions", re.compile(
        r"\b(new|updated|real)\s+instructions?\s*[:\-]", re.IGNORECASE)),
    ("reveal_system_prompt", re.compile(
        r"\b(reveal|show|print|repeat|what\s+(is|are))\s+(me\s+)?your\s+(system\s+)?(prompt|instructions?)\b",
        re.IGNORECASE)),
    ("role_override", re.compile(
        r"\byou\s+are\s+now\s+(a|an|no\s+longer)\b|\bact\s+as\s+(if\s+you|a|an)\b|\bpretend\s+(you\s+are|to\s+be)\b",
        re.IGNORECASE)),
    ("bypass_confirmation", re.compile(
        r"\b(skip|bypass|auto[\s-]?approve|without\s+(asking|confirming))\s+(the\s+)?confirm(ation)?\b",
        re.IGNORECASE)),
    ("developer_mode", re.compile(
        r"\b(developer|debug|admin|god)\s+mode\b|\bDAN\b", re.IGNORECASE)),
]

_SNIPPET_RADIUS = 40


def scan_for_injection(text: str) -> tuple[str, str] | None:
    """Return (pattern_name, snippet) on the first match, else None."""
    if not text:
        return None
    for name, pattern in _PATTERNS:
        m = pattern.search(text)
        if m:
            start = max(0, m.start() - _SNIPPET_RADIUS)
            end = min(len(text), m.end() + _SNIPPET_RADIUS)
            snippet = text[start:end].strip()
            return name, snippet
    return None

"""Customer Experience (CX) Monitor — LangSmith trace metrics.

Pulls root-chain runs from LangSmith for the configured project, computes
conversation-level latency, token usage, and cost KPIs, and returns them in a
date-filterable shape the CX dashboard can render.

When LANGCHAIN_API_KEY is not set the endpoint returns deterministic mock data
so the dashboard still loads and gives a realistic preview of what tracing adds.
"""
from __future__ import annotations

import random
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from ..config import get_settings

router = APIRouter(prefix="/api/cx", tags=["cx"])

# --------------------------------------------------------------------------- #
# LangSmith SDK — optional import so the server boots without the package
# --------------------------------------------------------------------------- #
try:
    from langsmith import Client as _LSClient  # noqa: F401 — used in cx_overview
    _SDK_AVAILABLE = True
except ImportError:
    _LSClient = None  # type: ignore[assignment, misc]
    _SDK_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _to_utc(d: date, end: bool = False) -> datetime:
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return dt + timedelta(days=1) if end else dt


INTENT_AVG_LATENCY = {
    "activation":    2100,
    "pending_order": 1900,
    "promo":         1600,
    "occ":           1800,
    "billing":        900,
    "other":          750,
}

_INTENTS   = list(INTENT_AVG_LATENCY)
_WEIGHTS   = [28, 18, 22, 14, 10, 8]
_DOW_MULT  = {0: 0.75, 1: 0.85, 2: 0.90, 3: 1.05, 4: 1.50, 5: 1.60, 6: 0.35}
_HOLIDAYS  = [
    (date(2026,  1,  1), 7,  3.0),
    (date(2026,  1, 19), 3,  1.8),
    (date(2026,  2, 16), 4,  2.0),
    (date(2026,  4,  5), 5,  2.2),
    (date(2026,  5, 10), 4,  2.4),
    (date(2026,  5, 25), 5,  2.8),
]


def _holiday_boost(d: date) -> float:
    for holiday, window, peak in _HOLIDAYS:
        delta = (d - holiday).days
        if 1 <= delta <= window:
            return 1.0 + (peak - 1.0) * (window - delta + 1) / window
    return 1.0


def _daily_volume(d: date, rng: random.Random) -> int:
    vol = 17.0 * _DOW_MULT[d.weekday()] * _holiday_boost(d) * rng.uniform(0.88, 1.14)
    return max(2, round(vol))


def _mock_cx_overview(
    start: Optional[date],
    end: Optional[date],
    settings,
) -> dict:
    s = start or date(2026, 1, 1)
    e = end   or date.today()
    rng = random.Random(int(s.strftime("%Y%m%d")) + int(e.strftime("%Y%m%d")))

    timeseries = []
    all_latencies: list[float] = []
    all_input_tokens: list[int]  = []
    all_output_tokens: list[int] = []
    error_count = 0
    recent_traces: list[dict] = []

    d = s
    while d <= e:
        n = _daily_volume(d, rng)
        day_latencies = []
        day_tokens = []
        for _ in range(n):
            intent = rng.choices(_INTENTS, weights=_WEIGHTS)[0]
            base_ms = INTENT_AVG_LATENCY[intent]
            latency_ms = int(rng.gauss(base_ms, base_ms * 0.25))
            latency_ms = max(200, latency_ms)

            input_tok  = int(rng.gauss(880, 180))
            output_tok = int(rng.gauss(215, 60))
            input_tok  = max(200, input_tok)
            output_tok = max(50,  output_tok)
            has_error  = rng.random() < 0.012

            all_latencies.append(latency_ms)
            all_input_tokens.append(input_tok)
            all_output_tokens.append(output_tok)
            day_latencies.append(latency_ms)
            day_tokens.append(input_tok + output_tok)
            if has_error:
                error_count += 1

            # Keep last 25 traces
            if d >= e - timedelta(days=3) and len(recent_traces) < 25:
                ts = datetime(d.year, d.month, d.day,
                              rng.randint(9, 19), rng.randint(0, 59),
                              tzinfo=timezone.utc)
                recent_traces.append({
                    "id": f"mock-{d.isoformat()}-{rng.randint(1000, 9999)}",
                    "started_at": ts.isoformat(),
                    "latency_ms": latency_ms,
                    "input_tokens": input_tok,
                    "output_tokens": output_tok,
                    "total_tokens": input_tok + output_tok,
                    "error": "TimeoutError: upstream agent did not respond" if has_error else None,
                    "intent": intent,
                    "url": None,
                })

        timeseries.append({
            "date": d.isoformat(),
            "conversations": n,
            "avg_latency_ms": int(statistics.mean(day_latencies)),
            "avg_tokens": int(statistics.mean(day_tokens)),
            "error_count": 0,
        })
        d += timedelta(days=1)

    total = len(all_latencies)
    sorted_lat = sorted(all_latencies)
    p50 = int(sorted_lat[int(total * 0.50)])  if sorted_lat else 0
    p95 = int(sorted_lat[int(total * 0.95)])  if sorted_lat else 0
    p99 = int(sorted_lat[int(total * 0.99)])  if sorted_lat else 0

    avg_in  = int(statistics.mean(all_input_tokens))  if all_input_tokens  else 0
    avg_out = int(statistics.mean(all_output_tokens)) if all_output_tokens else 0

    in_rate  = settings.langsmith_input_cost_per_million  / 1_000_000
    out_rate = settings.langsmith_output_cost_per_million / 1_000_000
    avg_cost = avg_in * in_rate + avg_out * out_rate
    total_in  = sum(all_input_tokens)
    total_out = sum(all_output_tokens)

    return {
        "configured": False,
        "langsmith_project": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"start": s.isoformat(), "end": e.isoformat()},
        "overview": {
            "conversations": total,
            "traces_captured": 0,
            "error_count": error_count,
            "error_rate": round(error_count / total, 4) if total else 0.0,
        },
        "latency_ms": {
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "avg": int(statistics.mean(all_latencies)) if all_latencies else 0,
            "by_intent": [
                {
                    "intent": k,
                    "avg_ms": int(rng.gauss(v, v * 0.05)),
                    "count": rng.randint(int(total * 0.08), int(total * 0.32)),
                }
                for k, v in INTENT_AVG_LATENCY.items()
            ],
        },
        "tokens": {
            "avg_input":  avg_in,
            "avg_output": avg_out,
            "avg_total":  avg_in + avg_out,
            "total_input":  total_in,
            "total_output": total_out,
        },
        "cost_usd": {
            "avg_per_conversation": round(avg_cost, 5),
            "total": round(total_in * in_rate + total_out * out_rate, 2),
            "model": settings.anthropic_model,
            "input_rate_per_million":  settings.langsmith_input_cost_per_million,
            "output_rate_per_million": settings.langsmith_output_cost_per_million,
        },
        "timeseries": timeseries,
        "recent_traces": sorted(recent_traces, key=lambda x: x["started_at"], reverse=True),
    }


def _live_cx_overview(
    start: Optional[date],
    end: Optional[date],
    settings,
) -> dict:
    """Pull real trace data from LangSmith."""
    client = _LSClient(api_key=settings.langsmith_api_key)  # type: ignore[misc]

    start_dt = _to_utc(start) if start else None
    end_dt   = _to_utc(end, end=True) if end else None

    list_kwargs: dict = dict(
        project_name=settings.langsmith_project,
        run_type="chain",
        is_root=True,
    )
    if start_dt:
        list_kwargs["start_time"] = start_dt
    if end_dt:
        list_kwargs["end_time"] = end_dt

    runs = list(client.list_runs(**list_kwargs))

    all_latencies:     list[float] = []
    all_input_tokens:  list[int]   = []
    all_output_tokens: list[int]   = []
    error_count = 0
    days: dict[str, dict] = {}
    recent_traces: list[dict] = []

    for run in runs:
        # Latency
        if run.end_time and run.start_time:
            ms = int((run.end_time - run.start_time).total_seconds() * 1000)
            all_latencies.append(ms)
        else:
            ms = 0

        # Tokens — different SDK versions expose them differently
        in_tok  = getattr(run, "prompt_tokens",     None) or getattr(run, "input_tokens",  None) or 0
        out_tok = getattr(run, "completion_tokens",  None) or getattr(run, "output_tokens", None) or 0
        if in_tok:  all_input_tokens.append(int(in_tok))
        if out_tok: all_output_tokens.append(int(out_tok))

        if run.error:
            error_count += 1

        d_str = (run.start_time or datetime.now(timezone.utc)).date().isoformat()
        row = days.setdefault(d_str, {"date": d_str, "conversations": 0,
                                       "avg_latency_ms": 0, "avg_tokens": 0,
                                       "error_count": 0, "_lats": [], "_toks": []})
        row["conversations"] += 1
        if ms:           row["_lats"].append(ms)
        if in_tok + out_tok: row["_toks"].append(int(in_tok + out_tok))
        if run.error:    row["error_count"] += 1

        url = getattr(run, "url", None)
        if len(recent_traces) < 50:
            recent_traces.append({
                "id": str(run.id),
                "started_at": (run.start_time or datetime.now(timezone.utc)).isoformat(),
                "latency_ms": ms,
                "input_tokens":  int(in_tok)  if in_tok  else None,
                "output_tokens": int(out_tok) if out_tok else None,
                "total_tokens":  int(in_tok + out_tok) if (in_tok or out_tok) else None,
                "error": run.error,
                "intent": None,
                "url": url,
            })

    # Finalise timeseries
    timeseries = []
    for row in sorted(days.values(), key=lambda r: r["date"]):
        lats = row.pop("_lats")
        toks = row.pop("_toks")
        row["avg_latency_ms"] = int(statistics.mean(lats)) if lats else 0
        row["avg_tokens"]     = int(statistics.mean(toks)) if toks else 0
        timeseries.append(row)

    total  = len(runs)
    sorted_lat = sorted(all_latencies)
    p50 = int(sorted_lat[int(total * 0.50)]) if sorted_lat else 0
    p95 = int(sorted_lat[int(total * 0.95)]) if sorted_lat else 0
    p99 = int(sorted_lat[int(total * 0.99)]) if sorted_lat else 0

    avg_in  = int(statistics.mean(all_input_tokens))  if all_input_tokens  else 0
    avg_out = int(statistics.mean(all_output_tokens)) if all_output_tokens else 0

    in_rate  = settings.langsmith_input_cost_per_million  / 1_000_000
    out_rate = settings.langsmith_output_cost_per_million / 1_000_000
    total_in  = sum(all_input_tokens)
    total_out = sum(all_output_tokens)

    return {
        "configured": True,
        "langsmith_project": settings.langsmith_project,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {
            "start": start.isoformat() if start else None,
            "end":   end.isoformat()   if end   else None,
        },
        "overview": {
            "conversations": total,
            "traces_captured": total,
            "error_count": error_count,
            "error_rate": round(error_count / total, 4) if total else 0.0,
        },
        "latency_ms": {
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "avg": int(statistics.mean(all_latencies)) if all_latencies else 0,
            "by_intent": [],  # LangSmith traces don't surface intent without metadata
        },
        "tokens": {
            "avg_input":  avg_in,
            "avg_output": avg_out,
            "avg_total":  avg_in + avg_out,
            "total_input":  total_in,
            "total_output": total_out,
        },
        "cost_usd": {
            "avg_per_conversation": round(avg_in * in_rate + avg_out * out_rate, 5),
            "total": round(total_in * in_rate + total_out * out_rate, 2),
            "model": settings.anthropic_model,
            "input_rate_per_million":  settings.langsmith_input_cost_per_million,
            "output_rate_per_million": settings.langsmith_output_cost_per_million,
        },
        "timeseries": timeseries,
        "recent_traces": sorted(recent_traces, key=lambda x: x["started_at"], reverse=True)[:25],
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
def _empty_live(start: Optional[date], end: Optional[date], settings) -> dict:
    """Return a valid live-shaped response with zero data (project not yet created)."""
    return {
        "configured": True,
        "langsmith_project": settings.langsmith_project,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {
            "start": start.isoformat() if start else None,
            "end":   end.isoformat()   if end   else None,
        },
        "overview": {"conversations": 0, "traces_captured": 0, "error_count": 0, "error_rate": 0.0},
        "latency_ms": {"p50": 0, "p95": 0, "p99": 0, "avg": 0, "by_intent": []},
        "tokens": {"avg_input": 0, "avg_output": 0, "avg_total": 0, "total_input": 0, "total_output": 0},
        "cost_usd": {
            "avg_per_conversation": 0.0, "total": 0.0,
            "model": settings.anthropic_model,
            "input_rate_per_million":  settings.langsmith_input_cost_per_million,
            "output_rate_per_million": settings.langsmith_output_cost_per_million,
        },
        "timeseries": [],
        "recent_traces": [],
        "no_traces_yet": True,
    }


def _with_observability(result: dict, start: Optional[date], end: Optional[date]) -> dict:
    """Attach the P0 observability slice — conversation health, sales-intent
    breakdown, guardrail audit, and true token economics — sourced from our
    own store, independent of whether LangSmith is configured. See
    docs/16-observability-p0.md.
    """
    from ..store import db
    result["observability"] = db.observability_overview(start, end)
    result["llm_usage"] = db.llm_usage_overview(start, end)
    return result


@router.get("/overview")
def cx_overview(
    start: Optional[date] = Query(None, description="Start date YYYY-MM-DD (inclusive)"),
    end:   Optional[date] = Query(None, description="End date YYYY-MM-DD (inclusive)"),
) -> dict:
    """Conversation-level CX metrics from LangSmith (or sample data if not configured)."""
    settings = get_settings()
    if settings.langsmith_enabled and _SDK_AVAILABLE:
        try:
            return _with_observability(_live_cx_overview(start, end, settings), start, end)
        except Exception as exc:
            msg = str(exc)
            # Project not found = key is valid but no traces sent yet
            if "not found" in msg.lower():
                return _with_observability(_empty_live(start, end, settings), start, end)
            # Any other error: fall back to mock so the UI never breaks
            result = _mock_cx_overview(start, end, settings)
            result["error"] = msg
            return _with_observability(result, start, end)
    return _with_observability(_mock_cx_overview(start, end, settings), start, end)

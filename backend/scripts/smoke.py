"""Live end-to-end smoke test. Requires both servers running:

    uvicorn app.mock_services.main:app --port 8100   # existing agents (mock)
    uvicorn app.main:app --port 8000                 # orchestrator

Then:  python scripts/smoke.py
"""
from __future__ import annotations

import sys

import httpx

API = "http://127.0.0.1:8000"


def chat(message: str, thread_id: str | None = None) -> dict:
    r = httpx.post(f"{API}/api/chat", json={"message": message, "thread_id": thread_id}, timeout=30)
    r.raise_for_status()
    return r.json()


def confirm(thread_id: str, approved: bool) -> dict:
    r = httpx.post(f"{API}/api/chat/confirm", json={"thread_id": thread_id, "approved": approved}, timeout=30)
    r.raise_for_status()
    return r.json()


def show(label: str, res: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"  status      : {res['status']}")
    print(f"  intent      : {res.get('intent')} ({res.get('confidence')})")
    if res.get("confirmation"):
        print(f"  confirm     : {res['confirmation']['prompt']}")
    if res.get("assistant_message"):
        print(f"  reply       : {res['assistant_message']}")
    if res.get("ticket_id"):
        print(f"  ticket      : {res['ticket_id']}")


def main() -> int:
    health = httpx.get(f"{API}/health", timeout=10).json()
    print(f"health: {health}")

    # 1. Activation -> confirmation -> resolve
    r = chat("Order ACT-1001 is stuck in activation, SIM won't activate")
    show("Activation (proposes fix)", r)
    if r["status"] == "needs_confirmation":
        show("Activation (after approval)", confirm(r["thread_id"], True))

    # 2. Pending order -> confirmation -> resolve
    r = chat("ORD-2002 is blocked, customer can't place a new upgrade order")
    show("Pending order (proposes fix)", r)
    if r["status"] == "needs_confirmation":
        show("Pending order (after approval)", confirm(r["thread_id"], True))

    # 3. Promo -> ineligible (resolved, no action)
    show("Promo ineligible (AC-3004)", chat("Account AC-3004 is missing their BOGO promo"))

    # 4. Billing -> KB answer
    show("Billing question (KB)", chat("Why is the customer's first bill so high?"))

    # 5. Unknown -> human ticket
    show("Unknown issue (escalates)", chat("The customer wants to rename their smartwatch watch face"))

    print("\nSmoke test complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

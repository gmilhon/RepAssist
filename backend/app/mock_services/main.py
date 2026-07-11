"""Mock 'existing agent' microservices.

These stand in for the real Activation Resolver, Pending Order Resolver, Promo
Correction Agent, the order-context service, and the knowledge base. They are a
SEPARATE FastAPI app (run on port 8100) to mirror a real distributed system;
the orchestrator only knows their HTTP contracts.

Run:  uvicorn app.mock_services.main:app --port 8100
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from .data import ACCOUNTS, KB_ARTICLES, ORDERS

app = FastAPI(title="Existing Agent Services (mock)", version="0.1.0")


class DiagnoseRequest(BaseModel):
    order_id: str | None = None
    account_id: str | None = None
    mtn: str | None = None
    notes: str | None = None


class ExecuteRequest(BaseModel):
    operation: str
    params: dict = {}


class KBRequest(BaseModel):
    query: str


def _action(service: str, operation: str, human_prompt: str, **params) -> dict:
    return {"service": service, "operation": operation, "params": params,
            "human_prompt": human_prompt}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mock-existing-agents"}


# --------------------------------------------------------------------------- #
# Activation Resolver
# --------------------------------------------------------------------------- #
@app.post("/activation/diagnose")
def activation_diagnose(req: DiagnoseRequest) -> dict:
    if req.order_id == "ACT-1002":
        return {"can_resolve": False,
                "root_cause": "Number port from the losing carrier has not completed.",
                "summary": "Activation is blocked by an external carrier port that we "
                           "cannot release from the sales counter."}
    return {"can_resolve": True,
            "root_cause": "SIM/eSIM profile was never pushed to the network.",
            "summary": "The line is stuck because provisioning didn't reach the network.",
            "proposed_action": _action(
                "activation", "resend_provisioning",
                "Re-send the provisioning request to activate the line now?",
                order_id=req.order_id)}


@app.post("/activation/execute")
def activation_execute(req: ExecuteRequest) -> dict:
    return {"success": True,
            "summary": "Provisioning re-sent and the line activated successfully.",
            "actions_taken": ["Re-sent provisioning request to the network",
                              "Confirmed the line is now Active"]}


# --------------------------------------------------------------------------- #
# Pending Order Resolver
# --------------------------------------------------------------------------- #
@app.post("/pending-order/diagnose")
def pending_diagnose(req: DiagnoseRequest) -> dict:
    if req.order_id == "ORD-2003":
        return {"can_resolve": False,
                "root_cause": "A credit-check hold is on the account.",
                "summary": "The new order is blocked by a credit hold that requires a "
                           "specialist to review."}
    return {"can_resolve": True,
            "root_cause": "A prior order (ORD-1990) is stuck in DELAYED and blocks new orders.",
            "summary": "The customer's new order is blocked by an older, stalled order.",
            "proposed_action": _action(
                "pending-order", "expedite_prior_order",
                "Expedite/clear the blocking order ORD-1990 so this order can proceed?",
                prior_order="ORD-1990", order_id=req.order_id)}


@app.post("/pending-order/execute")
def pending_execute(req: ExecuteRequest) -> dict:
    prior = req.params.get("prior_order", "the blocking order")
    return {"success": True,
            "summary": f"Cleared {prior}; the new order is no longer blocked.",
            "actions_taken": [f"Expedited {prior}", "Released the hold on the new order"]}


# --------------------------------------------------------------------------- #
# Promo Correction Agent
# --------------------------------------------------------------------------- #
@app.post("/promo/diagnose")
def promo_diagnose(req: DiagnoseRequest) -> dict:
    if req.account_id == "AC-3004":
        return {"can_resolve": True,
                "root_cause": "The promotion window closed before activation.",
                "summary": "The customer isn't eligible — the BOGO promo expired before "
                           "the line activated, so nothing was applied in error."}
    return {"can_resolve": True,
            "root_cause": "Eligibility criteria were met but the credit never attached.",
            "summary": "The customer qualifies for BOGO but the credit wasn't applied.",
            "proposed_action": _action(
                "promo", "reapply_promo",
                "Re-apply the BOGO-2026 promotional credit to this account?",
                promo="BOGO-2026", account_id=req.account_id)}


@app.post("/promo/execute")
def promo_execute(req: ExecuteRequest) -> dict:
    promo = req.params.get("promo", "the promotion")
    return {"success": True,
            "summary": f"Re-applied {promo}; the credit will appear within 1-2 cycles.",
            "actions_taken": [f"Re-applied {promo} credit",
                              "Validated the credit schedule on the account"]}


# --------------------------------------------------------------------------- #
# OCC — Other Charges and Credits
# --------------------------------------------------------------------------- #
@app.post("/occ/diagnose")
def occ_diagnose(req: DiagnoseRequest) -> dict:
    if req.account_id == "AC-5003":
        return {"can_resolve": False,
                "root_cause": "The 30-day activation fee waiver window has closed.",
                "summary": "The account was activated more than 30 days ago; no automatic "
                           "fee waiver can be applied at this time."}
    if req.account_id == "AC-5002":
        return {"can_resolve": True,
                "root_cause": "Documented 48-hour service degradation on the account.",
                "summary": "Customer is eligible for a $50.00 bill credit for the documented "
                           "network outage. Manager authorization is on file.",
                "proposed_action": _action(
                    "occ", "BILL_CREDIT",
                    "Apply $50.00 Bill Credit to account AC-5002? (Manager authorization on file.)",
                    account_id=req.account_id, amount=50.00, creditType="BILL_CREDIT")}
    return {"can_resolve": True,
            "root_cause": "Activation fee charged within the 30-day waiver window.",
            "summary": "Customer is eligible for a $35.00 activation fee waiver.",
            "proposed_action": _action(
                "occ", "ACTIVATION_FEE_WAIVER",
                "Apply $35.00 Activation Fee Waiver to this account?",
                account_id=req.account_id, amount=35.00, creditType="ACTIVATION_FEE_WAIVER")}


@app.post("/occ/execute")
def occ_execute(req: ExecuteRequest) -> dict:
    amount = req.params.get("amount", 0.0)
    credit_type = req.params.get("creditType", req.operation).replace("_", " ").title()
    account_id = req.params.get("account_id", "the account")
    return {"success": True,
            "summary": f"${float(amount):.2f} {credit_type} applied; will appear within 1-2 billing cycles.",
            "actions_taken": [f"Applied ${float(amount):.2f} {credit_type} to {account_id}",
                              "Credit scheduled for next billing cycle",
                              "Rep confirmation recorded"]}


# --------------------------------------------------------------------------- #
# Order-context service
# --------------------------------------------------------------------------- #
@app.get("/orders/lookup")
def orders_lookup(order_id: str = "", account_id: str = "") -> dict:
    if order_id and order_id in ORDERS:
        ctx = dict(ORDERS[order_id])
        acct = ctx.get("account_id")
        if acct in ACCOUNTS:
            ctx["account"] = ACCOUNTS[acct]
        return ctx
    if account_id and account_id in ACCOUNTS:
        return {"account": ACCOUNTS[account_id]}
    # Unknown ids still return a minimal shell so the UI has something to show.
    return {"order_id": order_id or None, "account_id": account_id or None,
            "status": "Unknown", "note": "No matching record in mock data."}


# --------------------------------------------------------------------------- #
# Knowledge base
# --------------------------------------------------------------------------- #
@app.post("/kb/search")
def kb_search(req: KBRequest) -> dict:
    q = req.query.lower()
    for art in KB_ARTICLES:
        if any(k in q for k in art["keywords"]):
            return {"hit": True, "article_id": art["article_id"], "answer": art["answer"]}
    return {"hit": False}

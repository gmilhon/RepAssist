"""A SAMPLE 'real' Activation Resolver — stands in for an actual existing agent.

Unlike backend/app/mock_services (which speaks our idealized diagnose/execute
contract), this service has its OWN native, vendor-style contract and requires a
bearer token — exactly what a real internal agent would look like. The point of
this module is to show that integrating a real agent is about writing an
*adapter* that translates between this contract and ours
(see backend/app/integrations/activation_adapter.py).

Run:  uvicorn app.sample_agent.main:app --port 8200
"""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Activation Resolver (sample real-style agent)", version="2.0.0")


class AnalyzeRequest(BaseModel):
    lineId: str | None = None
    mtn: str | None = None
    context: str | None = None


class Remediation(BaseModel):
    action: str
    label: str
    ref: str


class AnalyzeResponse(BaseModel):
    lineId: str | None = None
    state: str                       # PROVISIONING_FAILED | PORT_PENDING | ACTIVE
    faultCode: str | None = None
    analysis: str
    remediation: Remediation | None = None


class RemediateRequest(BaseModel):
    lineId: str | None = None
    action: str
    ref: str | None = None


class RemediateResponse(BaseModel):
    ok: bool
    state: str
    steps: list[str] = []


def _require_token(authorization: str | None) -> None:
    if not authorization or not authorization.lower().startswith("bearer ") or len(authorization) < 8:
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "activation-resolver-sample", "contract": "v2"}


@app.post("/v2/activation/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest, authorization: str | None = Header(default=None)) -> AnalyzeResponse:
    _require_token(authorization)
    if req.lineId == "ACT-1002":
        return AnalyzeResponse(
            lineId=req.lineId,
            state="PORT_PENDING",
            faultCode="CARRIER_PORT",
            analysis="Number port from the losing carrier has not completed; "
                     "this cannot be remediated from POS.",
            remediation=None,
        )
    return AnalyzeResponse(
        lineId=req.lineId,
        state="PROVISIONING_FAILED",
        faultCode="SIM_NOT_PUSHED",
        analysis="The SIM/eSIM profile was never pushed to the network.",
        remediation=Remediation(
            action="RESEND_PROVISIONING",
            label="Re-send the provisioning request to activate the line now?",
            ref=f"rem_{(req.lineId or 'unknown').lower()}",
        ),
    )


@app.post("/v2/activation/remediate", response_model=RemediateResponse)
def remediate(req: RemediateRequest, authorization: str | None = Header(default=None)) -> RemediateResponse:
    _require_token(authorization)
    return RemediateResponse(
        ok=True,
        state="ACTIVE",
        steps=[
            "Re-sent provisioning request to the network",
            "Confirmed the line is now Active",
        ],
    )


# --------------------------------------------------------------------------- #
# Sample Promo Correction Agent — a DIFFERENT vendor contract + auth (X-Api-Key)
# to show the adapter pattern generalizes across heterogeneous agents.
# --------------------------------------------------------------------------- #
class PromoEvalRequest(BaseModel):
    accountId: str | None = None
    mtn: str | None = None
    freeText: str | None = None


class PromoInfo(BaseModel):
    code: str
    name: str


class PromoFix(BaseModel):
    type: str
    token: str


class PromoEvalResponse(BaseModel):
    accountId: str | None = None
    eligibility: str                 # ELIGIBLE_NOT_APPLIED | INELIGIBLE | APPLIED
    promo: PromoInfo | None = None
    reason: str
    fix: PromoFix | None = None


class PromoApplyRequest(BaseModel):
    accountId: str | None = None
    fixToken: str | None = None
    promoCode: str | None = None


class PromoApplyResponse(BaseModel):
    applied: bool
    creditEta: str
    log: list[str] = []


def _require_api_key(x_api_key: str | None) -> None:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-Api-Key header")


@app.post("/promo-svc/v1/evaluate", response_model=PromoEvalResponse)
def promo_evaluate(req: PromoEvalRequest, x_api_key: str | None = Header(default=None)) -> PromoEvalResponse:
    _require_api_key(x_api_key)
    bogo = PromoInfo(code="BOGO-2026", name="Buy One Get One 2026")
    if req.accountId == "AC-3004":
        return PromoEvalResponse(
            accountId=req.accountId, eligibility="INELIGIBLE", promo=bogo,
            reason="The promotion window closed before activation; the customer "
                   "is not eligible, so nothing was applied in error.", fix=None)
    return PromoEvalResponse(
        accountId=req.accountId, eligibility="ELIGIBLE_NOT_APPLIED", promo=bogo,
        reason="Eligibility criteria were met but the credit never attached.",
        fix=PromoFix(type="REAPPLY_CREDIT", token=f"fix_{(req.accountId or 'unknown').lower()}"))


@app.post("/promo-svc/v1/apply", response_model=PromoApplyResponse)
def promo_apply(req: PromoApplyRequest, x_api_key: str | None = Header(default=None)) -> PromoApplyResponse:
    _require_api_key(x_api_key)
    return PromoApplyResponse(
        applied=True, creditEta="1-2 cycles",
        log=[f"Re-applied {req.promoCode or 'promotion'} credit",
             "Validated the credit schedule on the account"])


# --------------------------------------------------------------------------- #
# Sample OCC (Other Charges and Credits) Agent — Bearer auth, own contract.
# Scenarios:
#   AC-5001  Activation Fee Waiver, $35, AUTO approval
#   AC-5002  Bill Credit, $50, MANAGER_REQUIRED
#   AC-5003  Not eligible (waiver window closed)
# --------------------------------------------------------------------------- #
class OccEvalRequest(BaseModel):
    accountId: str | None = None
    creditType: str | None = None
    amount: float | None = None
    reason: str | None = None


class OccEvalResponse(BaseModel):
    accountId: str | None = None
    eligible: bool
    creditType: str
    amount: float
    approvalLevel: str       # AUTO | MANAGER_REQUIRED
    reason: str
    applyToken: str | None = None


class OccApplyRequest(BaseModel):
    accountId: str | None = None
    creditType: str
    amount: float
    applyToken: str | None = None


class OccApplyResponse(BaseModel):
    applied: bool
    creditId: str
    amount: float
    eta: str
    log: list[str] = []


@app.post("/occ/v1/evaluate", response_model=OccEvalResponse)
def occ_evaluate(req: OccEvalRequest, authorization: str | None = Header(default=None)) -> OccEvalResponse:
    _require_token(authorization)
    if req.accountId == "AC-5002":
        return OccEvalResponse(
            accountId=req.accountId,
            eligible=True,
            creditType="BILL_CREDIT",
            amount=50.00,
            approvalLevel="MANAGER_REQUIRED",
            reason="Service credit for documented 48-hour network degradation.",
            applyToken=f"occ_{(req.accountId or 'unknown').lower()}_bill",
        )
    if req.accountId == "AC-5003":
        return OccEvalResponse(
            accountId=req.accountId,
            eligible=False,
            creditType="ACTIVATION_FEE_WAIVER",
            amount=0.0,
            approvalLevel="AUTO",
            reason="Account was activated more than 30 days ago; the one-time fee waiver window has closed.",
            applyToken=None,
        )
    # Default (AC-5001 and any unknown): activation fee waiver eligible
    return OccEvalResponse(
        accountId=req.accountId,
        eligible=True,
        creditType="ACTIVATION_FEE_WAIVER",
        amount=35.00,
        approvalLevel="AUTO",
        reason="Account activated within the 30-day fee waiver window.",
        applyToken=f"occ_{(req.accountId or 'unknown').lower()}_act_fee",
    )


@app.post("/occ/v1/apply", response_model=OccApplyResponse)
def occ_apply(req: OccApplyRequest, authorization: str | None = Header(default=None)) -> OccApplyResponse:
    _require_token(authorization)
    acct = (req.accountId or "UNKNOWN").upper()
    credit_id = f"CRD-{acct}-{req.creditType[:3]}"
    label = req.creditType.replace("_", " ").title()
    return OccApplyResponse(
        applied=True,
        creditId=credit_id,
        amount=req.amount,
        eta="1-2 billing cycles",
        log=[
            f"${req.amount:.2f} {label} applied to {req.accountId}",
            f"Credit ID: {credit_id}",
            "Rep confirmation recorded",
        ],
    )

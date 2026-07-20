"""Central configuration, loaded from environment / .env.

Every setting has a default so the stack boots with no configuration at all.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    # LLM
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8").strip()

    # Existing agent microservices (mocked locally)
    agent_services_base_url: str = os.getenv(
        "AGENT_SERVICES_BASE_URL", "http://127.0.0.1:8100"
    ).rstrip("/")

    # Examples of pointing a capability at a real, vendor-shaped agent. Empty =>
    # use the built-in mock. See app/integrations/{activation,promo,occ}_adapter.py
    activation_agent_url: str = os.getenv("ACTIVATION_AGENT_URL", "").rstrip("/")
    activation_agent_token: str = os.getenv("ACTIVATION_AGENT_TOKEN", "").strip()
    promo_agent_url: str = os.getenv("PROMO_AGENT_URL", "").rstrip("/")
    promo_agent_token: str = os.getenv("PROMO_AGENT_TOKEN", "").strip()
    occ_agent_url: str = os.getenv("OCC_AGENT_URL", "").rstrip("/")
    occ_agent_token: str = os.getenv("OCC_AGENT_TOKEN", "").strip()

    # External Google CX Agent Studio (CES) agent, relayed to per-intent from the
    # graph's `ces_remote` node (see integrations/ces_client.py). Connection
    # config is sensitive → env/Secret Manager. An empty deployment turns the
    # feature off (enabled() is False). `ces_stub` keeps replies in-process for
    # the offline demo/tests; set CES_STUB=false — plus a Cloud Run service
    # account granted a CES-invoke role — to hit the live `runSession` API.
    ces_deployment: str = os.getenv("CES_DEPLOYMENT", "").strip()   # projects/…/apps/{app}/deployments/{dep}
    ces_app_version: str = os.getenv("CES_APP_VERSION", "").strip()  # projects/…/apps/{app}/versions/{ver}
    ces_location: str = os.getenv("CES_LOCATION", "us").strip()
    ces_stub: bool = os.getenv("CES_STUB", "false").lower() == "true"

    # Persistence
    tickets_db_url: str = os.getenv("TICKETS_DB_URL", "sqlite:///./repassist.db")
    checkpoint_db: str = os.getenv("CHECKPOINT_DB", "./checkpoints.sqlite")

    # Routing
    triage_confidence_threshold: float = float(
        os.getenv("TRIAGE_CONFIDENCE_THRESHOLD", "0.45")
    )

    # LangSmith observability (optional — traces automatically when configured)
    # Uses the standard LangChain env var names so any LangChain tool picks them up.
    langsmith_api_key: str = os.getenv("LANGCHAIN_API_KEY", "").strip()
    langsmith_project: str = os.getenv("LANGCHAIN_PROJECT", "rep-assist").strip()
    # Pricing for cost estimates (USD per million tokens, claude-sonnet-4-6 defaults)
    langsmith_input_cost_per_million: float = float(
        os.getenv("LANGSMITH_INPUT_COST_PER_MILLION", "3.0")
    )
    langsmith_output_cost_per_million: float = float(
        os.getenv("LANGSMITH_OUTPUT_COST_PER_MILLION", "15.0")
    )

    # CORS
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    # SMTP for email reports (optional — preview mode when not set)
    smtp_host:     str  = os.getenv("SMTP_HOST",     "").strip()
    smtp_port:     int  = int(os.getenv("SMTP_PORT", "587"))
    smtp_user:     str  = os.getenv("SMTP_USER",     "").strip()
    smtp_password: str  = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from:     str  = os.getenv("SMTP_FROM",     "").strip()
    smtp_tls:      bool = os.getenv("SMTP_TLS", "true").lower() == "true"

    @property
    def smtp_enabled(self) -> bool:
        """True when host + user are set — required to actually send email."""
        return bool(self.smtp_host and self.smtp_user)

    @property
    def smtp_from_addr(self) -> str:
        return self.smtp_from or self.smtp_user

    @property
    def llm_enabled(self) -> bool:
        """True when a real Anthropic key is present; otherwise we use the mock LLM."""
        return bool(self.anthropic_api_key)

    @property
    def langsmith_enabled(self) -> bool:
        """True when a LangSmith API key is present — enables auto-tracing."""
        return bool(self.langsmith_api_key)

    @property
    def ces_enabled(self) -> bool:
        """True when a CES deployment is configured — gates per-intent routing to
        the external CES agent. Independent of `ces_stub` (which only decides
        whether the relay call is live or the in-process stub)."""
        return bool(self.ces_deployment)


@lru_cache
def get_settings() -> Settings:
    return Settings()

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

    # Persistence
    tickets_db_url: str = os.getenv("TICKETS_DB_URL", "sqlite:///./repassist.db")
    checkpoint_db: str = os.getenv("CHECKPOINT_DB", "./checkpoints.sqlite")

    # Routing
    triage_confidence_threshold: float = float(
        os.getenv("TRIAGE_CONFIDENCE_THRESHOLD", "0.45")
    )

    # CORS
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

    @property
    def llm_enabled(self) -> bool:
        """True when a real Anthropic key is present; otherwise we use the mock LLM."""
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()

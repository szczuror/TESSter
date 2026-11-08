"""Settings, read from environment variables (and a local .env file, see .env.example)."""

from __future__ import annotations

from typing import Literal

from dotenv import find_dotenv, load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODEL = "vllm:gpt-oss_120b"


class Settings(BaseSettings):
    """All variables use the TESS_VERIFIER_ prefix, e.g. TESS_VERIFIER_MODEL.

    Provider credentials are not settings here: each provider reads its own variables,
    VLLM_BASE_URL and VLLM_API_KEY for the default model (PSNC), or ANTHROPIC_API_KEY,
    OPENAI_API_KEY, GOOGLE_API_KEY.
    """

    model_config = SettingsConfigDict(env_prefix="TESS_VERIFIER_", extra="ignore")

    model: str = DEFAULT_MODEL
    """LLM as provider:model, e.g. vllm:gpt-oss_120b or openai:<model>."""
    data: Literal["fake"] = "fake"
    """Data sources. Only placeholder data exist in v1."""
    max_requests: int = 25
    """Upper limit of LLM requests for one candidate, a guard against runaway cost."""
    max_tokens: int = 16000
    """Upper limit of tokens in one LLM response."""


def load_settings() -> Settings:
    """Load .env from the current directory (variables already set win), then read settings."""
    load_dotenv(find_dotenv(usecwd=True))
    return Settings()

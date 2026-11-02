import pydantic_ai
import pytest
from pydantic_ai import models

from tess_verifier.config import Settings
from tess_verifier.sources import DataSources, fake_sources

pydantic_ai.BANNER_ENABLED = False
models.ALLOW_MODEL_REQUESTS = False  # no test may call a real LLM API


@pytest.fixture
def sources() -> DataSources:
    return fake_sources()


@pytest.fixture
def settings() -> Settings:
    # "test" is Pydantic AI's built-in offline model; agent tests override it anyway.
    return Settings(model="test")

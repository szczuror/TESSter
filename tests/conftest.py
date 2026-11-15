import pydantic_ai
import pytest
from pydantic_ai import models

from tesster.config import Settings
from tesster.sources import DataSources, fake_sources

pydantic_ai.BANNER_ENABLED = False
models.ALLOW_MODEL_REQUESTS = False  # no test may call a real LLM API


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test may reach an online archive.

    astroquery sends everything through ``requests``, which fails here. A test of an archive
    gives it a canned answer instead (helpers.toi_table).
    """

    def refuse(session, request, **kwargs):
        # pytest.fail is not an Exception, so astroquery cannot turn it into one of its errors.
        pytest.fail(
            f"A test tried to reach an online archive ({request.url}). Use the fixture sources, "
            "or a canned answer (helpers.toi_table)."
        )

    monkeypatch.setattr("requests.sessions.Session.send", refuse)


@pytest.fixture
def sources() -> DataSources:
    """The placeholder candidates TOI-90001.01 to TOI-90005.01."""
    return fake_sources()


@pytest.fixture
def settings() -> Settings:
    # "test" is Pydantic AI's built-in offline model; agent tests override it anyway.
    return Settings(model="test")

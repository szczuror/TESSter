import pytest
from typer.testing import CliRunner

from tess_verifier.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Keep a developer's local .env and LLM variables out of the tests."""
    monkeypatch.setattr("tess_verifier.config.load_dotenv", lambda *args, **kwargs: False)
    for name in ("TESS_VERIFIER_MODEL", "TESS_VERIFIER_DATA", "VLLM_BASE_URL", "VLLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_samples_lists_the_placeholder_candidates():
    result = runner.invoke(app, ["samples"])
    assert result.exit_code == 0
    assert "TOI-90003.01" in result.output


def test_offline_check_prints_the_report():
    result = runner.invoke(app, ["check", "TOI-90003.01", "--offline"])
    assert result.exit_code == 0, result.output
    assert "TOI-90003.01: false positive" in result.output


def test_invalid_toi_is_explained():
    result = runner.invoke(app, ["check", "TOI-abc", "--offline"])
    assert result.exit_code == 1
    assert "TOI-1234.01" in result.output


def test_chat_needs_one_toi_and_an_llm():
    result = runner.invoke(app, ["check", "TOI-90001.01", "--offline", "--chat"])
    assert result.exit_code == 2


def test_chat_is_refused_in_a_blind_test():
    result = runner.invoke(app, ["check", "TOI-90001.01", "--blind", "--chat"])
    assert result.exit_code == 2
    assert "does not work with --blind" in result.output


def test_batch_without_a_valid_toi_fails():
    result = runner.invoke(app, ["check", "TOI-abc", "TOI-90009.01", "--offline"])
    assert result.exit_code == 1
    assert "None of the inputs could be checked" in result.output


def test_missing_llm_setup_is_explained():
    result = runner.invoke(app, ["check", "TOI-90001.01"])
    assert result.exit_code == 2
    assert "VLLM_BASE_URL" in result.output
    assert "--offline" in result.output


def test_out_saves_reports_and_summary(tmp_path):
    result = runner.invoke(
        app, ["check", "TOI-90001.01", "TOI-90002.01", "--offline", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "TOI-90001.01.md").read_text(encoding="utf-8").startswith("# TOI-90001.01")
    assert (tmp_path / "summary.md").exists()

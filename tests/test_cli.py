import pytest
from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
from helpers import TOI_700_ROW, toi_table
from typer.testing import CliRunner

from tesster.cli import app
from tesster.models import parse_toi
from tesster.sources import build_sources, fake_sources
from tesster.sources.reference import REFERENCE_CANDIDATES

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Keep a developer's local .env and LLM variables out of the tests."""
    monkeypatch.setattr("tesster.config.load_dotenv", lambda *args, **kwargs: False)
    for name in ("TESSTER_MODEL", "VLLM_BASE_URL", "VLLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def placeholder_data(monkeypatch):
    """``tesster check`` reads the online archives, so these tests give it the fixtures."""
    monkeypatch.setattr("tesster.cli.build_sources", fake_sources)


def archive_answers(monkeypatch, *rows: dict) -> None:
    """Use the real sources, with the archive behind astroquery answering with these rows."""
    monkeypatch.setattr("tesster.cli.build_sources", build_sources)
    monkeypatch.setattr(NasaExoplanetArchive, "query_criteria", lambda **criteria: toi_table(*rows))


def test_check_reads_the_online_archives_without_any_flag(monkeypatch, tmp_path):
    """Real data are the default: no option selects them."""
    archive_answers(monkeypatch, TOI_700_ROW)

    result = runner.invoke(app, ["check", "TOI-700.01", "--offline", "--out", str(tmp_path)])

    assert result.exit_code == 0, result.output
    report = (tmp_path / "TOI-700.01.md").read_text(encoding="utf-8")
    assert report.startswith("# TOI-700.01: inconclusive")
    assert "Placeholder data" not in report
    assert "confirmed planet (CP), catalog entry last updated 2024-02-15" in report
    assert "TIC 150428135" in report
    assert "exoplanetarchive.ipac.caltech.edu/TAP/sync" in report


def test_candidate_missing_from_the_online_catalog_is_explained(monkeypatch):
    archive_answers(monkeypatch)

    result = runner.invoke(app, ["check", "TOI-99999.01", "--offline"])

    assert result.exit_code == 1
    assert "No candidate TOI-99999.01" in result.output


def test_samples_lists_the_reference_candidates():
    result = runner.invoke(app, ["samples"])
    assert result.exit_code == 0
    for candidate in REFERENCE_CANDIDATES:
        assert candidate.toi in result.output
    assert "TOI-9000" not in result.output  # the placeholder candidates are for tests only


def test_reference_candidates_are_distinct_toi_numbers():
    tois = [str(parse_toi(candidate.toi)) for candidate in REFERENCE_CANDIDATES]
    assert tois == [candidate.toi for candidate in REFERENCE_CANDIDATES]
    assert len(set(tois)) == len(tois)
    assert 5 <= len(tois) <= 8


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

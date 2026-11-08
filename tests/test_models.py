import pytest

from tess_verifier.models import TOI_FORMAT_HINT, InvalidToiError, ToiId, parse_toi


@pytest.mark.parametrize("text", ["TOI-1234.01", "toi-1234.01", "  TOI 1234.01 ", "TOI1234.01"])
def test_parse_valid_toi(text):
    toi = parse_toi(text)
    assert toi == ToiId(star=1234, candidate=1)
    assert str(toi) == "TOI-1234.01"


@pytest.mark.parametrize("text", ["TOI-abc", "1234.01", "TOI-1234.1", "", "TOI-12.345"])
def test_invalid_toi_shows_expected_form(text):
    with pytest.raises(InvalidToiError, match=TOI_FORMAT_HINT):
        parse_toi(text)


def test_toi_without_suffix_is_not_supported_yet():
    with pytest.raises(InvalidToiError, match="suffix"):
        parse_toi("TOI-1234")


def test_tic_number_is_not_supported_yet():
    with pytest.raises(InvalidToiError, match="TIC"):
        parse_toi("TIC 25155310")

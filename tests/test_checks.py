import math

import pytest
from helpers import SOURCE, make_entry

from tess_verifier.models import (
    CentroidMeasurement,
    CheckStatus,
    NearbyStar,
    TransitMetrics,
)
from tess_verifier.vetting import checks


def metrics(**overrides) -> TransitMetrics:
    values = {
        "odd_depth_ppm": 1000,
        "odd_depth_err_ppm": 50,
        "odd_transits": 3,
        "even_depth_ppm": 1000,
        "even_depth_err_ppm": 50,
        "even_transits": 3,
        "secondary_depth_ppm": 0,
        "secondary_depth_err_ppm": 20,
        "source": SOURCE,
    }
    values.update(overrides)
    return TransitMetrics(**values)


def star(separation: float, tmag: float) -> NearbyStar:
    return NearbyStar(tic_id=7, separation_arcsec=separation, tmag=tmag, source=SOURCE)


def centroid(offset: float, err: float) -> CentroidMeasurement:
    return CentroidMeasurement(offset_arcsec=offset, offset_err_arcsec=err, source=SOURCE)


class TestNearbyStars:
    def test_full_eclipse_of_star_7_5_mag_fainter_gives_about_1000_ppm(self):
        assert checks.max_depth_if_eclipsed_ppm(10.0, 17.5) == pytest.approx(999, abs=1)

    @pytest.mark.parametrize(("tmag", "could_cause"), [(17.4, True), (17.6, False)])
    def test_brightness_limit_for_a_1000_ppm_dip(self, tmag, could_cause):
        (assessment,) = checks.assess_neighbors(make_entry(depth_ppm=1000), [star(60, tmag)])
        assert assessment.could_cause_dip is could_cause

    def test_neighbors_are_sorted_by_separation(self):
        found = checks.assess_neighbors(make_entry(), [star(120, 15), star(30, 16)])
        assert [n.star.separation_arcsec for n in found] == [30, 120]


class TestCentroid:
    def bright(self, separation: float):
        return checks.assess_neighbors(make_entry(depth_ppm=1000), [star(separation, 12.0)])

    def test_missing_pixel_data_skips_the_test(self):
        result = checks.centroid_check(None, self.bright(38), "why")
        assert result.status is CheckStatus.SKIPPED
        assert result.reason == "why"

    def test_significant_shift_fails(self):
        assert checks.centroid_check(centroid(14.5, 2.1), self.bright(38), "").status is (
            CheckStatus.FAILED
        )

    def test_coarse_precision_without_shift_is_unclear(self):
        assert checks.centroid_check(centroid(3.0, 9.0), self.bright(25), "").status is (
            CheckStatus.UNCLEAR
        )

    def test_significant_shift_fails_even_with_coarse_precision(self):
        assert checks.centroid_check(centroid(45.0, 10.0), self.bright(25), "").status is (
            CheckStatus.FAILED
        )

    def test_no_shift_passes(self):
        assert checks.centroid_check(centroid(0.4, 0.5), [], "").status is CheckStatus.PASSED

    @pytest.mark.parametrize(
        ("err", "status"), [(9.0, CheckStatus.UNCLEAR), (5.0, CheckStatus.PASSED)]
    )
    def test_without_the_star_catalog_precision_must_beat_a_third_of_a_pixel(self, err, status):
        # None: the star catalog could not be reached, so a bright star may lie one pixel away.
        assert checks.centroid_check(centroid(3.0, err), None, "").status is status


class TestUnusableErrors:
    """A zero or missing error must not make a measurement infinitely significant."""

    @pytest.mark.parametrize("err", [0.0, -1.0, math.nan])
    def test_centroid_without_a_usable_error_is_unclear(self, err):
        result = checks.centroid_check(centroid(0.0, err), [], "")
        assert result.status is CheckStatus.UNCLEAR
        assert result.finding == checks.NO_USABLE_ERROR

    def test_depths_without_errors_are_unclear(self):
        m = metrics(odd_depth_err_ppm=0, even_depth_err_ppm=0, secondary_depth_err_ppm=0)
        assert checks.odd_even_check(m, "").status is CheckStatus.UNCLEAR
        assert checks.secondary_eclipse_check(m, "").status is CheckStatus.UNCLEAR


class TestOddEven:
    def test_missing_light_curve_skips(self):
        assert checks.odd_even_check(None, "").status is CheckStatus.SKIPPED

    def test_different_depths_fail(self):
        m = metrics(
            odd_depth_ppm=13100, odd_depth_err_ppm=150, even_depth_ppm=10900, even_depth_err_ppm=150
        )
        result = checks.odd_even_check(m, "")
        assert result.status is CheckStatus.FAILED
        assert "10.4 sigma" in result.finding

    def test_equal_depths_pass(self):
        assert checks.odd_even_check(metrics(), "").status is CheckStatus.PASSED

    def test_single_transit_is_unclear(self):
        result = checks.odd_even_check(metrics(even_transits=0), "")
        assert result.status is CheckStatus.UNCLEAR


class TestSecondaryEclipse:
    def test_significant_secondary_fails(self):
        m = metrics(secondary_depth_ppm=900, secondary_depth_err_ppm=120)
        assert checks.secondary_eclipse_check(m, "").status is CheckStatus.FAILED

    def test_no_secondary_passes(self):
        assert checks.secondary_eclipse_check(metrics(), "").status is CheckStatus.PASSED

    def test_negative_depth_is_not_an_eclipse(self):
        m = metrics(secondary_depth_ppm=-200, secondary_depth_err_ppm=20)
        assert checks.secondary_eclipse_check(m, "").status is CheckStatus.PASSED


class TestCompanionSize:
    def test_unknown_star_radius_is_unclear(self):
        result = checks.companion_size_check(make_entry(stellar_radius_rsun=None), "")
        assert result.status is CheckStatus.UNCLEAR

    def test_object_bigger_than_two_jupiters_fails(self):
        # sqrt(0.25) * 1 solar radius = 0.5 solar radii, about 55 Earth radii
        result = checks.companion_size_check(make_entry(depth_ppm=250_000), "")
        assert result.status is CheckStatus.FAILED

    def test_planet_sized_object_passes(self):
        result = checks.companion_size_check(
            make_entry(depth_ppm=2400, stellar_radius_rsun=0.95), ""
        )
        assert result.status is CheckStatus.PASSED
        assert "5.1 Earth radii" in result.finding

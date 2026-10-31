from tess_verifier.models import CatalogEntry, Source, ToiId

SOURCE = Source(name="Test catalog", url="https://example.org/catalog")


def make_entry(**overrides) -> CatalogEntry:
    values = {
        "toi": ToiId(star=1234, candidate=1),
        "tic_id": 1,
        "tmag": 10.0,
        "ra_deg": 0.0,
        "dec_deg": 0.0,
        "period_days": 3.0,
        "epoch_btjd": 2000.0,
        "duration_hours": 2.0,
        "depth_ppm": 1000.0,
        "stellar_radius_rsun": 1.0,
        "source": SOURCE,
    }
    values.update(overrides)
    return CatalogEntry(**values)

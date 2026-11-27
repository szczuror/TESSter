"""The star catalog: the TESS Input Catalog (TIC) at MAST, read with astroquery (UC-01 step 4)."""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from tesster.models import CatalogEntry, NearbyStar, Source
from tesster.sources.base import STAR_CATALOG_NAME, SourceUnavailableError
from tesster.sources.exoplanet_archive import (
    TIME_LIMIT_SECONDS,
    _number,
    _summary,
    _TimeLimitError,
    _within,
)

if TYPE_CHECKING:
    from astropy.table import Table

MAST_INVOKE_URL = "https://mast.stsci.edu/api/v0/invoke"
TIC_CONE_SERVICE = "Mast.Catalogs.Tic.Cone"
COLUMNS = ("ID", "Tmag", "dstArcSec")


def ask_tic(ra_deg: float, dec_deg: float, radius_arcmin: float) -> Table:
    """Query the TIC cone search at MAST through astroquery, or raise SourceUnavailableError."""
    import requests
    from astropy.coordinates import Angle, SkyCoord
    from astroquery import exceptions as astroquery_errors
    from astroquery.mast import Catalogs

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", astroquery_errors.NoResultsWarning)
            return Catalogs.query_region(
                SkyCoord(ra_deg, dec_deg, unit="deg"),
                radius=Angle(radius_arcmin, "arcmin"),
                catalog="Tic",
            )
    except (
        astroquery_errors.InvalidQueryError,
        astroquery_errors.RemoteServiceError,
        astroquery_errors.TimeoutError,
        requests.RequestException,
    ) as exc:
        raise SourceUnavailableError(STAR_CATALOG_NAME, _summary(exc)) from exc


class TicStarCatalog:
    """Implements StarCatalog using the TESS Input Catalog cone search at MAST."""

    def __init__(
        self,
        ask: Callable[[float, float, float], Table] = ask_tic,
        today: Callable[[], date] = date.today,
        time_limit: float = TIME_LIMIT_SECONDS,
    ) -> None:
        self._ask = ask
        self._today = today
        self._time_limit = time_limit

    def stars_near(self, candidate: CatalogEntry, radius_arcmin: float) -> list[NearbyStar]:
        try:
            table = _within(
                self._time_limit,
                lambda: self._ask(candidate.ra_deg, candidate.dec_deg, radius_arcmin),
            )
        except _TimeLimitError:
            raise SourceUnavailableError(STAR_CATALOG_NAME, "it did not answer in time") from None

        source = Source(
            name=STAR_CATALOG_NAME,
            url=tic_cone_link(candidate.ra_deg, candidate.dec_deg, radius_arcmin),
            retrieved=self._today(),
        )
        max_arcsec = radius_arcmin * 60.0
        stars: list[NearbyStar] = []
        if table is None or len(table) == 0:
            return stars

        for row in table:
            tic_id = _tic_id(row["ID"])
            # Exclude the target by TIC number, not by distance: TOI-table coordinates can
            # lie several arcseconds from the TIC position.
            if tic_id is None or tic_id == candidate.tic_id:
                continue
            tmag = _number(row["Tmag"])
            separation = _number(row["dstArcSec"])
            if tmag is None or separation is None or separation < 0 or separation > max_arcsec:
                continue
            stars.append(
                NearbyStar(
                    tic_id=tic_id,
                    separation_arcsec=separation,
                    tmag=tmag,
                    source=source,
                )
            )
        stars.sort(key=lambda s: (s.separation_arcsec, s.tic_id))
        return stars


def tic_cone_link(ra_deg: float, dec_deg: float, radius_arcmin: float) -> str:
    """An address that runs the same TIC cone search in a browser (FR-14)."""
    request = {
        "service": TIC_CONE_SERVICE,
        "params": {
            "ra": round(ra_deg, 6),
            "dec": round(dec_deg, 6),
            "radius": round(radius_arcmin / 60.0, 6),
        },
        "format": "json",
        "pagesize": 2000,
        "page": 1,
    }
    return f"{MAST_INVOKE_URL}?{urlencode({'request': json.dumps(request, separators=(',', ':'))})}"


def _tic_id(cell: Any) -> int | None:
    if getattr(cell, "mask", False):
        return None
    cell = getattr(cell, "value", cell)
    try:
        value = int(str(cell).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None

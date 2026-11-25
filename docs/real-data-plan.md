# Real data: work plan

This plan covers the first project goal: `tesster check` on a real TOI gives a report in which every link resolves, and a known planet and a known eclipsing binary get the expected verdicts. It lists what is done, what is left, and how the rest is split into three packages that three people can work on at the same time. How each package is built is settled by the person who takes it.

## Done: the candidate catalog

`tesster check <TOI>` reads the candidate from the NASA Exoplanet Archive TOI table, with no option to select the data: real archives are the default. The placeholder candidates `TOI-90001.01`–`TOI-90005.01` are left for tests only.

- The catalog is read through astroquery, because the star catalog and the light curves (through lightkurve) need it too. For TAP tables astroquery has no time limit and reports every failure as `InvalidQueryError`, so `ToiCatalog` adds a 60-second limit and turns those errors into `SourceUnavailableError`.
- Sources that are not connected yet (papers, star catalog, light curves) raise `SourceNotConnectedError`. They never return an empty result, which the report would show as a fact, such as "No papers mention this candidate".
- A candidate without a value every check needs is not checked, and the report says which value is missing. This affects 109 of 8175 TOIs that have no period (single transits).
- The date next to the catalog status is the date the row last changed, because the TOI table has no separate status date.
- `tesster samples` lists eight reference candidates (`src/tesster/sources/reference.py`). Every change is checked against them.

| Reference TOI | What it is | Verdict now |
|---|---|---|
| TOI-495.01 | known planet WASP-121 b | *false positive* (see the open decision) |
| TOI-270.01 | confirmed planet TOI-270 c | *inconclusive* |
| TOI-562.01 | confirmed planet GJ 357 b, shallow transit | *inconclusive* |
| TOI-236.01 | eclipsing binary, object too big | *false positive* (companion size) |
| TOI-1637.01 | eclipsing binary, strong secondary eclipse | *inconclusive* |
| TOI-3503.01 | eclipsing binary, odd-even difference | *inconclusive* |
| TOI-1285.01 | nearby eclipsing binary, clear centroid shift | *inconclusive* |
| TOI-5962.01 | nearby eclipsing binary, two stars in one pixel | *inconclusive* |

Only the companion-size test runs on real data so far. The other tests are skipped for lack of measurements, so most verdicts are *inconclusive*.

## Open decision

The companion-size test rejects the real planet WASP-121 b. The catalog values give 22.7 Earth radii against a limit of 22.4 (two Jupiter radii), and the test ignores measurement errors. The limit is a vetting rule, so the team decides whether the test should take the errors into account.

## Packages

| | Package | Works after it |
|---|---|---|
| A | Nearby stars and centroid | A real table of nearby stars; whether the centroid test is required; nearby eclipsing binaries detected |
| B | Light-curve measurements | Odd-even and secondary-eclipse tests on real data; the first full verdicts |
| C | Saved archive data and papers | Reference TOIs checked in tests and CI without the network; a real papers section |

Each package is one or more pull requests from `main`. The packages touch the same few places (`build_sources()`, CLI tests, the reference table above). Small conflicts there are expected and resolved at merge.

### A. Nearby stars and centroid

**Nearby stars** come from the TESS Input Catalog (TIC): the stars within 2.5 arcmin of the target, and whether any is bright enough to cause the dip on its own (FR-07). Without them the centroid test is always required.

Checked on 2026-11-15 on the MAST service `Mast.Catalogs.Tic.Cone`:

- A 2.5 arcmin radius holds 142 stars in an empty field and 4382 in a crowded one, returned in pages of 2000. The report and the agent tool should show only the stars that could cause the dip, plus a count of the rest.
- The target itself is in the list. Exclude it by TIC number, not by distance: TOI-700 lies 3 arcsec from its own TOI-table coordinates.
- Still to check: how `astroquery.mast` handles magnitude filters and large fields, and whether it has a time limit.

**Centroid**:

- First, the result the TESS pipeline publishes (SPOC Data Validation), where one exists for the candidate.
- Where there is none, the test is skipped with that reason.
- Our own measurement from pixel data only if the evaluation shows it is needed.
- Checked on 2026-11-15 on ExoFOP: only about 2250 of 8175 TOIs list SPOC among the pipelines that found them (the rest are QLP and FAINT), so the SPOC result exists for a minority of candidates. The exact fields that hold it are not confirmed yet.

### B. Light-curve measurements

The largest package, best split into two pull requests:

1. Measurement functions: from a light curve to the depths of odd and even transits and of the secondary eclipse, with their errors. Tested on synthetic light curves with a known signal, without the network. This can start right away.
2. Downloading the light curve from MAST, removing trends, and folding it on the period.

The source must remember the result per candidate, because the odd-even and secondary-eclipse tests ask for the same measurements.

`LightCurveArchive` holds both the transit measurements (B) and the centroid (A). A and B agree at the start how to split it, for example into two classes joined in `build_sources()`.

### C. Saved archive data and papers

**Saved archive data**: what the archives returned can be saved and replayed, so tests, the evaluation and the demo do not need the network.

- Saving what the sources return is enough, in the same way as today's fixtures.
- Done as one layer around the source protocols, it does not depend on how A and B build their sources.
- Finish it early: A and B need it to test their sources on reference TOIs without the network. Until then they test against canned answers, as `tests/helpers.py::toi_table` does for the catalog.
- To decide: how saved data are picked. With no option to select the data, the simplest rule is to use them automatically when they exist.

**Papers**: search for papers about the candidate (NASA ADS, arXiv). A paper is listed only when code has confirmed that it mentions the candidate (NFR-02).

- The ExoFOP "Planet Name" column is empty, so the candidate's other names, needed for the search, come from the NASA Exoplanet Archive planet tables, looked up by TIC number.
- This part can wait: blind evaluation skips papers, so evaluation can start without it.

## Done when

- `tesster check` on a real TOI gives a report in which every link resolves.
- The known planets and eclipsing binaries in the reference table get the expected verdicts.
- `uv run pytest` passes without the network.

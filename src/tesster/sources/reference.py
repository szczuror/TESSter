"""Real candidates the project checks every change against.

They cover what the tests must tell apart: planets, eclipsing binaries and nearby eclipsing
binaries. What each one is comes from the TFOPWG dispositions and comments on ExoFOP-TESS, read
on 2026-11-15. All were found by the SPOC pipeline around bright stars and have periods under
six days, so each has many transits in the TESS data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceCandidate:
    toi: str
    known_as: str
    """What follow-up observations found."""
    shows: str
    """Why the candidate is in the set."""


REFERENCE_CANDIDATES = (
    ReferenceCandidate(
        "TOI-495.01",
        "Known planet WASP-121 b, a very large hot Jupiter",
        "A real planet almost too big to be one: about two Jupiter radii from the catalog values",
    ),
    ReferenceCandidate(
        "TOI-270.01",
        "Confirmed planet TOI-270 c, a sub-Neptune of a small red star",
        "A small planet with a clear transit",
    ),
    ReferenceCandidate(
        "TOI-562.01",
        "Confirmed planet GJ 357 b, a little larger than Earth",
        "A planet with a shallow transit",
    ),
    ReferenceCandidate(
        "TOI-236.01",
        "False positive: an eclipsing binary",
        "The transiting object is too big for a planet",
    ),
    ReferenceCandidate(
        "TOI-1637.01",
        "False positive: an eclipsing binary",
        "A strong secondary eclipse",
    ),
    ReferenceCandidate(
        "TOI-3503.01",
        "False positive: an eclipsing binary",
        "Odd and even dips of different depth",
    ),
    ReferenceCandidate(
        "TOI-1285.01",
        "False positive: a nearby eclipsing binary",
        "A clear shift of the light centre during the dip",
    ),
    ReferenceCandidate(
        "TOI-5962.01",
        "False positive: a nearby eclipsing binary",
        "Two stars in one TESS pixel",
    ),
)

"""The HTTP client the online archives share.

It is created in one place, so the tests can make sure that nothing reaches the network.
"""

from __future__ import annotations

import httpx

TIMEOUT_SECONDS = 60.0
"""The NASA Exoplanet Archive often takes about ten seconds to answer a query for one row."""


def new_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)

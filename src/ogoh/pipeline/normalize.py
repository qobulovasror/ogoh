"""URL canonicalisation — dedupe level 1.

The same article reaches us as ?utm_source=feedly, with and without www, with and
without a trailing slash. Collapsing those to one string before hashing is what
makes the UNIQUE constraint on items.url_hash actually catch repeats.
"""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PREFIXES = ("utm_", "mc_", "pk_")
_TRACKING_KEYS = frozenset(
    {"fbclid", "gclid", "igshid", "yclid", "ref", "cmpid", "mkt_tok", "at_medium"}
)


def canonicalize_url(url: str) -> str:
    parts = urlparse(url.strip())
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES) and key.lower() not in _TRACKING_KEYS
    ]

    return urlunparse(
        (
            "https" if parts.scheme in ("http", "https", "") else parts.scheme,
            netloc,
            parts.path.rstrip("/") or "/",
            "",
            urlencode(sorted(query)),
            "",  # fragments never identify a distinct article
        )
    )


def url_hash(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode()).hexdigest()

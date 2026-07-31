"""Spread load across several keys of the same provider, and fail over between them.

One free-tier Gemini key is a hard RPM ceiling; a burst of questions hits it and
starts drawing 429s. Two or more keys let the work fan out — each call starts on
the next key round-robin, which lowers the rate any single key sees — and if a key
is momentarily rate-limited the call retries on the others before giving up.

This wraps providers of the SAME kind (Gemini keys). Falling back to a DIFFERENT
provider (Gemini → Groq) is FallbackProvider's job; the two compose — a rotating
Gemini can be the primary inside a FallbackProvider.
"""

import logging

log = logging.getLogger(__name__)


def split_keys(raw: str) -> list[str]:
    """A comma-separated key string to a clean list. One key, or many."""
    return [key.strip() for key in raw.split(",") if key.strip()]


class RotatingProvider:
    def __init__(self, providers: list) -> None:
        if not providers:
            raise ValueError("RotatingProvider needs at least one provider")
        self._providers = list(providers)
        self._next = 0
        self.model = self._providers[0].model

    def _run(self, method: str, *args):
        count = len(self._providers)
        # Round-robin start spreads the load; advancing every call is what keeps
        # one key from carrying the whole rate.
        start = self._next % count
        self._next = (self._next + 1) % count

        last_exc: Exception | None = None
        for offset in range(count):
            index = (start + offset) % count
            provider = self._providers[index]
            try:
                result = getattr(provider, method)(*args)
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "provider key #%d failed on %s (%s) — rotating",
                    index,
                    method,
                    type(exc).__name__,
                )
                continue
            self.model = provider.model
            return result
        raise last_exc

    def classify_batch(self, items):
        return self._run("classify_batch", items)

    def judge_pairs(self, pairs):
        return self._run("judge_pairs", pairs)

    def research(self, payload):
        return self._run("research", payload)

    def agent_step(self, system: str, transcript: str):
        return self._run("agent_step", system, transcript)

"""Try one provider, fall back to the next.

The point is availability: when Gemini answers 429 — routine on the free tier —
or goes down, every LLM step in the pipeline otherwise skips and the reader gets
silence. A second provider on a separate service and separate quota turns that
into a slower answer instead of no answer.

Order is priority: the first provider is tried first, the rest only when it
raises. `model` tracks whichever one last answered, so the model_used stamp on an
enrichment names the provider that actually wrote it, not the one that was asked.
"""

import logging

from ogoh.llm.base import (
    EnrichInput,
    LLMProvider,
    PairInput,
    PairVerdict,
    ResearchInput,
    ResearchResult,
    Verdict,
)

log = logging.getLogger(__name__)


class FallbackProvider:
    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("FallbackProvider needs at least one provider")
        self._providers = list(providers)
        self.model = self._providers[0].model

    def _run(self, method: str, *args):
        last_exc: Exception | None = None
        for provider in self._providers:
            try:
                result = getattr(provider, method)(*args)
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "provider %s failed on %s (%s) — trying the next",
                    provider.model,
                    method,
                    type(exc).__name__,
                )
                continue
            self.model = provider.model
            return result
        # Every provider failed. Re-raise so the caller's own handling — enrich
        # leaves the batch for next run, dedupe leaves pairs separate — still fires.
        raise last_exc

    def classify_batch(self, items: list[EnrichInput]) -> list[Verdict]:
        return self._run("classify_batch", items)

    def judge_pairs(self, pairs: list[PairInput]) -> list[PairVerdict]:
        return self._run("judge_pairs", pairs)

    def research(self, payload: ResearchInput) -> ResearchResult:
        return self._run("research", payload)

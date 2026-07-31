"""The provider that keeps the pipeline answering when the first choice fails."""

import pytest

from ogoh.llm.base import EnrichInput, PairInput, ResearchInput, ResearchResult, Verdict
from ogoh.llm.fallback import FallbackProvider


class FakeProvider:
    def __init__(self, model, *, error=None):
        self.model = model
        self._error = error
        self.calls = 0

    def classify_batch(self, items):
        self.calls += 1
        if self._error:
            raise self._error
        return [Verdict(index=i.index, importance=6, summary="ok") for i in items]

    def judge_pairs(self, pairs):
        self.calls += 1
        if self._error:
            raise self._error
        return []

    def research(self, payload):
        self.calls += 1
        if self._error:
            raise self._error
        return ResearchResult(body="ok")


def _items():
    return [EnrichInput(index=0, source="s", title="t", text="body")]


def test_the_primary_answers_and_the_fallback_is_untouched():
    primary = FakeProvider("gemini")
    secondary = FakeProvider("groq")
    provider = FallbackProvider([primary, secondary])

    result = provider.classify_batch(_items())

    assert len(result) == 1
    assert secondary.calls == 0
    assert provider.model == "gemini"


def test_the_fallback_takes_over_when_the_primary_raises():
    primary = FakeProvider("gemini", error=RuntimeError("429"))
    secondary = FakeProvider("groq")
    provider = FallbackProvider([primary, secondary])

    result = provider.classify_batch(_items())

    assert len(result) == 1
    assert secondary.calls == 1
    # The stamp names the provider that actually answered, not the one asked.
    assert provider.model == "groq"


def test_all_failing_re_raises_so_the_caller_still_handles_it():
    primary = FakeProvider("gemini", error=RuntimeError("down"))
    secondary = FakeProvider("groq", error=RuntimeError("also down"))
    provider = FallbackProvider([primary, secondary])

    with pytest.raises(RuntimeError):
        provider.judge_pairs([PairInput(index=0, left_title="a", right_title="b")])


def test_a_single_provider_needs_no_wrapper_but_one_still_works():
    provider = FallbackProvider([FakeProvider("gemini")])
    assert provider.research(ResearchInput(headline="h", entities=[], coverage=[], background=[]))


def test_no_providers_is_a_configuration_error():
    with pytest.raises(ValueError):
        FallbackProvider([])

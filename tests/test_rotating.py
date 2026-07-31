"""Key rotation: spread load round-robin, fail over on a rate-limited key."""

import pytest

from ogoh.llm.rotating import RotatingProvider, split_keys


class FakeKey:
    def __init__(self, model, *, error=None):
        self.model = model
        self._error = error
        self.calls = 0

    def classify_batch(self, items):
        self.calls += 1
        if self._error:
            raise self._error
        return [self.model]

    def agent_step(self, system, transcript):
        self.calls += 1
        if self._error:
            raise self._error
        return self.model


def test_split_keys_handles_one_or_many():
    assert split_keys("solo") == ["solo"]
    assert split_keys(" a , b ,,c ") == ["a", "b", "c"]
    assert split_keys("") == []


def test_calls_are_spread_round_robin():
    a, b = FakeKey("A"), FakeKey("B")
    provider = RotatingProvider([a, b])

    provider.classify_batch([])
    provider.classify_batch([])
    provider.classify_batch([])

    # Round-robin: A, B, A — the load does not all land on one key.
    assert a.calls == 2
    assert b.calls == 1


def test_a_rate_limited_key_fails_over_to_the_next():
    dead = FakeKey("dead", error=RuntimeError("429"))
    live = FakeKey("live")
    provider = RotatingProvider([dead, live])

    result = provider.classify_batch([])

    assert result == ["live"]
    assert provider.model == "live"  # tracks the key that answered


def test_all_keys_failing_raises():
    provider = RotatingProvider(
        [FakeKey("a", error=RuntimeError("x")), FakeKey("b", error=RuntimeError("y"))]
    )
    with pytest.raises(RuntimeError):
        provider.agent_step("s", "t")


def test_no_keys_is_a_configuration_error():
    with pytest.raises(ValueError):
        RotatingProvider([])

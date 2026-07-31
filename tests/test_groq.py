"""GroqProvider against a mocked transport — no network, real request/parse path.

Groq's live behaviour (model id, rate limits) can't be checked without a key, but
the two things this code owns — the request it sends and how it parses the reply —
are exercised here through httpx's MockTransport.
"""

import json

import httpx

from ogoh.llm.base import EnrichInput, PairInput
from ogoh.llm.groq import GroqProvider


def _provider(handler) -> GroqProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GroqProvider(api_key="test-key", model="test-model", client=client)


def _reply(payload: dict) -> httpx.Response:
    body = {"choices": [{"message": {"content": json.dumps(payload)}}]}
    return httpx.Response(200, json=body)


def test_classify_sends_a_well_formed_request_and_parses_the_reply():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _reply(
            {
                "verdicts": [
                    {
                        "index": 0,
                        "importance": 9,
                        "summary": "  A launch.  ",
                        "summary_uz": "Yangi model.",
                        "tags": ["model-release"],
                        "entities": ["OpenAI"],
                    }
                ]
            }
        )

    provider = _provider(handler)
    verdicts = provider.classify_batch([EnrichInput(index=0, source="s", title="t", text="x")])

    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert len(verdicts) == 1
    assert verdicts[0].importance == 9
    assert verdicts[0].summary == "A launch."  # stripped


def test_judge_pairs_parses_verdicts():
    def handler(request: httpx.Request) -> httpx.Response:
        return _reply({"verdicts": [{"index": 0, "same_event": True, "reason": "same launch"}]})

    provider = _provider(handler)
    verdicts = provider.judge_pairs([PairInput(index=0, left_title="a", right_title="b")])

    assert verdicts[0].same_event is True


def test_an_empty_batch_makes_no_call():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not be called for an empty batch")

    assert _provider(handler).classify_batch([]) == []


def test_a_server_error_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    provider = _provider(handler)
    try:
        provider.classify_batch([EnrichInput(index=0, source="s", title="t", text="x")])
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("expected an HTTPStatusError to propagate")

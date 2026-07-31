"""Groq as the fallback provider.

Groq speaks the OpenAI chat-completions dialect, so this needs no SDK of its own —
httpx (already a dependency) posts to the compatibility endpoint. It reuses the
same prompts and the same output dataclasses as the Gemini provider, so a caller
cannot tell which one answered.

One difference from Gemini matters: Groq's JSON mode guarantees valid JSON but
enforces no schema, so the exact envelope has to be spelled out in the prompt
rather than handed over as a response_format schema. That is the `_ENVELOPE_*`
suffixes below.
"""

import logging

import httpx
from pydantic import BaseModel, Field

from ogoh.llm.base import (
    EnrichInput,
    PairInput,
    PairVerdict,
    ResearchInput,
    ResearchResult,
    Verdict,
)
from ogoh.llm.prompts import (
    PAIR_SYSTEM_INSTRUCTION,
    RESEARCH_SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION,
    build_classify_prompt,
    build_pair_prompt,
    build_research_prompt,
)

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_TIMEOUT = 120.0

_ENVELOPE_CLASSIFY = (
    '\n\nReturn one JSON object, no prose around it, of the form: '
    '{"verdicts": [{"index": <int>, "importance": <int 0-10>, "summary": <str>, '
    '"summary_uz": <str>, "tags": [<str>], "entities": [<str>]}]}'
)
_ENVELOPE_PAIRS = (
    '\n\nReturn one JSON object, no prose around it, of the form: '
    '{"verdicts": [{"index": <int>, "same_event": <bool>, "reason": <str>}]}'
)
_ENVELOPE_RESEARCH = (
    '\n\nReturn one JSON object, no prose around it, of the form: '
    '{"body": <str>, "body_uz": <str>}'
)


class _Verdict(BaseModel):
    index: int
    importance: int = Field(ge=0, le=10)
    summary: str
    summary_uz: str = ""
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class _Batch(BaseModel):
    verdicts: list[_Verdict]


class _PairVerdict(BaseModel):
    index: int
    same_event: bool
    reason: str = ""


class _PairBatch(BaseModel):
    verdicts: list[_PairVerdict]


class _Research(BaseModel):
    body: str
    body_uz: str = ""


class GroqProvider:
    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self.model = model
        self._api_key = api_key
        # An injectable client is what makes this testable without a network: a
        # test hands in an httpx.Client wired to a MockTransport.
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def _complete(self, system: str, prompt: str, temperature: float) -> str:
        response = self._client.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def classify_batch(self, items: list[EnrichInput]) -> list[Verdict]:
        if not items:
            return []
        raw = self._complete(
            SYSTEM_INSTRUCTION, build_classify_prompt(items) + _ENVELOPE_CLASSIFY, 0.1
        )
        batch = _Batch.model_validate_json(raw)
        return [
            Verdict(
                index=verdict.index,
                importance=verdict.importance,
                summary=verdict.summary.strip(),
                summary_uz=verdict.summary_uz.strip(),
                tags=verdict.tags,
                entities=verdict.entities,
            )
            for verdict in batch.verdicts
        ]

    def judge_pairs(self, pairs: list[PairInput]) -> list[PairVerdict]:
        if not pairs:
            return []
        raw = self._complete(
            PAIR_SYSTEM_INSTRUCTION, build_pair_prompt(pairs) + _ENVELOPE_PAIRS, 0.0
        )
        batch = _PairBatch.model_validate_json(raw)
        return [
            PairVerdict(index=v.index, same_event=v.same_event, reason=v.reason.strip())
            for v in batch.verdicts
        ]

    def research(self, payload: ResearchInput) -> ResearchResult:
        raw = self._complete(
            RESEARCH_SYSTEM_INSTRUCTION, build_research_prompt(payload) + _ENVELOPE_RESEARCH, 0.2
        )
        result = _Research.model_validate_json(raw)
        return ResearchResult(body=result.body.strip(), body_uz=result.body_uz.strip())

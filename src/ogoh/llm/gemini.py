import logging

from google import genai
from pydantic import BaseModel, Field

from ogoh.llm.base import EnrichInput, PairInput, PairVerdict, Verdict
from ogoh.llm.prompts import (
    PAIR_SYSTEM_INSTRUCTION,
    SYSTEM_INSTRUCTION,
    build_classify_prompt,
    build_pair_prompt,
)

log = logging.getLogger(__name__)


class _Verdict(BaseModel):
    index: int
    importance: int = Field(ge=0, le=10)
    summary: str
    summary_uz: str = ""
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class _Batch(BaseModel):
    # Wrapped in an object rather than handing over a bare top-level array:
    # object schemas are the well-trodden path through response_format.
    verdicts: list[_Verdict]


class _PairVerdict(BaseModel):
    index: int
    same_event: bool
    reason: str = Field(default="", description="at most eight words")


class _PairBatch(BaseModel):
    verdicts: list[_PairVerdict]


class GeminiProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self.model = model

    def classify_batch(self, items: list[EnrichInput]) -> list[Verdict]:
        if not items:
            return []

        interaction = self._client.interactions.create(
            model=self.model,
            input=build_classify_prompt(items),
            system_instruction=SYSTEM_INSTRUCTION,
            generation_config={"temperature": 0.1},
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _Batch.model_json_schema(),
            },
        )

        batch = _Batch.model_validate_json(interaction.output_text)
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

        interaction = self._client.interactions.create(
            model=self.model,
            input=build_pair_prompt(pairs),
            system_instruction=PAIR_SYSTEM_INSTRUCTION,
            # This is a judgement with a right answer, not a piece of writing.
            generation_config={"temperature": 0.0},
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _PairBatch.model_json_schema(),
            },
        )

        batch = _PairBatch.model_validate_json(interaction.output_text)
        return [
            PairVerdict(index=v.index, same_event=v.same_event, reason=v.reason.strip())
            for v in batch.verdicts
        ]

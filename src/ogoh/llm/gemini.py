import logging

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from ogoh.agent.types import AgentAction
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


class _Research(BaseModel):
    body: str
    body_uz: str = ""


class _Action(BaseModel):
    action: str
    text: str = ""
    sources: list[str] = Field(default_factory=list)


# Both of these are off by default in the SDK, and both defaults are wrong here.
# Without a timeout the underlying httpx client waits forever, and a wedged call
# blocks the pipeline thread — which max_instances=1 then turns into "no news
# again, ever, until someone restarts the container". Retries are likewise
# disabled unless retry_options is passed, so a single free-tier 429 threw away
# a whole batch of twenty with no backoff before the next one.
_TIMEOUT_MS = 120_000


class GeminiProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(),
            ),
        )
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

    def research(self, payload: ResearchInput) -> ResearchResult:
        interaction = self._client.interactions.create(
            model=self.model,
            input=build_research_prompt(payload),
            system_instruction=RESEARCH_SYSTEM_INSTRUCTION,
            generation_config={"temperature": 0.2},
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _Research.model_json_schema(),
            },
        )
        result = _Research.model_validate_json(interaction.output_text)
        return ResearchResult(body=result.body.strip(), body_uz=result.body_uz.strip())

    def agent_step(self, system: str, transcript: str) -> AgentAction:
        """One decision in the /ask agent loop: pick the next action.

        Structured output rather than native function-calling: it reuses the same
        response_format path as the rest of this provider, and the runner — not
        the model — actually executes the tool. temperature stays low; this is a
        routing decision, not writing.
        """
        interaction = self._client.interactions.create(
            model=self.model,
            input=transcript,
            system_instruction=system,
            generation_config={"temperature": 0.2},
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _Action.model_json_schema(),
            },
        )
        action = _Action.model_validate_json(interaction.output_text)
        return AgentAction(action=action.action, text=action.text, sources=action.sources)

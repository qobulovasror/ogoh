"""Enrichment prompt.

The rubric is written to be absolute on purpose. Batch-relative scoring is the
main failure mode of this step: left alone, the model spreads scores across
whatever batch it is handed, so twenty dull items still produce an 8 and the
importance threshold stops meaning anything from one run to the next.
"""

from collections.abc import Sequence

from ogoh.llm.base import EnrichInput
from ogoh.taxonomy import TAGS

MAX_TEXT_CHARS = 2_000

SYSTEM_INSTRUCTION = """\
You triage AI-industry news for a personalised digest. You are handed a batch of \
items pulled from RSS feeds and you return, for each one, its tags, the entities \
it concerns, an importance score, and a short summary.

Never invent facts. When an item's text is too thin to summarise, summarise the \
title alone and score it low. Summaries state what happened in plain language: no \
marketing register, no "exciting", no framing the reader has to discount.\
"""

_RUBRIC = """\
IMPORTANCE RUBRIC (0-10)
  10  A frontier lab ships a flagship model, or pricing/limits change in a way
      that immediately affects anyone already building on the API.
   8  A new model variant, a major new API capability, or a rate-limit or quota
      change.
   6  A notable feature, an SDK release, a significant benchmark result, or a
      major open-weights release.
   4  An incremental product update, a funding round, a partnership, or an
      opinion piece carrying new data.
   2  Routine coverage, a rehash of older news, speculation, or marketing.
   0  Off-topic, spam, or not about AI at all.

Score every item ABSOLUTELY against this rubric. Do NOT grade on a curve against
the other items in this batch. If all twenty items are routine coverage, all
twenty score 2. A batch with no flagship launch in it contains no 10.\
"""


def build_classify_prompt(items: Sequence[EnrichInput]) -> str:
    tag_menu = "\n".join(f"  {tag.key} — {tag.hint}" for tag in TAGS)
    rendered = "\n\n".join(
        f"### index: {item.index}\n"
        f"source: {item.source}\n"
        f"title: {item.title}\n"
        f"text: {_truncate(item.text)}"
        for item in items
    )

    return f"""\
{_RUBRIC}

ALLOWED TAGS — use only these keys, 1 to 3 per item:
{tag_menu}

ENTITIES — the organisations, models, or products the item is actually about,
for example "Anthropic", "Claude", "MCP". At most 5. Empty list if none apply.

SUMMARY — one or two sentences. What happened, and what it changes for someone
building on these APIs.

Return exactly {len(items)} verdicts, one per item. Echo each item's index back
unchanged: the caller matches verdicts to items by index, not by position.

ITEMS

{rendered}"""


def _truncate(text: str) -> str:
    if not text:
        return "(no body text — judge from the title alone)"
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + " …"

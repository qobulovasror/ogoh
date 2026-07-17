"""Enrichment prompt.

The rubric is written to be absolute on purpose. Batch-relative scoring is the
main failure mode of this step: left alone, the model spreads scores across
whatever batch it is handed, so twenty dull items still produce an 8 and the
importance threshold stops meaning anything from one run to the next.
"""

from collections.abc import Sequence

from ogoh.llm.base import EnrichInput, PairInput
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
building on these APIs. Write it twice:

  summary     — English.
  summary_uz  — Uzbek, latin script. A natural rendering, not a word-for-word
                translation. Leave technical terms, product names and version
                numbers exactly as they are: Claude Sonnet 5, API, rate limit,
                open-weights, expires_at.

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


PAIR_SYSTEM_INSTRUCTION = """\
You decide whether two headlines describe the same event — one thing that \
happened, written up twice — or two different things.

You are strict about this. Two headlines can be about the same product, the same \
company and the same week and still be two events. Say they are the same event \
only when a reader who saw one would learn nothing new from the other.\
"""

_PAIR_RULES = """\
The same event, covered twice:
  "xai-org/grok-build, now open source" / "Grok Build is open source"
  "Claude Sonnet 5 is now available" / "Anthropic releases Claude Sonnet 5"

Different events, however close they look:
  "sqlite-utils 4.1.1" / "sqlite-utils 4.0"           — different releases
  "Claude Sonnet 5 is now available" / "Claude Opus 5 is now available"
                                                       — different products
  "OpenAI announces new model" / "OpenAI announces new pricing"
                                                       — different announcements
  "How sales teams use X" / "How data science teams use X"
                                                       — different articles

Version numbers matter. Product names matter. When you cannot tell, answer that
they are different: showing a reader the same story twice is a nuisance, while
merging two stories deletes one of them and nobody ever learns it existed.\
"""


def build_pair_prompt(pairs: Sequence[PairInput]) -> str:
    rendered = "\n\n".join(
        f"### index: {pair.index}\nA: {pair.left_title}\nB: {pair.right_title}" for pair in pairs
    )
    return f"""\
{_PAIR_RULES}

Return exactly {len(pairs)} verdicts, one per pair. Echo each index back
unchanged: the caller matches verdicts by index, not by position.

PAIRS

{rendered}"""

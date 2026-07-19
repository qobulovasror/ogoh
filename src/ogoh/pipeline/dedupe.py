"""Fold reruns of one story into a single cluster.

Level 1 — the canonical URL hash in ingest — catches the same URL arriving twice.
This catches the same story republished elsewhere, in two passes:

  >= THRESHOLD          near-certain. Merged on the spot, no model involved.
  [CANDIDATE, THRESHOLD) too close to call. Handed to the model to adjudicate.
  < CANDIDATE            left alone.

Why a model and not a similarity number. Measured over live pairs, no threshold
of any kind separates these two cases:

    same story    "xai-org/grok-build, now open source" / "Grok Build is open source"
                  jaccard 0.67   cosine 0.942
    different     "sqlite-utils 4.1.1" / "sqlite-utils 4.0"
                  jaccard 0.50   cosine 0.960

Lexically the true pair scores higher; by embedding the false one does. The plan
called for embeddings at cosine > 0.88, and that is worse than useless here — it
would merge two distinct releases and the second would vanish without trace.
Embeddings answer "same topic", and 4.1.1 and 4.0 genuinely are the same topic.
Nobody asked them the right question.

The model answers the right question, 8/8 on the measured pairs, and says why:
"different software versions", "different products". So similarity is demoted to
what it is good at — proposing candidates cheaply — and the judgement goes to the
thing that can actually make it. Costs about one extra call a day.

Simhash, which the plan also called for, earns its keep on long documents and
corpora needing LSH. These are headlines, and one run compares ~30 new items
against a few hundred. Set overlap is more accurate on short strings and free.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ogoh.config import get_settings
from ogoh.db.models import Item
from ogoh.llm.base import LLMProvider, PairInput

log = logging.getLogger(__name__)

# Merge without asking. Only typographic and near-verbatim reruns reach this.
THRESHOLD = 0.85

# Worth asking about. Below this the pair shares a couple of words and nothing
# else; every measured true duplicate sits at 0.5 or above.
CANDIDATE = 0.45

# One prompt's worth. A day of news produces a handful of candidates, so this is
# a runaway guard, not a real limit.
MAX_PAIRS_PER_RUN = 40

# Versions stay whole: splitting "4.1.1" into digits made it identical to "4.0"
# once stop-word filtering removed the parts, merging three distinct releases.
_TOKEN = re.compile(r"[a-z]+|[0-9]+(?:\.[0-9]+)*")

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
        "have", "how", "in", "is", "it", "its", "new", "now", "of", "on", "or",
        "the", "to", "use", "with",
    }
)


@dataclass(slots=True)
class DedupeStats:
    clustered: int = 0
    merged: int = 0
    adjudicated: int = 0
    merged_by_model: int = 0


def assign_clusters(
    session: Session,
    provider: LLMProvider | None = None,
    within_hours: int | None = None,
) -> DedupeStats:
    """Cluster every stored item, not just the ones today's digest would show.

    The window defaults to everything ingest retains. Tying it to a narrower span
    — 48h, say, to match a daily digest — leaves older items with a NULL cluster,
    and then a weekly subscriber is served the duplicates nobody compared.

    Without a provider the lexical pass runs alone and the ambiguous pairs are
    left as separate stories, which is the safe direction to fail in.
    """
    hours = within_hours if within_hours is not None else get_settings().max_age_days * 24
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    published = func.coalesce(Item.published_at, Item.fetched_at)

    # Oldest first, so the earliest publisher of a story becomes its canonical
    # item and later republishers fold into it.
    candidates = session.scalars(
        select(Item).where(published >= cutoff).order_by(published.asc(), Item.id.asc())
    ).all()

    stats = DedupeStats()
    seen: list[tuple[frozenset[str], int, str]] = []
    ambiguous: list[tuple[Item, int, str]] = []

    for item in candidates:
        tokens = title_tokens(item.title)

        # Items clustered on an earlier run keep their assignment and stay
        # matchable, so a rerun published tomorrow still finds today's story.
        if item.cluster_id is not None:
            if tokens:
                seen.append((tokens, item.cluster_id, item.title))
            continue

        if not tokens:
            item.cluster_id = item.id
            continue

        best_cluster, best_title, best_score = _closest(tokens, seen)

        if best_score >= THRESHOLD:
            item.cluster_id = best_cluster
            stats.merged += 1
            log.info("dedupe: %r folded into cluster %d", item.title, best_cluster)
            continue

        # Stands alone for now. If the model later says otherwise this is
        # reassigned below — safe only because dedupe runs before enrichment, so
        # nothing has been scored, shown or delivered under this id yet.
        item.cluster_id = item.id
        seen.append((tokens, item.id, item.title))
        stats.clustered += 1

        if best_score >= CANDIDATE:
            ambiguous.append((item, best_cluster, best_title))

    session.flush()

    if ambiguous and provider is not None:
        _adjudicate(session, provider, ambiguous, stats)
        session.flush()

    return stats


def _adjudicate(
    session: Session,
    provider: LLMProvider,
    ambiguous: list[tuple[Item, int, str]],
    stats: DedupeStats,
) -> None:
    batch = ambiguous[:MAX_PAIRS_PER_RUN]
    if len(ambiguous) > MAX_PAIRS_PER_RUN:
        log.warning(
            "dedupe: %d ambiguous pairs, judging %d — the rest stay separate this run",
            len(ambiguous),
            MAX_PAIRS_PER_RUN,
        )

    pairs = [
        PairInput(index=position, left_title=item.title, right_title=other_title)
        for position, (item, _, other_title) in enumerate(batch)
    ]

    try:
        verdicts = provider.judge_pairs(pairs)
    except Exception:
        # Failing here leaves the pairs as separate stories: a duplicate the
        # reader can see, rather than a merge nobody can.
        log.exception("dedupe: could not judge %d pairs; leaving them separate", len(pairs))
        return

    stats.adjudicated = len(batch)
    by_index = {verdict.index: verdict for verdict in verdicts}

    for position, (item, other_cluster, other_title) in enumerate(batch):
        verdict = by_index.get(position)
        if verdict is None or not verdict.same_event:
            continue
        item.cluster_id = other_cluster
        stats.clustered -= 1
        stats.merged_by_model += 1
        log.info(
            "dedupe: model folded %r into cluster %d (%s)",
            item.title,
            other_cluster,
            verdict.reason or "same event",
        )


def _closest(
    tokens: frozenset[str], seen: list[tuple[frozenset[str], int, str]]
) -> tuple[int | None, str, float]:
    best_cluster: int | None = None
    best_title = ""
    best_score = 0.0
    for other_tokens, cluster_id, title in seen:
        score = jaccard(tokens, other_tokens)
        if score > best_score:
            best_cluster, best_title, best_score = cluster_id, title, score
    return best_cluster, best_title, best_score


def title_tokens(title: str) -> frozenset[str]:
    # NFKD folds typographic variants apart that render identically. The same
    # headline reached us as "Introducing GPT-Live" from one source and
    # "Introducing GPT‑Live" — U+2011, a non-breaking hyphen — from another.
    folded = unicodedata.normalize("NFKD", title)
    folded = folded.replace("‑", "-").replace("‐", "-")
    return frozenset(t for t in _TOKEN.findall(folded.lower()) if t not in _STOPWORDS)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)

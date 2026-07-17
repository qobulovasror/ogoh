"""Digest assembly: one entry per story, most authoritative source first.

Two rankings, deliberately separate. Within a story the most trusted source
speaks — Anthropic's own release note outranks a rewrite of it, whoever happened
to publish first. Across stories, importance decides the order.

Note what this does *not* do: pick a new canonical and write it back to
`Item.cluster_id`. That column is the key of the deliveries ledger. Moving it
would make every already-sent story look unsent, and everyone would get their
week over again. Cluster identity is permanent; presentation is decided here,
per render.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ogoh.db.models import Item, ItemEnrichment, Source
from ogoh.taxonomy import LABELS_UZ


@dataclass(slots=True)
class DigestEntry:
    item: Item
    enrichment: ItemEnrichment
    also_covered_by: int = 0


def as_utc(value: datetime) -> datetime:
    """SQLite has no timestamptz.

    DateTime(timezone=True) round-trips through it as a naive value, and mixing
    that with an aware one raises TypeError. Postgres returns these aware, so
    this has to cope with both.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def top_entries(
    session: Session,
    min_importance: int,
    limit: int,
    within_hours: int = 48,
) -> list[DigestEntry]:
    cutoff = datetime.now(UTC) - timedelta(hours=within_hours)

    # Window on when the news happened, not on when we happened to fetch it.
    # Every item looks fresh by fetched_at on a first run, which is how a 2015
    # archive post ends up leading today's digest.
    published = func.coalesce(Item.published_at, Item.fetched_at)

    stmt = (
        select(Item, ItemEnrichment, Source.trust_tier)
        .join(ItemEnrichment, ItemEnrichment.item_id == Item.id)
        .join(Source, Source.id == Item.source_id)
        .where(ItemEnrichment.importance >= min_importance)
        .where(published >= cutoff)
        .order_by(ItemEnrichment.importance.desc(), published.desc())
        # Over-fetch: rows collapse by cluster below, and a story carried by four
        # outlets would otherwise eat four of the caller's slots.
        .limit(limit * 5)
    )

    clusters: dict[int, list[tuple[Item, ItemEnrichment, int]]] = {}
    for item, enrichment, trust_tier in session.execute(stmt).all():
        clusters.setdefault(item.cluster_id or item.id, []).append((item, enrichment, trust_tier))

    entries = []
    for members in clusters.values():
        # Lower tier is more authoritative. Between two equally trusted sources
        # the one who broke the story wins — without an explicit tiebreak this
        # falls to fetch order, which means whoever published last.
        members.sort(key=lambda member: (member[2], _recency(member[0])))
        item, enrichment, _ = members[0]
        entries.append(
            DigestEntry(item=item, enrichment=enrichment, also_covered_by=len(members) - 1)
        )

    entries.sort(key=lambda entry: (-entry.enrichment.importance, -_recency(entry.item)))
    return entries[:limit]


def _recency(item: Item) -> float:
    return as_utc(item.published_at or item.fetched_at).timestamp()


def render_telegram(entries: Sequence[DigestEntry]) -> str:
    if not entries:
        return "Bu safar chegaradan o'tgan yangilik yo'q."

    blocks = ["<b>AI yangiliklari</b>\n"]
    for entry in entries:
        tags = " · ".join(LABELS_UZ.get(tag, tag) for tag in entry.enrichment.tags)
        meta = entry.item.source.name
        if tags:
            meta += f" · {tags}"
        if entry.also_covered_by:
            meta += f" · +{entry.also_covered_by} manba"
        blocks.append(
            f"<b>{entry.enrichment.importance}/10</b> — "
            f'<a href="{escape(entry.item.url)}">{escape(entry.item.title)}</a>\n'
            f"{escape(entry.enrichment.summary)}\n"
            f"<i>{escape(meta)}</i>"
        )
    return "\n\n".join(blocks)


def render_console(entries: Sequence[DigestEntry]) -> str:
    if not entries:
        return "(chegaradan o'tgan yangilik yo'q)"

    lines = []
    for entry in entries:
        extra = f"  (+{entry.also_covered_by} manba)" if entry.also_covered_by else ""
        lines.append(f"[{entry.enrichment.importance:>2}/10] {entry.item.title}{extra}")
        lines.append(f"         {entry.enrichment.summary}")
        lines.append(f"         {entry.item.source.name} · {', '.join(entry.enrichment.tags)}")
        lines.append(f"         {entry.item.url}")
        lines.append("")
    return "\n".join(lines)

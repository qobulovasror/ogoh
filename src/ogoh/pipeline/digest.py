"""Digest assembly: the best item per story, ranked.

One shared list for now. Per-user matching lands with the bot — that is where
user_topics and the deliveries ledger come in.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ogoh.db.models import Item, ItemEnrichment
from ogoh.taxonomy import LABELS_UZ


@dataclass(slots=True)
class DigestEntry:
    item: Item
    enrichment: ItemEnrichment
    also_covered_by: int = 0


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
        select(Item, ItemEnrichment)
        .join(ItemEnrichment, ItemEnrichment.item_id == Item.id)
        .where(ItemEnrichment.importance >= min_importance)
        .where(published >= cutoff)
        .order_by(ItemEnrichment.importance.desc(), published.desc())
        # Over-fetch: rows collapse by cluster below, and a story carried by four
        # outlets would otherwise eat four of the caller's slots.
        .limit(limit * 5)
    )

    entries: list[DigestEntry] = []
    by_cluster: dict[int, DigestEntry] = {}

    for item, enrichment in session.execute(stmt).all():
        cluster = item.cluster_id or item.id
        existing = by_cluster.get(cluster)
        if existing is not None:
            # Already have this story from a higher-ranked source; just note the
            # extra coverage.
            existing.also_covered_by += 1
            continue
        if len(entries) >= limit:
            continue
        entry = DigestEntry(item=item, enrichment=enrichment)
        by_cluster[cluster] = entry
        entries.append(entry)

    return entries


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

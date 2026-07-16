"""P0 digest: top items by importance, one shared list.

Per-user matching lands in P1 — that is where user_topics and the deliveries
ledger come in. For now this proves the pipeline produces something worth reading.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ogoh.db.models import Item, ItemEnrichment
from ogoh.taxonomy import LABELS_UZ


def top_items(
    session: Session,
    min_importance: int,
    limit: int,
    within_hours: int = 48,
) -> Sequence[tuple[Item, ItemEnrichment]]:
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
        .limit(limit)
    )
    return session.execute(stmt).all()


def render_telegram(rows: Sequence[tuple[Item, ItemEnrichment]]) -> str:
    if not rows:
        return "Bu safar chegaradan o'tgan yangilik yo'q."

    blocks = ["<b>AI yangiliklari</b>\n"]
    for item, enrichment in rows:
        tags = " · ".join(LABELS_UZ.get(tag, tag) for tag in enrichment.tags)
        blocks.append(
            f"<b>{enrichment.importance}/10</b> — "
            f'<a href="{escape(item.url)}">{escape(item.title)}</a>\n'
            f"{escape(enrichment.summary)}\n"
            f"<i>{escape(item.source.name)}{' · ' + escape(tags) if tags else ''}</i>"
        )
    return "\n\n".join(blocks)


def render_console(rows: Sequence[tuple[Item, ItemEnrichment]]) -> str:
    if not rows:
        return "(chegaradan o'tgan yangilik yo'q)"

    lines = []
    for item, enrichment in rows:
        lines.append(f"[{enrichment.importance:>2}/10] {item.title}")
        lines.append(f"         {enrichment.summary}")
        lines.append(f"         {item.source.name} · {', '.join(enrichment.tags)}")
        lines.append(f"         {item.url}")
        lines.append("")
    return "\n".join(lines)

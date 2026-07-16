"""P0 schema: sources, items, enrichment.

Tags and entities are JSON rather than a Postgres ARRAY so the same models run on
SQLite now and on Postgres later without a rewrite. JSON maps to JSONB on
Postgres, which indexes fine, so this is not a decision that has to be undone.

users / user_topics / deliveries land in P1. `deliveries` in particular carries
PRIMARY KEY(user_id, cluster_id) and is what makes double-sending impossible.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # 1 = primary (the lab itself), 2 = strong secondary, 3 = general press.
    # Used to pick the canonical item once clustering lands in P2.
    trust_tier: Mapped[int] = mapped_column(SmallInteger, default=2)

    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["Item"]] = relationship(back_populates="source")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)

    url: Mapped[str] = mapped_column(String(1024))
    canonical_url: Mapped[str] = mapped_column(String(1024))
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)

    title: Mapped[str] = mapped_column(String(512))
    author: Mapped[str | None] = mapped_column(String(256))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_text: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    source: Mapped[Source] = relationship(back_populates="items")
    enrichment: Mapped["ItemEnrichment | None"] = relationship(
        back_populates="item", uselist=False
    )

    __table_args__ = (Index("ix_items_published_at", "published_at"),)


class ItemEnrichment(Base):
    __tablename__ = "item_enrichment"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)

    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    entities: Mapped[list[str]] = mapped_column(JSON, default=list)
    importance: Mapped[int] = mapped_column(SmallInteger, index=True)
    summary: Mapped[str] = mapped_column(Text)

    model_used: Mapped[str] = mapped_column(String(64))
    enriched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    item: Mapped[Item] = relationship(back_populates="enrichment")

"""Schema: sources, items, enrichment, users, subscriptions, deliveries.

Tags and entities are JSON rather than a Postgres ARRAY so the same models run on
SQLite now and on Postgres later without a rewrite. JSON maps to JSONB on
Postgres, which indexes fine, so this is not a decision that has to be undone.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
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

    # The id of this story's canonical item — its earliest publisher. An item
    # that nobody else ran points at itself. NULL means dedupe hasn't seen it yet.
    cluster_id: Mapped[int | None] = mapped_column(index=True)

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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Telegram ids exceed 2^31, so this must be BigInteger — the default Integer
    # holds today's ids and silently overflows on newer accounts.
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))

    lang: Mapped[str] = mapped_column(String(8), default="uz")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent")

    digest_mode: Mapped[str] = mapped_column(String(16), default="daily")  # see DIGEST_MODES
    digest_hour: Mapped[int] = mapped_column(SmallInteger, default=9)
    min_importance: Mapped[int] = mapped_column(SmallInteger, default=5)

    # Without this a 20-minute scheduler would re-send a daily digest every 20
    # minutes for the whole hour it is due — the deliveries ledger would keep the
    # stories from repeating, but the reader still gets three empty-ish messages.
    last_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    topics: Mapped[list["UserTopic"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class UserTopic(Base):
    __tablename__ = "user_topics"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    tag: Mapped[str] = mapped_column(String(32), primary_key=True)

    user: Mapped[User] = relationship(back_populates="topics")


class Delivery(Base):
    """The idempotency ledger.

    PRIMARY KEY(user_id, cluster_id) is what actually makes it impossible to send
    one person the same story twice. Every guard above this is a convenience; this
    is the one that holds when the process dies mid-run or two instances race.
    Keyed on cluster, not item, so a story republished by a second outlet does not
    come round again.
    """

    __tablename__ = "deliveries"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    cluster_id: Mapped[int] = mapped_column(primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

"""Claude Platform release notes.

docs.claude.com serves raw markdown for a docs page when you append `.md`, so
this is a markdown parser rather than an HTML scraper. That matters: the rendered
page is Next.js App Router HTML whose class names look like
`FeaturedGrid-module-scss-module__W1FydW__sideLink`, and that hash changes on
every build. Anything selecting on it breaks on Anthropic's next deploy, silently.

anthropic.com/news has no `.md` escape hatch and no working sitemap, so it stays
unhandled for now. These release notes carry the model and rate-limit changes
this project exists to catch, which is most of what that page would have given us.
"""

import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from ogoh.sources.base import RawItem

log = logging.getLogger(__name__)

_DATE_HEADING = re.compile(r"^###\s+([A-Z][a-z]+ \d{1,2}, \d{4})\s*$", re.MULTILINE)
_MDX_COMPONENT = re.compile(r"<(\w+)>.*?</\1>", re.DOTALL)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_BLANK_RUN = re.compile(r"\n{3,}")


class ClaudeReleaseNotes:
    kind = "changelog"
    name = "Claude Platform release notes"

    # The canonical location. docs.claude.com/en/release-notes/api still works but
    # 301s here and then 307s from api to overview — two hops on every poll, and
    # a link that bounces the reader twice. Redirects stay followed regardless,
    # since this URL will move again eventually.
    url = "https://platform.claude.com/docs/en/release-notes/overview"
    trust_tier = 1

    def fetch(self) -> list[RawItem]:
        response = httpx.get(f"{self.url}.md", timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        body = response.text

        # Appending .md to a docs URL is a convention, not a contract. When it
        # stops holding we get a rendered page back and every regex below quietly
        # matches nothing — an empty source, which is the failure that hides.
        if body.lstrip()[:200].lower().startswith(("<!doctype", "<html")):
            raise RuntimeError(f"{self.name}: expected markdown, got HTML — the .md route moved")

        return list(_parse(body, self.url))


def _parse(markdown: str, page_url: str) -> Iterator[RawItem]:
    body = _MDX_COMPONENT.sub("", markdown)
    headings = list(_DATE_HEADING.finditer(body))

    for heading, following in zip(headings, [*headings[1:], None]):
        label = heading.group(1)
        published = _parse_date(label)
        if published is None:
            continue

        end = following.start() if following else len(body)
        text = _clean(body[heading.end() : end])
        if not text:
            continue

        yield RawItem(
            # The anchor is real — the rendered page carries id="july-10-2026" —
            # so the link lands the reader on the right entry. It is not the
            # identity though: canonicalisation drops fragments. Hence uid.
            url=f"{page_url}#{_slug(label)}",
            uid=f"release-notes:{published.date().isoformat()}",
            title=f"Claude Platform release notes — {label}",
            published_at=published,
            text=text,
            # This section is the whole entry. Its URL is the full release notes
            # page, so letting extraction near it would replace one day's changes
            # with every day's.
            text_is_complete=True,
        )


def _parse_date(label: str) -> datetime | None:
    try:
        return datetime.strptime(label, "%B %d, %Y").replace(tzinfo=UTC)
    except ValueError:
        log.warning("unparseable release-notes date heading: %r", label)
        return None


def _slug(label: str) -> str:
    return label.lower().replace(",", "").replace(" ", "-")


def _clean(section: str) -> str:
    text = _MD_LINK.sub(r"\1", section)  # keep the link text, drop the target
    return _BLANK_RUN.sub("\n\n", text).strip()

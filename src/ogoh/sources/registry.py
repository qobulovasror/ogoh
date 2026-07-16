"""The P0 source list.

Every URL here was probed and returns items. Two findings worth keeping in mind:

- OpenAI publishes a real RSS feed, so no scraper is needed for it.
- Anthropic does not (both /rss.xml and /news/rss.xml are 404), so it needs an
  HTML scraper. That lands in P1 — it is the one source this project exists for.
- Google DeepMind's rss.xml parses but is permanently empty, which is exactly the
  silent-source failure the ingest step warns about. Left out on purpose.
"""

from ogoh.sources.base import SourceFetcher
from ogoh.sources.rss import RssSource

FETCHERS: tuple[SourceFetcher, ...] = (
    RssSource("OpenAI News", "https://openai.com/news/rss.xml", trust_tier=1),
    RssSource("Simon Willison", "https://simonwillison.net/atom/everything/", trust_tier=1),
    RssSource("Ars Technica AI", "https://arstechnica.com/ai/feed/", trust_tier=2),
    RssSource("Hacker News 100+", "https://hnrss.org/frontpage?points=100", trust_tier=2),
    RssSource(
        "TechCrunch AI",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        trust_tier=3,
    ),
)

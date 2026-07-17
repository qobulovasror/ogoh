"""The source list.

Every URL here was probed and returns items. Findings worth keeping:

- OpenAI publishes a real RSS feed, so it needs no scraper — and it serves its
  whole archive back to 2015, which is what ingest's max_age_days guards against.
- Anthropic publishes no feed (both /rss.xml and /news/rss.xml are 404, and
  sitemap.xml is a soft 404 — a Next.js error page served with status 200). Its
  release notes are reachable as raw markdown instead; see changelog.py.
- GitHub exposes releases.atom per repo, which plain RssSource already reads.
- Google DeepMind's rss.xml parses but is permanently empty (240 bytes, channel,
  no items) — the silent-source failure ingest warns about. Left out on purpose.
"""

from ogoh.sources.base import SourceFetcher
from ogoh.sources.changelog import ClaudeReleaseNotes
from ogoh.sources.rss import RssSource

FETCHERS: tuple[SourceFetcher, ...] = (
    ClaudeReleaseNotes(),
    RssSource(
        "Claude Code releases",
        "https://github.com/anthropics/claude-code/releases.atom",
        trust_tier=1,
    ),
    RssSource("OpenAI News", "https://openai.com/news/rss.xml", trust_tier=1),
    RssSource("Simon Willison", "https://simonwillison.net/atom/everything/", trust_tier=1),
    RssSource("Hugging Face blog", "https://huggingface.co/blog/feed.xml", trust_tier=2),
    RssSource("Ars Technica AI", "https://arstechnica.com/ai/feed/", trust_tier=2),
    RssSource("Hacker News 100+", "https://hnrss.org/frontpage?points=100", trust_tier=2),
    RssSource(
        "TechCrunch AI",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        trust_tier=3,
    ),
)

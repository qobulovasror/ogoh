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

# trust_tier answers one question: when several sources carry the same story,
# whose telling do we show? Not "which source is best" — Simon Willison writes
# better than most first-party blogs. It is about who is speaking with authority
# about *this* news.
#
#   1  first-party. The organisation announcing its own work.
#   2  expert secondary. Reads the primary source and adds something.
#   3  press and aggregators. Reports on what tier 1 said.
#
# Getting this wrong is quiet: OpenAI's own GPT-Live announcement lost the slot
# to a blog post about it, because both were marked tier 1 and the tie fell to
# whoever published later.
FETCHERS: tuple[SourceFetcher, ...] = (
    ClaudeReleaseNotes(),
    RssSource(
        "Claude Code releases",
        "https://github.com/anthropics/claude-code/releases.atom",
        trust_tier=1,
    ),
    RssSource("OpenAI News", "https://openai.com/news/rss.xml", trust_tier=1),
    RssSource("Google AI blog", "https://blog.google/technology/ai/rss/", trust_tier=1),
    RssSource("Hugging Face blog", "https://huggingface.co/blog/feed.xml", trust_tier=1),
    # The arXiv API answers in Atom, so it needs no code of its own.
    RssSource(
        "arXiv cs.AI",
        "http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.CL"
        "&sortBy=submittedDate&sortOrder=descending&max_results=30",
        trust_tier=2,
    ),
    RssSource("Simon Willison", "https://simonwillison.net/atom/everything/", trust_tier=2),
    RssSource("Ars Technica AI", "https://arstechnica.com/ai/feed/", trust_tier=2),
    RssSource(
        "The Verge AI",
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        trust_tier=3,
    ),
    RssSource("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", trust_tier=3),
    RssSource("Hacker News 100+", "https://hnrss.org/frontpage?points=100", trust_tier=3),
    # One Reddit feed, not the two the plan listed. Reddit rate-limits by IP —
    # not per subreddit — and the window measured at roughly 15 seconds: a second
    # feed fetched right after the first gets a 429 and comes back empty, and no
    # retry short of a 15-second sleep clears it. That is 15 seconds of every run
    # spent asleep, 18 minutes a day, to collect community chatter. r/LocalLLaMA
    # is the half that carries real open-weights news, so it is the half kept.
    RssSource("Reddit LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/.rss", trust_tier=3),
)

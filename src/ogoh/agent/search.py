"""Web search behind a small protocol, so the provider is a config edit.

Tavily is built for agents: one call returns a short synthesized answer plus the
source pages already extracted to clean text, so the agent needs no separate
fetch step. httpx (already a dependency) posts to it — no SDK.
"""

from dataclasses import dataclass, field
from typing import Protocol

import httpx

from ogoh.config import Settings

_ENDPOINT = "https://api.tavily.com/search"
_TIMEOUT = 30.0


@dataclass(slots=True)
class WebResult:
    title: str
    url: str
    content: str


@dataclass(slots=True)
class WebSearch:
    answer: str = ""
    results: list[WebResult] = field(default_factory=list)


class SearchProvider(Protocol):
    def search(self, query: str) -> WebSearch:
        ...


class TavilyProvider:
    def __init__(
        self, api_key: str, max_results: int = 5, client: httpx.Client | None = None
    ) -> None:
        self._api_key = api_key
        self._max_results = max_results
        # Injectable client so tests drive it through a MockTransport, no network.
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def search(self, query: str) -> WebSearch:
        response = self._client.post(
            _ENDPOINT,
            json={
                "api_key": self._api_key,
                "query": query,
                "max_results": self._max_results,
                "include_answer": True,
            },
        )
        response.raise_for_status()
        data = response.json()
        results = [
            WebResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
            )
            for item in data.get("results", [])
        ]
        return WebSearch(answer=data.get("answer") or "", results=results)


def build_search_provider(
    settings: Settings, client: httpx.Client | None = None
) -> SearchProvider | None:
    if not settings.tavily_api_key:
        return None
    return TavilyProvider(settings.tavily_api_key, settings.search_max_results, client=client)

"""The closed tag set.

Enrichment drops any tag the model emits that is not a key here. Keeping the set
closed is the whole reason user topic subscriptions can be matched at all — an
open tag set would drift into synonyms ("model-launch", "new-model", "release")
and nothing would ever match.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tag:
    key: str
    hint: str  # sent to the model
    label_uz: str  # shown to users


TAGS: tuple[Tag, ...] = (
    Tag("model-release", "a new model or model version ships", "Yangi model"),
    Tag("pricing-limits", "pricing, rate limits, quota or plan changes", "Narx va limitlar"),
    Tag("api-features", "new API parameters, endpoints, or SDK releases", "API va SDK"),
    Tag("agents-tools", "agents, MCP, tool use, computer use", "Agentlar va MCP"),
    Tag("research", "papers, benchmarks, evaluations", "Tadqiqot"),
    Tag("opensource", "open weights, local or self-hosted models", "Open source"),
    Tag("funding-business", "funding, acquisitions, company news", "Biznes"),
    Tag("safety-policy", "safety, alignment, regulation, policy", "Xavfsizlik va siyosat"),
    Tag("infra-hardware", "chips, datacenters, inference serving", "Infratuzilma"),
    Tag("product-launch", "consumer or product launches", "Mahsulot"),
)

TAG_KEYS: frozenset[str] = frozenset(t.key for t in TAGS)

LABELS_UZ: dict[str, str] = {t.key: t.label_uz for t in TAGS}

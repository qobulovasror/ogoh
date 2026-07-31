from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Blank is allowed so `--dry-run` can exercise ingest with no key at all.
    # The LLM step checks it before the first call.
    gemini_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Flash-Lite gets 15 RPM on the free tier against 10 RPM for the full Flash
    # models, and classify/summarise is exactly the shape of work it is built for.
    gemini_model: str = "gemini-3.1-flash-lite"

    # Fallback provider. Separate quota on a separate service, so when Gemini
    # answers 429 or goes down the pipeline keeps enriching instead of going
    # silent. Off unless a key is set; the model id is Groq's and operator-set.
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    database_url: str = "sqlite:///ogoh.db"

    enrich_batch_size: int = 20
    min_importance: int = 5
    digest_limit: int = 10

    # Some feeds serve their whole archive — OpenAI's goes back to 2015 and ships
    # 1036 items on the first pull. Without a cutoff the first run enriches a
    # decade of history and the first digest is all decade-old launches.
    max_age_days: int = 14

    # Deep dives per pipeline tick. The day yields one or two stories at
    # importance 8+, and each already-written one is skipped, so this is a
    # runaway guard rather than a real budget.
    research_per_run: int = 1

    # How long to keep the full article text after fetching it. The summary,
    # tags, entities and every other bit of metadata are kept forever — this
    # drops only raw_text, the bulky field, once an item is far past every digest
    # window and can no longer be shown or re-summarised. 0 disables pruning.
    raw_text_retention_days: int = 90

    # Admin panel. Only this Telegram id may log in — they run /admin in the bot
    # to get a one-time code and enter it in the panel. 0 means no admin is set
    # and the panel refuses every login. The session secret signs the login
    # cookie; leave it blank and it is derived from the bot token at startup.
    admin_telegram_id: int = 0
    admin_session_secret: str = ""
    admin_host: str = "127.0.0.1"
    admin_port: int = 8000

    # Interactive research agent (/ask). Off unless a user is enabled AND a search
    # key is set. General web Q&A, so the budget and cache below are load-bearing,
    # not decoration: a handful of active users would drain Tavily's free monthly
    # allowance in days without them.
    tavily_api_key: str = ""
    agent_model: str = "gemini-3.1-flash-lite"
    search_max_results: int = 5
    # Per user, per day. The main guard on a shared free-tier quota.
    agent_daily_budget: int = 10
    # Hard stops on one question's loop, so a confused model can't spend a whole
    # budget on a single turn.
    agent_max_tool_calls: int = 5
    agent_max_web_searches: int = 3
    # A repeated question inside this window reuses the stored answer, no new call.
    agent_cache_ttl_hours: int = 6
    # A conversation left idle this long is dropped, so its context stops growing.
    agent_idle_timeout_minutes: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()

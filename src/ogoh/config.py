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


@lru_cache
def get_settings() -> Settings:
    return Settings()

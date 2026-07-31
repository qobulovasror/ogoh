"""FSM storage selection: memory by default, safe fallback when Redis can't load."""

from aiogram.fsm.storage.memory import MemoryStorage

from ogoh.bot.main import build_storage
from ogoh.config import Settings


def test_no_redis_url_uses_memory():
    assert isinstance(build_storage(Settings(redis_url="")), MemoryStorage)


def test_an_unusable_redis_url_falls_back_to_memory_without_raising():
    # The redis package is not installed here, so importing RedisStorage fails —
    # the bot must still come up on memory rather than crash on startup.
    storage = build_storage(Settings(redis_url="redis://localhost:6379/0"))
    assert isinstance(storage, MemoryStorage)

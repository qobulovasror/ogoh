"""Stand-ins for the Telegram objects the handlers are handed.

Deliberately not aiogram instances. The isinstance-guarded edit_text and
edit_reply_markup calls are skipped as a result, which suits what these tests are
for: the risk in a handler is a subscription silently not saved, not a keyboard
drawn a pixel wrong.
"""

from dataclasses import dataclass, field


@dataclass
class StubUser:
    id: int = 42
    username: str | None = "tester"


@dataclass
class StubMessage:
    from_user: StubUser = field(default_factory=StubUser)
    replies: list[str] = field(default_factory=list)

    async def answer(self, text, **kwargs):
        self.replies.append(text)


@dataclass
class StubCallback:
    data: str
    from_user: StubUser = field(default_factory=StubUser)
    message: object = None
    answered: list = field(default_factory=list)

    async def answer(self, text=None, **kwargs):
        self.answered.append(text)

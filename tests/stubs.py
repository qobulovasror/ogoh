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


@dataclass
class StubCommand:
    """Stands in for aiogram's CommandObject — handlers only read `.args`."""

    args: str | None = None


class StubState:
    """Stands in for aiogram's FSMContext — an in-memory data bag."""

    def __init__(self):
        self.state = None
        self._data = {}

    async def set_state(self, state):
        self.state = state

    async def set_data(self, data):
        self._data = dict(data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def get_data(self):
        return dict(self._data)

    async def clear(self):
        self.state = None
        self._data = {}

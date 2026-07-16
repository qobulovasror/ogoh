"""Direct sendMessage call.

aiogram arrives in P1 with the actual bot (commands, handlers, per-user state).
P0 needs one outbound message, and that is one HTTP POST.
"""

import httpx

_API = "https://api.telegram.org"
_MAX_MESSAGE_CHARS = 4096


def send_message(token: str, chat_id: str, text: str) -> None:
    response = httpx.post(
        f"{_API}/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text[:_MAX_MESSAGE_CHARS],
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        },
        timeout=20.0,
    )
    if response.is_error:
        # response.text carries Telegram's reason. The URL holds the token, so it
        # must never reach the message or the log.
        raise RuntimeError(f"telegram sendMessage failed ({response.status_code}): {response.text}")

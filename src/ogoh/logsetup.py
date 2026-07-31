"""Logging setup shared by the two entry points.

Here rather than duplicated in each because of the httpx line: the bot token
lives in the request URL, and httpx logs every request URL at INFO. So the CLI's
--send printed the token to stdout, and the bot process wrote it into the
container's log file — defeating, by a route nobody had looked at, the care
notify/telegram.py takes to keep the token out of its own error messages.

Silencing httpx also stops it logging every article URL the extractor fetches,
which on a busy run crowds the diagnostics out of the 30MB docker keeps.
"""

import logging

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=_FORMAT)
    logging.getLogger("httpx").setLevel(logging.WARNING)

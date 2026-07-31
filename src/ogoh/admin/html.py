"""Server-rendered HTML, built from Python strings.

No template files and no client build: the panel is small and self-contained, so
a handful of helpers that assemble escaped HTML beat standing up Jinja and a
bundler. Every value that comes from the database or a form goes through
`escape` — these helpers take already-escaped cell HTML, callers escape their own
text.
"""

from collections.abc import Sequence
from html import escape

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 15px/1.5 system-ui, sans-serif; margin: 0; color: #1a1a1a; background: #f6f7f9; }
@media (prefers-color-scheme: dark) { body { color: #e6e6e6; background: #16181d; } }
header { display: flex; gap: 1rem; align-items: center; padding: .7rem 1.2rem;
  background: #1f2430; color: #fff; flex-wrap: wrap; }
header a { color: #cdd3df; text-decoration: none; padding: .2rem .4rem; border-radius: 5px; }
header a.on { background: #394150; color: #fff; }
header a:hover { color: #fff; }
header .right { margin-left: auto; }
main { max-width: 1000px; margin: 0 auto; padding: 1.2rem; }
h1 { font-size: 1.3rem; } h2 { font-size: 1.05rem; margin-top: 1.6rem; }
table { border-collapse: collapse; width: 100%; margin: .6rem 0; background: #fff; }
@media (prefers-color-scheme: dark) { table { background: #1e2129; } }
th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #e3e5ea; vertical-align: top; }
@media (prefers-color-scheme: dark) { th, td { border-color: #2c303a; } }
th { font-size: .8rem; text-transform: uppercase; letter-spacing: .03em; color: #7a828f; }
a { color: #2f6fd6; } @media (prefers-color-scheme: dark) { a { color: #79a6f0; } }
form.inline { display: inline; }
input, select, textarea { font: inherit; padding: .35rem .5rem; border: 1px solid #c8ccd4;
  border-radius: 6px; background: #fff; color: inherit; }
@media (prefers-color-scheme: dark) { input, select, textarea { background: #12141a; border-color: #333; } }
button { font: inherit; padding: .4rem .8rem; border: 0; border-radius: 6px; cursor: pointer;
  background: #2f6fd6; color: #fff; }
button.ghost { background: #6b7280; } button.danger { background: #c23b3b; }
.card { background: #fff; border-radius: 10px; padding: 1rem 1.2rem; margin: .6rem 0; }
@media (prefers-color-scheme: dark) { .card { background: #1e2129; } }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .8rem; }
.stat { font-size: 1.7rem; font-weight: 700; } .stat small { font-size: .8rem; font-weight: 400; color: #7a828f; }
.flash { background: #e7f3e7; border: 1px solid #b6ddb6; padding: .6rem .9rem; border-radius: 8px; margin: .6rem 0; }
@media (prefers-color-scheme: dark) { .flash { background: #1d2b1d; border-color: #2f4a2f; } }
.muted { color: #7a828f; } .tag { display: inline-block; background: #eef1f6; border-radius: 5px;
  padding: .05rem .4rem; margin: 0 .2rem .2rem 0; font-size: .82rem; }
@media (prefers-color-scheme: dark) { .tag { background: #262b36; } }
label { display: block; margin: .5rem 0 .15rem; font-size: .85rem; color: #7a828f; }
.row { display: flex; gap: .5rem; flex-wrap: wrap; align-items: end; }
pre { white-space: pre-wrap; word-break: break-word; background: #f0f1f4; padding: .8rem; border-radius: 8px; }
@media (prefers-color-scheme: dark) { pre { background: #12141a; } }
"""

_NAV = (
    ("/", "Dashboard"),
    ("/sources", "Manbalar"),
    ("/items", "Yangiliklar"),
    ("/users", "Foydalanuvchilar"),
    ("/agent", "Agent"),
)


def page(title: str, body: str, active: str = "") -> str:
    nav = "".join(
        f'<a href="{path}" class="{"on" if path == active else ""}">{escape(label)}</a>'
        for path, label in _NAV
    )
    return (
        "<!doctype html><html lang='uz'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)} · Ogoh admin</title><style>{_CSS}</style></head><body>"
        f"<header><b>Ogoh</b>{nav}<a href='/logout' class='right'>Chiqish</a></header>"
        f"<main>{body}</main></body></html>"
    )


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    if not rows:
        return f"<table><thead><tr>{head}</tr></thead></table><p class='muted'>Bo'sh.</p>"
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

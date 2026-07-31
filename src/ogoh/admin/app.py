"""The admin panel: FastAPI, server-rendered, one module of routes.

Auth is a one-time code the bot hands the configured admin (see bot/handlers
handle_admin and admin/auth). Everything past /login is gated by a signed session
cookie. The panel reads and writes the same database the bot and pipeline use,
through the same session_scope, so a change here is a change everywhere.
"""

import logging
from datetime import UTC, datetime, timedelta
from html import escape

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from ogoh.admin import html
from ogoh.admin.auth import SESSION_KEY, session_secret, verify_code
from ogoh.config import Settings, get_settings
from ogoh.db.models import (
    AgentQueryCache,
    AgentUsage,
    Feedback,
    Item,
    ItemEnrichment,
    Source,
    User,
    UserKeyword,
    UserTopic,
)
from ogoh.db.session import session_scope
from ogoh.pipeline.digest import as_utc
from ogoh.taxonomy import TAG_KEYS, TAGS
from ogoh.worker import run_pipeline

log = logging.getLogger(__name__)

_DIGEST_MODES = ("instant", "daily", "weekly", "off")
_LANGS = ("uz", "en")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Ogoh admin")
    app.add_middleware(SessionMiddleware, secret_key=session_secret(settings), same_site="lax")

    def _guarded(request: Request) -> RedirectResponse | None:
        if not request.session.get(SESSION_KEY):
            return RedirectResponse("/login", status_code=303)
        return None

    # ---- auth ----------------------------------------------------------------

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request, error: str = "") -> HTMLResponse:
        if request.session.get(SESSION_KEY):
            return RedirectResponse("/", status_code=303)
        note = f"<p class='flash' style='background:#f7e3e3'>{escape(error)}</p>" if error else ""
        body = (
            "<h1>Ogoh admin</h1>"
            "<p class='muted'>Botda <b>/admin</b> yozib kod ol, shu yerga kirit.</p>"
            f"{note}"
            "<form method='post' action='/login'>"
            "<label>Kirish kodi</label>"
            "<div class='row'><input name='code' autofocus inputmode='numeric' "
            "autocomplete='one-time-code'><button>Kirish</button></div></form>"
        )
        return HTMLResponse(html.page("Kirish", body))

    @app.post("/login")
    async def login_submit(request: Request, code: str = Form("")) -> RedirectResponse:
        with session_scope() as session:
            admin_id = verify_code(session, code, settings.admin_telegram_id)
        if admin_id is None:
            return RedirectResponse("/login?error=Kod+xato+yoki+muddati+o'tgan", status_code=303)
        request.session[SESSION_KEY] = admin_id
        return RedirectResponse("/", status_code=303)

    @app.get("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # ---- dashboard -----------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, msg: str = "") -> HTMLResponse:
        if guard := _guarded(request):
            return guard
        now = datetime.now(UTC)
        day_ago = now - timedelta(hours=24)
        week_ago = now - timedelta(days=7)

        with session_scope() as session:
            users = session.scalar(select(func.count()).select_from(User)) or 0
            active = session.scalar(
                select(func.count()).select_from(User).where(User.is_active.is_(True))
            ) or 0
            sources = session.scalar(
                select(func.count()).select_from(Source).where(Source.enabled.is_(True))
            ) or 0
            items_total = session.scalar(select(func.count()).select_from(Item)) or 0
            items_day = session.scalar(
                select(func.count()).select_from(Item).where(Item.fetched_at >= day_ago)
            ) or 0
            enriched_day = session.scalar(
                select(func.count())
                .select_from(ItemEnrichment)
                .where(ItemEnrichment.enriched_at >= day_ago)
            ) or 0
            up = session.scalar(
                select(func.count()).select_from(Feedback).where(Feedback.vote == 1)
            ) or 0
            down = session.scalar(
                select(func.count()).select_from(Feedback).where(Feedback.vote == -1)
            ) or 0
            fed_recently = select(Item.source_id).where(Item.fetched_at >= week_ago).distinct()
            quiet = list(
                session.scalars(
                    select(Source.name)
                    .where(Source.enabled.is_(True))
                    .where(Source.id.not_in(fed_recently))
                    .order_by(Source.name)
                )
            )

        def stat(value: int, label: str) -> str:
            return f"<div class='card'><div class='stat'>{value}<br><small>{escape(label)}</small></div></div>"

        cards = (
            stat(users, f"obunachi ({active} faol)")
            + stat(sources, "manba")
            + stat(items_day, "24s yangilik")
            + stat(items_total, "jami item")
            + stat(enriched_day, "24s baholangan")
            + stat(up, "👍")
            + stat(down, "👎")
        )
        quiet_note = (
            "<div class='card'><h2>Jim manbalar ⚠️</h2>"
            + ("".join(f"<span class='tag'>{escape(name)}</span>" for name in quiet) or "yo'q")
            + "</div>"
        )
        flash = f"<p class='flash'>{escape(msg)}</p>" if msg else ""
        run = (
            "<form method='post' action='/run'><button>Pipeline'ni hozir ishga tushir</button>"
            " <span class='muted'>fetch → dedupe → extract → enrich → research</span></form>"
        )
        body = f"<h1>Dashboard</h1>{flash}<div class='grid'>{cards}</div>{quiet_note}{run}"
        return HTMLResponse(html.page("Dashboard", body, active="/"))

    @app.post("/run")
    async def run_now(request: Request) -> RedirectResponse:
        if guard := _guarded(request):
            return guard
        stats = await run_in_threadpool(run_pipeline)
        msg = (
            f"Run tugadi: {stats.new_items} yangi, {stats.stories} to'plam, "
            f"{stats.enriched} baholandi, {stats.researched} chuqur tahlil."
        )
        return RedirectResponse(f"/?msg={_q(msg)}", status_code=303)

    # ---- sources -------------------------------------------------------------

    @app.get("/sources", response_class=HTMLResponse)
    async def sources_list(request: Request, msg: str = "") -> HTMLResponse:
        if guard := _guarded(request):
            return guard
        with session_scope() as session:
            rows = list(
                session.scalars(select(Source).order_by(Source.trust_tier, Source.name))
            )
            counts = dict(
                session.execute(
                    select(Item.source_id, func.count(Item.id)).group_by(Item.source_id)
                ).all()
            )
            table_rows = [_source_row(source, counts.get(source.id, 0)) for source in rows]

        flash = f"<p class='flash'>{escape(msg)}</p>" if msg else ""
        add = (
            "<h2>Yangi manba</h2>"
            "<form method='post' action='/sources/add' class='row'>"
            "<div><label>Nomi</label><input name='name' required></div>"
            "<div><label>URL</label><input name='url' size='40' required></div>"
            "<div><label>Turi</label><input name='kind' value='rss' size='8'></div>"
            "<div><label>Tier</label><input name='trust_tier' type='number' min='1' max='3' value='2' size='2'></div>"
            "<button>Qo'shish</button></form>"
        )
        body = (
            f"<h1>Manbalar</h1>{flash}"
            + html.table(
                ["Nomi", "Tier", "URL", "Item", "Holat", "Amal"], table_rows
            )
            + add
        )
        return HTMLResponse(html.page("Manbalar", body, active="/sources"))

    @app.post("/sources/add")
    async def sources_add(
        request: Request,
        name: str = Form(...),
        url: str = Form(...),
        kind: str = Form("rss"),
        trust_tier: int = Form(2),
    ) -> RedirectResponse:
        if guard := _guarded(request):
            return guard
        with session_scope() as session:
            exists = session.scalar(select(Source).where(Source.name == name.strip()))
            if exists is not None:
                return RedirectResponse("/sources?msg=" + _q("Bu nomli manba bor"), status_code=303)
            session.add(
                Source(
                    name=name.strip(),
                    url=url.strip(),
                    kind=kind.strip() or "rss",
                    trust_tier=_clamp(trust_tier, 1, 3),
                    enabled=True,
                )
            )
        return RedirectResponse("/sources?msg=" + _q("Qo'shildi"), status_code=303)

    @app.post("/sources/{source_id}/update")
    async def sources_update(
        request: Request,
        source_id: int,
        url: str = Form(...),
        kind: str = Form("rss"),
        trust_tier: int = Form(2),
        enabled: str = Form(""),
    ) -> RedirectResponse:
        if guard := _guarded(request):
            return guard
        with session_scope() as session:
            source = session.get(Source, source_id)
            if source is not None:
                source.url = url.strip()
                source.kind = kind.strip() or "rss"
                source.trust_tier = _clamp(trust_tier, 1, 3)
                source.enabled = enabled == "on"
        return RedirectResponse("/sources?msg=" + _q("Saqlandi"), status_code=303)

    @app.post("/sources/{source_id}/delete")
    async def sources_delete(request: Request, source_id: int) -> RedirectResponse:
        if guard := _guarded(request):
            return guard
        with session_scope() as session:
            source = session.get(Source, source_id)
            if source is None:
                return RedirectResponse("/sources", status_code=303)
            has_items = session.scalar(
                select(func.count()).select_from(Item).where(Item.source_id == source_id)
            )
            if has_items:
                # Items carry a foreign key to the source; deleting it would orphan
                # them. Disabling is the reversible, non-destructive equivalent.
                source.enabled = False
                msg = "Itemlari bor — o'chirish o'rniga o'chirib qo'yildi (disabled)"
            else:
                session.delete(source)
                msg = "O'chirildi"
        return RedirectResponse("/sources?msg=" + _q(msg), status_code=303)

    # ---- items ---------------------------------------------------------------

    @app.get("/items", response_class=HTMLResponse)
    async def items_list(
        request: Request, source_id: int = 0, min_importance: int = 0, limit: int = 50
    ) -> HTMLResponse:
        if guard := _guarded(request):
            return guard
        limit = _clamp(limit, 1, 200)
        with session_scope() as session:
            source_options = [(0, "— barcha manba —")] + [
                (s.id, s.name)
                for s in session.scalars(select(Source).order_by(Source.name))
            ]
            stmt = (
                select(Item, ItemEnrichment)
                .outerjoin(ItemEnrichment, ItemEnrichment.item_id == Item.id)
                .order_by(
                    func.coalesce(Item.published_at, Item.fetched_at).desc(), Item.id.desc()
                )
            )
            if source_id:
                stmt = stmt.where(Item.source_id == source_id)
            if min_importance:
                stmt = stmt.where(ItemEnrichment.importance >= min_importance)
            rows = session.execute(stmt.limit(limit)).all()
            table_rows = [_item_row(item, enr) for item, enr in rows]

        filters = (
            "<form method='get' action='/items' class='row'>"
            "<div><label>Manba</label>"
            f"{_select('source_id', source_options, source_id)}</div>"
            "<div><label>Min importance</label>"
            f"<input name='min_importance' type='number' min='0' max='10' value='{min_importance}' size='2'></div>"
            f"<input type='hidden' name='limit' value='{limit}'>"
            "<button>Filtr</button></form>"
        )
        body = (
            "<h1>Yangiliklar</h1>" + filters
            + html.table(["#", "Sana", "Manba", "Sarlavha", "Imp", "Teglar"], table_rows)
        )
        return HTMLResponse(html.page("Yangiliklar", body, active="/items"))

    @app.get("/items/{item_id}", response_class=HTMLResponse)
    async def item_detail(request: Request, item_id: int, msg: str = "") -> HTMLResponse:
        if guard := _guarded(request):
            return guard
        with session_scope() as session:
            item = session.get(Item, item_id)
            if item is None:
                return HTMLResponse(html.page("404", "<h1>Topilmadi</h1>"), status_code=404)
            enr = session.get(ItemEnrichment, item_id)
            source_name = item.source.name
            body = _item_detail(item, enr, source_name, msg)
        return HTMLResponse(html.page("Item", body, active="/items"))

    @app.post("/items/{item_id}/reenrich")
    async def item_reenrich(request: Request, item_id: int) -> RedirectResponse:
        if guard := _guarded(request):
            return guard
        with session_scope() as session:
            enr = session.get(ItemEnrichment, item_id)
            if enr is not None:
                # Dropping the enrichment returns the item to the pending set; the
                # next run (or the Run button) scores it again from current text.
                session.delete(enr)
        return RedirectResponse(f"/items/{item_id}?msg=" + _q("Qayta baholashga qo'yildi"), status_code=303)

    # ---- agent ---------------------------------------------------------------

    @app.get("/agent", response_class=HTMLResponse)
    async def agent_stats(request: Request) -> HTMLResponse:
        if guard := _guarded(request):
            return guard
        today = datetime.now(UTC).date()
        with session_scope() as session:
            enabled = list(
                session.scalars(
                    select(User).where(User.agent_enabled.is_(True)).order_by(User.username)
                )
            )
            today_total = session.scalar(
                select(func.coalesce(func.sum(AgentUsage.count), 0)).where(AgentUsage.day == today)
            ) or 0
            all_total = session.scalar(
                select(func.coalesce(func.sum(AgentUsage.count), 0))
            ) or 0
            cached = session.scalar(select(func.count()).select_from(AgentQueryCache)) or 0
            per_user = []
            for user in enabled:
                row = session.get(AgentUsage, (user.id, today))
                per_user.append(
                    [
                        f"<a href='/users/{user.id}'>{escape(user.username or str(user.telegram_id))}</a>",
                        str(row.count if row else 0),
                        str(settings.agent_daily_budget),
                    ]
                )

        cfg = get_settings()
        cards = (
            f"<div class='card'><div class='stat'>{len(enabled)}<br><small>agent yoqilgan</small></div></div>"
            f"<div class='card'><div class='stat'>{today_total}<br><small>bugungi savol</small></div></div>"
            f"<div class='card'><div class='stat'>{all_total}<br><small>jami savol</small></div></div>"
            f"<div class='card'><div class='stat'>{cached}<br><small>keshdagi javob</small></div></div>"
        )
        conf = (
            "<div class='card'><h2>Sozlama</h2>"
            f"Model: <b>{escape(cfg.agent_model)}</b><br>"
            f"Kunlik budjet: <b>{cfg.agent_daily_budget}</b><br>"
            f"Chegaralar: {cfg.agent_max_tool_calls} tool · {cfg.agent_max_web_searches} web · "
            f"{cfg.agent_max_fetches} fetch<br>"
            f"Web qidiruv: <b>{'Tavily' if cfg.tavily_api_key else 'sozlanmagan'}</b></div>"
        )
        body = (
            "<h1>Agent</h1>"
            f"<div class='grid'>{cards}</div>{conf}"
            "<h2>Yoqilgan foydalanuvchilar</h2>"
            + html.table(["User", "Bugun", "Budjet"], per_user)
            + "<p class='muted'>Suhbat tarixi (transcript) hozircha saqlanmaydi — P2.</p>"
        )
        return HTMLResponse(html.page("Agent", body, active="/agent"))

    # ---- users ---------------------------------------------------------------

    @app.get("/users", response_class=HTMLResponse)
    async def users_list(request: Request) -> HTMLResponse:
        if guard := _guarded(request):
            return guard
        with session_scope() as session:
            rows = list(session.scalars(select(User).order_by(User.created_at.desc())))
            table_rows = [_user_row(u) for u in rows]
        body = "<h1>Foydalanuvchilar</h1>" + html.table(
            ["#", "Username", "Rejim", "Vaqt", "Imp", "Mavzu", "Kalit", "Holat"], table_rows
        )
        return HTMLResponse(html.page("Foydalanuvchilar", body, active="/users"))

    @app.get("/users/{user_id}", response_class=HTMLResponse)
    async def user_detail(request: Request, user_id: int, msg: str = "") -> HTMLResponse:
        if guard := _guarded(request):
            return guard
        with session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                return HTMLResponse(html.page("404", "<h1>Topilmadi</h1>"), status_code=404)
            topics = {t.tag for t in user.topics}
            keywords = ", ".join(k.keyword for k in user.keywords)
            body = _user_form(user, topics, keywords, msg)
        return HTMLResponse(html.page("Foydalanuvchi", body, active="/users"))

    @app.post("/users/{user_id}/update")
    async def user_update(request: Request, user_id: int) -> RedirectResponse:
        if guard := _guarded(request):
            return guard
        form = await request.form()
        with session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                return RedirectResponse("/users", status_code=303)

            mode = str(form.get("digest_mode", user.digest_mode))
            if mode in _DIGEST_MODES:
                user.digest_mode = mode
            lang = str(form.get("lang", user.lang))
            if lang in _LANGS:
                user.lang = lang
            user.digest_hour = _clamp(_int(form.get("digest_hour"), user.digest_hour), 0, 23)
            user.min_importance = _clamp(_int(form.get("min_importance"), user.min_importance), 0, 10)
            tz = str(form.get("timezone", user.timezone)).strip()
            if tz:
                user.timezone = tz
            user.is_active = form.get("is_active") == "on"
            user.agent_enabled = form.get("agent_enabled") == "on"

            # Rebuild the rule sets from the form: the checked topics and the typed
            # keywords replace whatever was there.
            chosen = {str(t) for t in form.getlist("topics")} & TAG_KEYS
            for existing in list(user.topics):
                session.delete(existing)
            session.flush()
            for tag in sorted(chosen):
                session.add(UserTopic(user_id=user.id, tag=tag))

            for existing in list(user.keywords):
                session.delete(existing)
            session.flush()
            for keyword in _parse_keywords(str(form.get("keywords", ""))):
                session.add(UserKeyword(user_id=user.id, keyword=keyword))

        return RedirectResponse(f"/users/{user_id}?msg=" + _q("Saqlandi"), status_code=303)

    return app


# --- small helpers ------------------------------------------------------------


def _q(text: str) -> str:
    from urllib.parse import quote

    return quote(text)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_keywords(raw: str) -> list[str]:
    seen: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        keyword = part.strip().lower()[:32]
        if keyword and keyword not in seen:
            seen.append(keyword)
        if len(seen) >= 20:
            break
    return seen


def _select(name: str, options, current) -> str:
    opts = "".join(
        f"<option value='{escape(str(value))}'{' selected' if value == current else ''}>"
        f"{escape(str(label))}</option>"
        for value, label in options
    )
    return f"<select name='{escape(name)}'>{opts}</select>"


def _fmt(when, default: str = "—") -> str:
    if when is None:
        return default
    return as_utc(when).strftime("%m-%d %H:%M")


def _source_row(source: Source, count: int) -> list[str]:
    status = "✅" if source.enabled else "⏸"
    edit = (
        f"<form method='post' action='/sources/{source.id}/update' class='row' style='gap:.3rem'>"
        f"<input name='url' value='{escape(source.url)}' size='28'>"
        f"<input name='kind' value='{escape(source.kind)}' size='6'>"
        f"<input name='trust_tier' type='number' min='1' max='3' value='{source.trust_tier}' size='2'>"
        f"<label style='display:inline;margin:0'><input type='checkbox' name='enabled'"
        f"{' checked' if source.enabled else ''}> on</label>"
        "<button class='ghost'>Saqla</button></form>"
        f"<form method='post' action='/sources/{source.id}/delete' class='inline'>"
        "<button class='danger'>O'chir</button></form>"
    )
    return [
        escape(source.name),
        str(source.trust_tier),
        f"<span class='muted'>{escape(source.url)}</span>",
        str(count),
        status,
        edit,
    ]


def _item_row(item: Item, enr: ItemEnrichment | None) -> list[str]:
    imp = str(enr.importance) if enr else "—"
    tags = " ".join(f"<span class='tag'>{escape(t)}</span>" for t in (enr.tags if enr else []))
    return [
        str(item.id),
        f"<span class='muted'>{_fmt(item.published_at or item.fetched_at)}</span>",
        escape(item.source.name),
        f"<a href='/items/{item.id}'>{escape(item.title)}</a>",
        imp,
        tags,
    ]


def _item_detail(item: Item, enr: ItemEnrichment | None, source_name: str, msg: str) -> str:
    flash = f"<p class='flash'>{escape(msg)}</p>" if msg else ""
    meta = (
        f"<p class='muted'>{escape(source_name)} · {_fmt(item.published_at or item.fetched_at)}</p>"
        f"<p><a href='{escape(item.url)}' target='_blank'>{escape(item.url)}</a></p>"
    )
    if enr:
        tags = " ".join(f"<span class='tag'>{escape(t)}</span>" for t in enr.tags)
        ents = " ".join(f"<span class='tag'>{escape(e)}</span>" for e in (enr.entities or []))
        enrich = (
            f"<div class='card'><b>Importance:</b> {enr.importance}/10<br>"
            f"<b>Teglar:</b> {tags or '—'}<br><b>Entities:</b> {ents or '—'}<br>"
            f"<b>Summary:</b> {escape(enr.summary)}<br>"
            f"<b>Summary UZ:</b> {escape(enr.summary_uz or '—')}<br>"
            f"<span class='muted'>{escape(enr.model_used)} · {_fmt(enr.enriched_at)}</span></div>"
        )
    else:
        enrich = "<div class='card muted'>Hali baholanmagan.</div>"
    reenrich = (
        f"<form method='post' action='/items/{item.id}/reenrich' class='inline'>"
        "<button class='ghost'>Qayta baholash</button></form>"
    )
    text = escape(item.raw_text) if item.raw_text else "(matn yo'q yoki tozalangan)"
    return (
        f"<p><a href='/items'>← ro'yxat</a></p>{flash}"
        f"<h1>{escape(item.title)}</h1>{meta}{enrich}{reenrich}"
        f"<h2>To'liq matn</h2><pre>{text}</pre>"
    )


def _user_row(user: User) -> list[str]:
    status = "✅" if user.is_active else "⏸"
    return [
        f"<a href='/users/{user.id}'>{user.id}</a>",
        escape(user.username or "—"),
        escape(user.digest_mode),
        f"{user.digest_hour:02d}:00 {escape(user.timezone)}",
        str(user.min_importance),
        str(len(user.topics)),
        str(len(user.keywords)),
        status,
    ]


def _user_form(user: User, topics: set[str], keywords: str, msg: str) -> str:
    flash = f"<p class='flash'>{escape(msg)}</p>" if msg else ""
    topic_boxes = "".join(
        "<label style='display:inline-block;margin:.2rem .6rem .2rem 0'>"
        f"<input type='checkbox' name='topics' value='{escape(tag.key)}'"
        f"{' checked' if tag.key in topics else ''}> {escape(tag.label_uz)}</label>"
        for tag in TAGS
    )
    modes = _select("digest_mode", [(m, m) for m in _DIGEST_MODES], user.digest_mode)
    langs = _select("lang", [(m, m) for m in _LANGS], user.lang)
    return (
        f"<p><a href='/users'>← ro'yxat</a></p>{flash}"
        f"<h1>@{escape(user.username or str(user.telegram_id))}</h1>"
        f"<p class='muted'>telegram id {user.telegram_id} · a'zo bo'ldi {_fmt(user.created_at)}"
        f" · oxirgi yig'ma {_fmt(user.last_digest_at)}</p>"
        f"<form method='post' action='/users/{user.id}/update'>"
        "<div class='row'>"
        f"<div><label>Rejim</label>{modes}</div>"
        f"<div><label>Til</label>{langs}</div>"
        f"<div><label>Soat</label><input name='digest_hour' type='number' min='0' max='23' value='{user.digest_hour}' size='2'></div>"
        f"<div><label>Mintaqa</label><input name='timezone' value='{escape(user.timezone)}'></div>"
        f"<div><label>Min importance</label><input name='min_importance' type='number' min='0' max='10' value='{user.min_importance}' size='2'></div>"
        "<div><label>Faol</label><input type='checkbox' name='is_active'"
        f"{' checked' if user.is_active else ''}></div>"
        "<div><label>Agent (/ask)</label><input type='checkbox' name='agent_enabled'"
        f"{' checked' if user.agent_enabled else ''}></div>"
        "</div>"
        f"<label>Mavzular (qoidalar)</label><div>{topic_boxes}</div>"
        f"<label>Kalit so'zlar</label><input name='keywords' size='50' value='{escape(keywords)}'>"
        "<div style='margin-top:.8rem'><button>Saqlash</button></div></form>"
    )

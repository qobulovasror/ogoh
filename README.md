# Ogoh

AI yangiliklarini yig'ib, saralab, har kimga o'zi so'ragan turdagisini Telegram
orqali yetkazadi. Ustiga — `/ask` bilan suhbatlashadigan qidiruv agenti va
operator uchun veb admin panel.

Batafsil arxitektura va fazalar: [PLAN.md](PLAN.md), agent uchun [AGENT_PLAN.md](AGENT_PLAN.md).

## Holat

Multi-user ishlaydi. 12 ta manba → dedupe → to'liq matn → Gemini saralash →
kunlik chuqur tahlil → har bir foydalanuvchiga o'z mavzulari bo'yicha digest.
Yoniga: interaktiv `/ask` agenti (korpus + veb qidiruv) va admin panel.

214 ta test, `uv run pytest`.

## Ishga tushirish

```bash
uv sync
cp .env.example .env
```

`.env` ga kalitlarni yoz:
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey (tekin, karta kerak emas).
  Bir nechta kalit vergul bilan — yuk taqsimlash va 429 da o'tish uchun aylantiriladi:
  `GEMINI_API_KEY=key_one,key_two`
- `TELEGRAM_BOT_TOKEN` — [@BotFather](https://t.me/BotFather) da `/newbot`

Qolgan hamma sozlama kodda default bilan keladi — o'zgartirmoqchi bo'lganingni
[.env.example](.env.example) dan ko'chirib yoq (Groq fallback, agent limitlari,
admin panel, Redis va h.k.).

```bash
uv run ogoh-bot      # bot + har 20 daqiqada pipeline. Asosiy rejim.
uv run ogoh-admin    # veb admin panel (127.0.0.1:8000). Ixtiyoriy.
```

Bir martalik ishga tushirish (bot siz, tekshirish uchun):

```bash
uv run ogoh --dry-run   # faqat yig'adi, LLM chaqirmaydi, kalit kerak emas
uv run ogoh             # yig'adi, saralaydi, konsolga chiqaradi
uv run ogoh --send      # TELEGRAM_CHAT_ID ga bitta umumiy digest yuboradi
```

## Deploy

Compose'da ikkita servis: `bot` (bot + pipeline) va `admin` (veb panel). Ikkalasi
ham bir xil image va bir xil `ogoh-data` volume ini ulashadi.

```bash
# VPS da
git clone <repo> && cd ogoh
cp .env.example .env && nano .env    # kalitlarni yoz
docker compose up -d --build
docker compose logs -f
```

Admin panel faqat loopback ga bog'lanadi (`127.0.0.1:8000`) — internetga ochiq
emas. SSH tunnel bilan kir: `ssh -L 8000:127.0.0.1:8000 vps`. Publik ochish kerak
bo'lsa, oldiga TLS (reverse proxy) qo'y — kirish kodi ochiq ketadi.

DB `ogoh-data` volume ida. Backup — bitta fayl:

```bash
docker compose cp bot:/data/ogoh.db ./backup-$(date +%F).db
```

Migratsiya bot ishga tushganda avtomatik ishlaydi (`init_db` → `alembic upgrade head`).
Qo'lda qadam yo'q.

### Ikkita tuzoq

**1. Bot faqat bitta joyda ishlashi mumkin.** Telegram long-polling da bitta
`getUpdates` iste'molchisi bo'ladi. Noutbukda ham, VPS da ham ishlab tursa —
Telegram `409 Conflict` qaytaradi va ikkalasi ham ishonchsiz ishlaydi. Deploydan
keyin lokalni o'chir.

**2. Lokal `ogoh.db` VPS ga o'zi ko'chmaydi.** Deploydan keyin DB yangi bo'ladi —
botga qayta `/start` yozish kerak. Yoki eski faylni ko'chir:

```bash
docker compose cp ./ogoh.db bot:/data/ogoh.db && docker compose restart bot
```

## Migratsiya

Sxema o'zgartirsang:

```bash
uv run alembic revision --autogenerate -m "nima o'zgardi"
uv run alembic check      # model va DB mos kelishini tekshiradi
uv run alembic current    # joriy versiya
```

`create_all` ataylab ishlatilmaydi: u yetishmagan jadvalni qo'shadi, lekin
o'zgargan ustunni tegmay qoldiradi — ya'ni sxema va model jimgina ayrilib ketadi.

## Bot buyruqlari

| Buyruq | Vazifa |
|---|---|
| `/start` | ro'yxatdan o'tish |
| `/topics` | mavzu tanlash (10 ta teg, bosib yoq/o'chir) |
| `/keywords` | erkin kalit so'zlar (teglardan tashqari) |
| `/freq` | darhol / kunlik / haftalik / o'chirilgan |
| `/time` | kunlik yig'ma soati |
| `/zone` | vaqt mintaqa (soat shu bo'yicha hisoblanadi) |
| `/level` | muhimlik chegarasi (past = ko'proq xabar) |
| `/lang` | xulosalar tili (o'zbekcha / inglizcha) |
| `/settings` | hamma sozlama bir ekranda |
| `/preview` | hozir nima borligini ko'rish (yuborilgan deb belgilanmaydi) |
| `/sources` | manba sog'ligi (bir hafta jim feed belgilanadi) |
| `/stats` | umumiy holat (obunachi, oqim, jim manba soni) |
| `/pause` | vaqtincha to'xtatish |
| `/stop` | obunani bekor qilish (o'chirmaydi, sozlama qoladi) |
| `/ask` | qidiruv agenti bilan suhbat (yoqilgan foydalanuvchiga) |
| `/admin` | admin panelga bir martalik kod (faqat admin) |

Har bir yangilik ostida 👍/👎 tugmalari. Mavzu tanlanmasa — hammasi yuboriladi.
`instant` rejim faqat 8/10 va undan yuqori bahoni yuboradi (model chiqishi, limit
o'zgarishi).

## Qidiruv agenti (`/ask`)

Yoqilgan foydalanuvchi `/ask` bilan suhbat ochadi va savol beradi — agent javob
qidirib topadi. Loop `decide → act → observe`: model harakatni **nomlaydi**,
tool'ni runner ishlatib, natijani observation qilib qaytaradi. Model tool'larga
to'g'ridan-to'g'ri tegmaydi.

- **Korpus avval, veb keyin.** `search_corpus` bepul (o'z do'konimiz); `web_search`
  faqat model so'raganda va limit yetsa (Tavily kaliti bilan — `TAVILY_API_KEY`).
  Kalitsiz agent faqat korpusdan ishlaydi.
- **Chegaralangan.** Bir savolga qadam soni (`AGENT_MAX_TOOL_CALLS`), veb qidiruv,
  sahifa yuklash — hammasi capped. Cap urilsa model borига javob berishga majbur.
- **Arzon uchta yo'l bilan.** Korpus vebdan oldin; takror savol cache'dan (TTL);
  har yangi savol kunlik budjetdan bitta birlik yeydi (`AGENT_DAILY_BUDGET`).
- **Eskalatsiya.** Qiyin turda model bir marta kuchliroq modelga o'tadi
  (`AGENT_MODEL_HEAVY`) — sozlanmasa no-op.
- **Xavfsizlik.** Tool qaytargan matn *ma'lumot*, ko'rsatma emas — prompt injection'ga
  qarshi loop har observation'ni tool natijasi deb belgilaydi.
- FSM holati suhbatni xabarlar orasida saqlaydi; `REDIS_URL` bo'lsa restart'dan
  o'tadi, bo'lmasa xotirada. `/done` — suhbatni yopadi.

## Admin panel

FastAPI, server-render, bitta modul route. Kirish: botda `/admin` yozib bir
martalik kod olasan (faqat `ADMIN_TELEGRAM_ID`), keyin imzolangan cookie bilan
sessiya. Bot va pipeline bilan bir xil DB ga yozadi.

| Sahifa | Nima |
|---|---|
| `/` | boshqaruv paneli + qo'lda `/run` |
| `/sources` | manba qo'shish / tahrir / o'chirish |
| `/items` | yangiliklar, bittasini qayta baholash |
| `/agent` | agent transkriptlari va foydalanish |
| `/users` | foydalanuvchi sozlamalarini ko'rish/tahrir |

## Manbalar

| Manba | Usul | Daraja |
|---|---|---|
| Claude Platform release notes | markdown changelog | 1 |
| Claude Code releases | GitHub Atom | 1 |
| OpenAI News | RSS | 1 |
| Google AI blog | RSS | 1 |
| Hugging Face blog | RSS | 1 |
| arXiv (cs.AI, cs.CL) | Atom API | 2 |
| Simon Willison | RSS | 2 |
| Ars Technica AI | RSS | 2 |
| The Verge AI | RSS | 3 |
| Hacker News (100+ ball) | RSS | 3 |
| TechCrunch AI | RSS | 3 |
| Reddit r/LocalLLaMA | RSS | 3 |

Daraja = bir yangilikni bir necha manba yozganda, kim vakolat bilan gapiryapti
(1 = birlamchi, 2 = ekspert, 3 = matbuot). Yangi manba qo'shish = `sources/` da
bitta fayl, `SourceFetcher` protokolini bajarsin va `registry.py` ga qo'shilsin.

## LLM provayderlari

Bitta abstraksiya, ikki qatlam kompozitsiya:

- **Gemini** — asosiy. Bir nechta kalit berilsa `RotatingProvider` ular orasida
  aylanadi (yuk taqsimlash + 429 failover).
- **Groq** — ixtiyoriy fallback, alohida kvota. Gemini yiqilsa enrich/dedupe/research
  Groq ga tushadi. `GROQ_API_KEY` qo'yilmasa o'chiq.

`FallbackProvider([rotating_gemini, groq])` — birinchisi yiqilsa keyingisiga o'tadi.

## Nima qayerda

```
sources/     manba adapterlari (rss, changelog)
pipeline/    ingest -> normalize -> dedupe -> extract -> enrich -> research -> match -> digest -> retention
llm/         provider abstraksiyasi (gemini, groq, fallback, rotating) + prompt
agent/       /ask agenti: runner, korpus/veb qidiruv, budjet, cache, audit
bot/         aiogram handlerlar, agent handlerlar, klaviaturalar
admin/       FastAPI veb panel (auth, route, html)
notify/      Telegram yetkazish
worker.py    davriy vazifa: pipeline + yetkazish
db/          SQLAlchemy modellar
migrations/  alembic
tests/       214 test
```

Ikkita bosqich e'tiborga loyiq — ikkalasi ham "jimgina yo'qotish" muammosini yopadi:

- **`extract`** — feed lead i kalta bo'lganda to'liq maqola matnini yuklaydi. Feed
  lead i bilan LLM OpenAI ning flagship model e'loniga 2/10 qo'ygan edi, to'liq matn
  bilan 10/10 — `min_importance=5` da yuborilmasdan qolardi.
- **`research`** — kuniga bir marta kunning eng muhim yangiligiga ~120 so'zlik chuqur
  tahlil yozadi: nima o'zgardi, kimga ta'sir qiladi, nima noaniq. Web qidiruv emas,
  o'z korpusimiz asosida — chunki qiymat *tarixda*: bugungi e'lonni o'tgan haftalardagi
  yangiliklar bilan bog'lashda. Batafsil: [PLAN.md](PLAN.md).

## Xarajat

Har bir ishga tushirishda LLM chaqiruvlari: enrich (20 tadan batch), dedupe hukmi
(kuniga ~1), research (kuniga ~1). Har 20 daqiqada ishlaganda kuniga ~50 chaqiruv —
Gemini free tier limiti 1500/kun, ya'ni ~3%. `/ask` agenti ustiga qo'shadi, lekin
har foydalanuvchiga kunlik budjet bilan chegaralangan (`AGENT_DAILY_BUDGET`).
Embedding va grounding ishlatilmaydi. Pul xarajati: faqat VPS (~€4/oy).

## Ma'lum cheklovlar

- **Anthropic dan faqat release notes.** `anthropic.com/news` da RSS ham, sitemap ham
  yo'q, HTML klasslari esa har build da o'zgaradigan hash. Release notes model va
  limit o'zgarishlarini qamrab oladi — asosiy ehtiyoj shu.
- **~10% item hali kalta matnli** — ba'zi saytlar botlarni rad etadi (techdirt 403),
  ular feed lead ida qoladi va shunga qarab baholanadi.
- **Grounding yo'q.** Research o'z korpusimizda ishlaydi. Gemini ning `google_search`
  grounding i free tier da 429 beradi (billing yoqilgan loyihalarga tegishli). Agent
  vebni Tavily orqali qidiradi, Gemini grounding orqali emas.
- **Feedback yig'iladi, lekin hali ishlatilmaydi.** 👍/👎 saqlanadi; sozlash uchun
  yetarli ovoz to'planganda mos algoritm qo'shiladi.
- **SQLite.** Bot va admin bitta faylga yozadi (admin — yengil ikkinchi o'quvchi).
  ~46 MB/yil — bu miqyosda yetarli. Postgres yana bir yozuvchi paydo bo'lganda.
  Backup: `docker compose cp` bilan bitta fayl.
- **`max_age_days=14`** — undan eski yangilik olinmaydi.

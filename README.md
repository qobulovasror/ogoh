# Ogoh

AI yangiliklarini yig'ib, saralab, har kimga o'zi so'ragan turdagisini Telegram
orqali yetkazadi.

Batafsil arxitektura va fazalar: [PLAN.md](PLAN.md)

## Holat

Multi-user ishlaydi. 12 ta manba → dedupe → to'liq matn → Gemini saralash →
kunlik chuqur tahlil → har bir foydalanuvchiga o'z mavzulari bo'yicha digest.

146 ta test, `uv run pytest`.

## Ishga tushirish

```bash
uv sync
cp .env.example .env
```

`.env` ga kalitlarni yoz:
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey (tekin, karta kerak emas)
- `TELEGRAM_BOT_TOKEN` — [@BotFather](https://t.me/BotFather) da `/newbot`

```bash
uv run ogoh-bot      # bot + har 20 daqiqada pipeline. Asosiy rejim.
```

Bir martalik ishga tushirish (bot siz, tekshirish uchun):

```bash
uv run ogoh --dry-run   # faqat yig'adi, LLM chaqirmaydi, kalit kerak emas
uv run ogoh             # yig'adi, saralaydi, konsolga chiqaradi
uv run ogoh --send      # TELEGRAM_CHAT_ID ga bitta umumiy digest yuboradi
```

## Deploy

```bash
# VPS da
git clone <repo> && cd ogoh
cp .env.example .env && nano .env    # kalitlarni yoz
docker compose up -d --build
docker compose logs -f
```

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
| `/freq` | darhol / kunlik / haftalik / o'chirilgan |
| `/lang` | xulosalar tili (o'zbekcha / inglizcha) |
| `/preview` | hozir nima borligini ko'rish (yuborilgan deb belgilanmaydi) |
| `/pause` | vaqtincha to'xtatish |
| `/stop` | butunlay o'chirish |

Har bir yangilik ostida 👍/👎 tugmalari. Mavzu tanlanmasa — hammasi yuboriladi.
`instant` rejim faqat 8/10 va undan yuqori bahoni yuboradi (model chiqishi, limit
o'zgarishi).

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

## Nima qayerda

```
sources/     manba adapterlari (rss, changelog)
pipeline/    ingest -> dedupe -> extract -> enrich -> research -> match -> digest
llm/         provider abstraksiyasi + prompt
bot/         aiogram handlerlar, klaviaturalar
worker.py    davriy vazifa: pipeline + yetkazish
db/          SQLAlchemy modellar
migrations/  alembic
tests/       146 test
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
Gemini free tier limiti 1500/kun, ya'ni ~3%. Embedding va grounding ishlatilmaydi.
Pul xarajati: faqat VPS (~€4/oy).

## Ma'lum cheklovlar

- **Anthropic dan faqat release notes.** `anthropic.com/news` da RSS ham, sitemap ham
  yo'q, HTML klasslari esa har build da o'zgaradigan hash. Release notes model va
  limit o'zgarishlarini qamrab oladi — asosiy ehtiyoj shu.
- **~10% item hali kalta matnli** — ba'zi saytlar botlarni rad etadi (techdirt 403),
  ular feed lead ida qoladi va shunga qarab baholanadi.
- **Grounding yo'q.** Research o'z korpusimizda ishlaydi. Gemini ning `google_search`
  grounding i free tier da 429 beradi (billing yoqilgan loyihalarga tegishli).
- **Feedback yig'iladi, lekin hali ishlatilmaydi.** 👍/👎 saqlanadi; sozlash uchun
  yetarli ovoz to'planganda mos algoritm qo'shiladi.
- **SQLite.** Bitta jarayon, ~46 MB/yil — bu miqyosda yetarli. Postgres ikkinchi
  yozuvchi paydo bo'lganda. Backup: `docker compose cp` bilan bitta fayl.
- **`max_age_days=14`** — undan eski yangilik olinmaydi.

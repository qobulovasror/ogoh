# Ogoh

AI yangiliklarini yig'ib, saralab, har kimga o'zi so'ragan turdagisini Telegram
orqali yetkazadi.

Batafsil arxitektura va fazalar: [PLAN.md](PLAN.md)

## Holat

Multi-user ishlaydi. 8 ta manba → dedupe → Gemini saralash → har bir foydalanuvchiga
o'z mavzulari bo'yicha digest.

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
| `/preview` | hozir nima borligini ko'rish (yuborilgan deb belgilanmaydi) |
| `/pause` | vaqtincha to'xtatish |
| `/stop` | butunlay o'chirish |

Mavzu tanlanmasa — hammasi yuboriladi. `instant` rejim faqat 8/10 va undan yuqori
bahoni yuboradi (model chiqishi, limit o'zgarishi).

## Manbalar

| Manba | Usul |
|---|---|
| Claude Platform release notes | markdown changelog |
| Claude Code releases | GitHub Atom |
| OpenAI News | RSS |
| Simon Willison | RSS |
| Hugging Face blog | RSS |
| Ars Technica AI | RSS |
| Hacker News (100+ ball) | RSS |
| TechCrunch AI | RSS |

Yangi manba qo'shish = `sources/` da bitta fayl, `SourceFetcher` protokolini
bajarsin va `registry.py` ga qo'shilsin. Boshqa joyga tegmaydi.

## Nima qayerda

```
sources/     manba adapterlari (rss, changelog)
pipeline/    ingest -> dedupe -> extract -> enrich -> match -> digest
llm/         provider abstraksiyasi + prompt
bot/         aiogram handlerlar, klaviaturalar
worker.py    davriy vazifa: pipeline + yetkazish
db/          SQLAlchemy modellar
migrations/  alembic
```

`extract` — feed lead i kalta bo'lgan itemlar uchun to'liq maqola matnini yuklaydi.
Ustuvorligi yuqori: feed lead i bilan LLM OpenAI ning flagship model e'loniga 2/10
qo'ygan edi, to'liq matn bilan 10/10. Batafsil: [PLAN.md](PLAN.md).

## Xarajat

Bir ishga tushirishda ~130 yangilik yig'iladi, 20 tadan batch qilinib ~7 ta LLM
chaqiruv ketadi. Har 20 daqiqada ishlaganda ham kuniga ~50 chaqiruv — Gemini free
tier limiti 1500/kun. Pul xarajati: faqat VPS.

## Ma'lum cheklovlar

- **Dedupe faqat leksik.** Sarlavhalari deyarli bir xil dubllarni tutadi (chegara 0.85).
  Ma'no bir xil, so'z boshqa bo'lsa — o'tkazib yuboradi. Sabab va o'lchov:
  `pipeline/dedupe.py` docstring. Embedding P2 da.
- **Anthropic dan faqat release notes.** `anthropic.com/news` da RSS ham, sitemap ham
  yo'q, HTML klasslari esa har build da o'zgaradigan hash. Release notes model va
  limit o'zgarishlarini qamrab oladi — asosiy ehtiyoj shu.
- **~10% item hali kalta matnli** — ba'zi saytlar botlarni rad etadi (techdirt 403),
  ular feed lead ida qoladi va shunga qarab baholanadi.
- **SQLite + `create_all`.** Migratsiya yo'q — sxema o'zgarsa DB ni o'chirib qayta
  yaratish kerak. Alembic + Postgres deploydan oldin.
- **`max_age_days=14`** — undan eski yangilik olinmaydi.

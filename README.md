# Ogoh

AI yangiliklarini yig'ib, saralab, Telegram orqali yetkazadi.

Batafsil arxitektura va fazalar: [PLAN.md](PLAN.md)

## Hozirgi holat — P0

Pipeline boshidan oxirigacha ishlaydi: **5 ta RSS manba → SQLite → Gemini saralash → Telegram**.

Multi-user hali yo'q (P1). Hozircha bitta umumiy digest, o'zingga yuboriladi.

## Ishga tushirish

```bash
uv sync
cp .env.example .env
```

`.env` ga `GEMINI_API_KEY` yoz — https://aistudio.google.com/apikey (tekin, karta kerak emas).

```bash
uv run ogoh --dry-run   # faqat RSS yig'adi, LLM chaqirmaydi, kalit kerak emas
uv run ogoh             # yig'adi, saralaydi, konsolga chiqaradi
uv run ogoh --send      # ustiga Telegram ga yuboradi
```

Telegram uchun qo'shimcha: [@BotFather](https://t.me/BotFather) da `/newbot` qilib
`TELEGRAM_BOT_TOKEN` ol, [@userinfobot](https://t.me/userinfobot) dan o'z raqamli
id ingni olib `TELEGRAM_CHAT_ID` ga yoz. Botga bir marta `/start` yubor — aks holda
u senga yoza olmaydi.

### Foydali flaglar

| Flag | Vazifa |
|---|---|
| `--dry-run` | LLM siz, faqat ingest |
| `--limit N` | shu safar faqat N ta item enrich qilinadi |
| `--min-importance N` | chegarani vaqtincha o'zgartirish |
| `-v` | debug loglar |

## Nima qayerda

```
sources/     manba adapterlari — yangi manba = bitta yangi fayl
pipeline/    ingest -> normalize -> enrich -> digest
llm/         provider abstraksiyasi + prompt
notify/      Telegram yuborish
db/          SQLAlchemy modellar
```

## Xarajat

Bir ishga tushirishda ~100 yangilik yig'iladi, 20 tadan batch qilinib **~6 ta LLM chaqiruv**
ketadi. Gemini free tier — 1500 chaqiruv/kun. Har 20 daqiqada ishlatsang ham kvotaning
kichik qismi ishlatiladi.

## Ma'lum cheklovlar (P0)

- Dedupe faqat URL bo'yicha. Bir yangilikni 2 ta sayt boshqa sarlavha bilan yozsa,
  ikkalasi ham o'tadi. Simhash P1 da, embedding cluster P2 da.
- Anthropic manbasi yo'q — ularda RSS yo'q, scraper P1 da.
- Matn faqat RSS lead idan olinadi. To'liq maqola matni (`trafilatura`) P2 da.
- `max_age_days=14` — undan eski yangilik umuman olinmaydi.

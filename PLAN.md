# Ogoh — Reja

AI yangiliklarini avtomatik yig'uvchi, filtrlovchi va har bir foydalanuvchiga
uning qiziqishiga qarab yetkazuvchi Telegram bot.

**Ko'lam:** 10-50 foydalanuvchi (men + do'stlar)
**Kanal:** Telegram bot + Mini App (sozlamalar UI) + web admin panel
**LLM:** Google Gemini free tier (asosiy), Groq (zaxira)

---

## 1. Asosiy arxitektura qarori

> **LLM ga "internetdan yangilik qidir" dema.**

Sabab: qimmat, sekin, ishonchsiz, hallucinate qiladi, va kvotani bir kunda yeydi.

**O'rniga:** manbalarni RSS/API orqali *deterministik* yig'. LLM faqat uchta ishni qilsin:
tasnif (classify), muhimlik bahosi (score), qisqartirish (summarize). Matn allaqachon
qo'lingda bo'ladi — LLM hech narsa qidirmaydi.

Natija: LLM chaqiruv soni kuniga ~20 ta. Gemini free limit — 1500/kun. Ya'ni **kvotaning
~1% i ishlatiladi.**

Istisno: kunda bir marta, eng muhim 3 ta yangilik uchun *active research* agent ishlaydi
(Gemini + `google_search` grounding) — chuqurroq kontekst yig'adi. Bu yerda AI haqiqatan
tadqiqot qiladi, lekin cheklangan hajmda.

---

## 2. LLM provider tanlovi

| Provider | Model ID | Free limit | Rol |
|---|---|---|---|
| Gemini Flash-Lite | `gemini-3.1-flash-lite` | 15 RPM | **asosiy** — classify/summarize |
| Gemini Flash | `gemini-3.5-flash` | 10 RPM, 250k TPM, 1500 req/kun | og'irroq ish uchun |
| Gemini Embedding | `gemini-embedding-001` | tekin | dedupe (P2) |
| Groq | — | 30 RPM, **6k TPM**, ~1k req/kun | zaxira (fallback) |
| OpenRouter `:free` | — | 20 RPM, 50 req/kun | uchinchi zaxira |

> Model ID lari rasmiy hujjatdan tekshirilgan. Ilgari yozgan `gemini-3-flash` va
> `text-embedding-004` — ikkalasi ham mavjud emas.

**Nega Gemini:** yangilik qisqartirish **TPM-og'ir** ish, RPM-og'ir emas. Groq ning
6k TPM si bitta o'rtacha maqolaga ham zo'rg'a yetadi. Gemini ning 250k TPM si — 40 barobar keng.
Karta ham kerak emas.

Groq ni zaxira qil: alohida kvota, Gemini yiqilsa avtomatik o'tib ketadi.
Kod darajasida `LLMProvider` interface qil — provider almashtirish bitta config o'zgarishi bo'lsin.
Free tier shartlari o'zgaradi; abstraksiya bugun arzon, keyin qimmat.

Embedding: Gemini `gemini-embedding-001` — u ham tekin.

---

## 3. Stack (tanlangan)

**Backend: Python**

Sabab — bitta hal qiluvchi argument: **`trafilatura`**. HTML dan maqola matnini toza ajratib
olish bu loyihaning eng iflos qismi, va trafilatura dan yaxshiroq JS ekvivalenti yo'q.
Shuningdek `feedparser` buzuq RSS feed larni `rss-parser` dan ancha chidamli hazm qiladi.
Backend og'ir ishni qiladi (parse, extract, dedupe, embed, schedule) — Python u yerda ustun.

Frontend baribir alohida build bo'ladi, shuning uchun "bitta til" argumenti bu yerda kuchsiz.

```
Backend:    Python 3.12 + FastAPI + aiogram + APScheduler + SQLAlchemy
Parsing:    feedparser, trafilatura, httpx
LLM:        google-genai SDK
DB:         Postgres 16 + pgvector
Frontend:   Vite + React (bitta app, ikkita route: /app = Mini App, /admin = panel)
Deploy:     VPS (Hetzner CX22 ~€4/oy) + docker-compose
```

### Postgres rad etildi — SQLite qoldi (o'lchangan)

Reja Postgres + pgvector deb yozgan edi. O'lchov boshqa narsa ko'rsatdi:

| | Raqam |
|---|---|
| DB hajmi (131 item + 14 kun tarix) | **312 KB** |
| Yillik o'sish (kuniga ~30 item) | ~25 MB |
| Yozuvchi jarayonlar | **1 ta** |
| Foydalanuvchi | 10-50 |

Postgres beradigan narsalar va ularning hozirgi holati:
- *Parallel yozuvchilar* — bitta jarayon bor. Kerak emas.
- *pgvector* — P2 da 11k item × 768 float. Python da 500 ta yaqin item ustida
  cosine — mikrosoniya. Kerak emas.
- *Miqyos* — 25 MB/yil. Kulgili.

Evaziga: konteyner, parol, volume, backup strategiyasi, kechasi buziladigan yana
bitta komponent. Bu miqyosda SQLite yutadi. Backup — 312 KB faylni nusxalash.

**Alembic esa boshqa masala** — u Postgres bilan bog'liq emas, SQLite da ham
ishlaydi, va u haqiqatan kerak edi: foydalanuvchi ma'lumoti paydo bo'lgach
`create_all` bilan davom etish sxema o'zgarishida uni yo'q qiladi. Reja ikkovini
bitta bandga bog'lab, kerakmasini kerakliga tirkab qo'ygan ekan.

**Qachon qaytamiz:** ikkinchi yozuvchi jarayon paydo bo'lsa, yoki vector search
Python halqasidan oshib ketsa.

---

## 4. Ma'lumot oqimi (pipeline)

```
Manbalar (RSS / HN API / arXiv / GitHub / scrape)
   │  har 20 daqiqada
   ▼
Ingest      fetch → normalize → items jadvali
   ▼
Prefilter   arzon darvoza (LLM siz) — 300 ta → ~120 ta
   ▼
Dedupe      url hash → simhash → embedding cluster
   ▼
Enrich      LLM batch (20 ta/prompt) → tags, importance, summary
   ▼
Match       har user uchun: tags ∩ interests, importance ≥ threshold, keywords
   ▼
Digest      user jadvali bo'yicha (instant / daily / weekly)
   ▼
Deliver     Telegram
```

### Prefilter — LLM dan oldingi arzon darvoza

Hamma narsani LLM ga berma. Avval arzon filtr:

- Manba ishonch darajasi (Anthropic rasmiy = doim o'tadi)
- Barcha userlar qiziqishlari birlashmasi + taxonomy seed so'zlari bo'yicha keyword match
- HackerNews: `score >= 50`
- arXiv: title/abstract keyword hit bo'lmasa tashla

Natija: 300 → 120. LLM chaqiruvning 60% i tejaladi.

### Dedupe — 3 daraja

Bir yangilikni 10 ta sayt yozadi. Dedupe ishlamasa user spam yeydi va chiqib ketadi.
**MVP da ham kerak — keyinga qoldirma.**

1. **URL canonicalize** ✅ — `utm_*` va fragment ni olib tashla, trailing slash
   normalize → `sha256` → DB da `UNIQUE`. Aniq takrorlarni o'ldiradi.
   *Ogohlantirish:* fragment tashlash changelog kabi anchor bilan adreslanadigan
   sahifalarni buzadi — har bir yozuv bitta hash ga tushadi. Shuning uchun `RawItem.uid`:
   manba kerak bo'lsa o'z identifikatorini o'zi e'lon qiladi.
2. ~~**Simhash**~~ → **Jaccard ≥ 0.85** ✅ — avtomatik qo'shish, sabab quyida.
3. ~~**Embedding cosine > 0.88**~~ → **LLM hukmi** ✅ — *reja rad etildi, sabab quyida.*

### Nega embedding emas, LLM (o'lchangan — reja rad etildi)

Reja 3-daraja uchun `embedding cosine > 0.88` degan edi. O'lchadim:

```
                                                    jaccard   cosine
ROST    "xai-org/grok-build, now open source"
        "Grok Build is open source"                   0.67     0.942
YOLGON  "sqlite-utils 4.1.1" / "sqlite-utils 4.0"     0.50     0.960
```

**Cosine da yolg'on juftlik rost juftlikdan yuqori.** Masofa: −0.018. To'liq matn
qo'shsam yomonlashadi: −0.045. Ya'ni ishlaydigan chegara mavjud emas.

Reja shu yerda nafaqat foydasiz, balki **zararli** edi: `> 0.88` ikkala relizni
qo'shib yuborardi va ikkinchisi izsiz yo'qolardi.

Sabab: embedding "bir xil **mavzu**" ni o'lchaydi. `4.1.1` va `4.0` haqiqatan bir
xil mavzu — bir loyiha, bir turdagi e'lon. Embedding to'g'ri javob beryapti,
faqat savol noto'g'ri berilgan.

**LLM to'g'ri savolga javob beradi** — o'lchangan 8 juftlikda 8/8, ustiga sababini
aytadi: "different software versions", "different products". Jonli ma'lumotda: 9 ta
nomzoddan 1 tasini qo'shdi (`grok-build`, "Identical news about the same project"),
8 tasini to'g'ri ajratdi.

Shuning uchun o'xshashlik o'z o'rniga tushirildi — **nomzod taklif qilish**, hukm
emas:

```
>= 0.85           deyarli aniq  -> darhol qo'shiladi, LLM chaqirilmaydi
[0.45, 0.85)      noaniq        -> LLM hukm qiladi
< 0.45            begona        -> tegilmaydi
```

Kuniga ~1 qo'shimcha chaqiruv. LLM yiqilsa yoki javob bermasa — juftlik ajratilgan
holda qoladi: ko'rinadigan dubl, jimgina o'chirishdan yaxshiroq.

### Nega simhash emas, Jaccard (o'lchangan)

Simhash uzun hujjatlar va LSH banding kerak bo'ladigan katta korpus uchun foydali.
Bu yerda sarlavhalar — bir necha token, va bir run ~130 yangi itemni bir necha yuz
eski item bilan solishtiradi. Bu miqyosda to'g'ridan-to'g'ri to'plam kesishmasi
qisqa satrlarda **aniqroq** va xarajati nol.

99 ta jonli item ustida o'lchov:

```
1.00  "Introducing GPT-Live" / "Introducing GPT‑Live"        ROST (U+2011 defis)
0.67  "xai-org/grok-build, now open source"
      "Grok Build is open source"                             ROST
0.50  "sqlite-utils 4.1.1" / "sqlite-utils 4.0"               YOLG'ON (har xil reliz)
0.50  "How sales teams use ChatGPT Work"
      "How data science teams use ChatGPT Work"               YOLG'ON (har xil maqola)
```

Rost va yolg'on orasida atigi **0.17** masofa. O'rtadagi chegara boshqa kun boshqa
taqsimotda tanga tashlashga aylanadi. Shuning uchun chegara **0.85** — faqat deyarli
aniq bo'lganini qo'shadi, qolganini o'tkazib yuboradi.

Asimmetriya hal qildi: **yolg'on qo'shish yangilikni jimgina o'chiradi** (o'quvchi
u chiqqanini ham bilmaydi), yolg'on ajratish esa shunchaki bir narsani ikki marta
ko'rsatadi. `grok-build` kabi ma'noviy juftlar embedding talab qiladi — bir kunlik
yangilikka moslangan chegara emas.

*Tokenizer tuzog'i:* versiya raqamini butun saqlash kerak. `4.1.1` ni raqamlarga
bo'lsang, stop-word filtridan keyin `4.0` bilan aynan bir xil bo'lib qoladi va
uchta har xil reliz bitta bo'lib ketadi.

*Oyna tuzog'i:* dedupe oynasi ingest saqlaydigan hamma narsani qoplashi shart.
48 soatga qo'ysang, eski itemlar `cluster_id=NULL` bo'lib qoladi va **haftalik
obunachi hech solishtirilmagan dubllarni oladi.**

Cluster ichidan canonical tanla: `manba_ishonchi × yangilik`. Xabarda "+4 boshqa manba" ko'rsat.

---

## 5. Manbalar

Hammasi `curl` bilan tekshirilgan (2026-07-16):

| Manba | Usul | Holat |
|---|---|---|
| **OpenAI News** `openai.com/news/rss.xml` | RSS | ✅ 1036 item — **RSS bor**, scrape kerak emas |
| Simon Willison | RSS | ✅ 30 item, eng zich manba |
| Ars Technica AI | RSS | ✅ 20 item |
| Hacker News `hnrss.org/frontpage?points=100` | RSS | ✅ 14 item |
| TechCrunch AI | RSS | ✅ 20 item |
| HuggingFace blog | RSS | ✅ 829 item — P1 da qo'shiladi |
| The Verge AI | RSS | ✅ 10 item — P1 |
| **Claude Platform release notes** | **markdown** | ✅ `.md` qo'shsang xom markdown beradi — scrape kerak emas |
| **Claude Code releases** | GitHub Atom | ✅ mavjud `RssSource` hazm qiladi |
| ~~Anthropic news HTML~~ | scrape | ⏸ qoldirildi — sabab quyida |
| ~~Google DeepMind~~ `deepmind.google/blog/rss.xml` | — | ❌ **o'lik**: 240 bayt, `<channel>` bor, item yo'q |
| Reddit `r/LocalLLaMA`, `r/ClaudeAI` | RSS | P1 |
| arXiv `cs.AI`, `cs.CL` | rasmiy API | P2 |
| GitHub Releases | Atom feed | P2 |

Tuzatishlar:
- **OpenAI da RSS bor** — ilgari "scrape kerak" degandim, noto'g'ri edi. Bitta scraper tejaldi,
  ustiga u *birlamchi* manba (trust_tier=1).
- **DeepMind feed o'lik** — aynan rejadagi "jimgina 0 item qaytaradi" xavfining tirik misoli.
  Ro'yxatdan chiqarildi.
- **Anthropic uchun HTML scrape shart emas edi.** Claude docs har qanday sahifani `.md`
  qo'shsang xom markdown qilib beradi. `### July 10, 2026` sarlavhalari ostida toza
  bulletlar — aynan model va limit o'zgarishlari. HTML dan tubdan barqarorroq.

### Nega `anthropic.com/news` HTML scraper i qoldirildi

Uchta to'siq:
1. **Sitemap yo'q** — `sitemap.xml` 200 qaytaradi, lekin ichida `<html id="__next_error__">`.
   Bu soxta 404: status kodga qarab yozilgan tekshiruv buni "ishlayapti" deb o'qiydi.
2. **CSS klasslari hash langan** — `FeaturedGrid-module-scss-module__W1FydW__sideLink`.
   `W1FydW` har build da o'zgaradi. Shu selektorga bog'langan scraper Anthropic har
   deploy qilganda **jimgina** o'ladi.
3. **Next.js App Router** — `__NEXT_DATA__` JSON yo'q, faqat `self.__next_f` RSC payload.
   Parse qilish mumkin, lekin mo'rt.

Release notes asosiy ehtiyojni (model, limit, API) qoplaydi. Qolgani — e'lonlar va
kompaniya yangiliklari — TechCrunch/HN orqali baribir yetib keladi. Nisbat to'g'ri
kelmadi: mo'rt scraper ni har hafta tuzatishdan ko'ra, mustahkam manbadan boshlash.

Har bir manba `Source` protokolini bajarsin: `fetch() -> list[RawItem]`. Yangi manba qo'shish
= bitta fayl, boshqa joyga tegmaydi.

---

## 6. Taxonomy (qat'iy teglar)

```
model-release      yangi model, versiya yangilanishi
pricing-limits     narx, rate limit, kvota o'zgarishi
api-features       yangi API param, endpoint, SDK
agents-tools       MCP, agent, tool use, computer use
research           maqola, benchmark
opensource         ochiq vazn, local model
funding-business   investitsiya, sotib olish
safety-policy      xavfsizlik, regulyatsiya
infra-hardware     chip, datacenter, serving
product-launch     consumer app, product
```

10 ta teg MVP uchun yetarli. User o'ziga keraklisini tanlaydi.

---

## 7. DB sxemasi (asosiy jadvallar)

```sql
sources(id, name, kind, url, enabled, trust_tier,
        last_fetched_at, etag, last_modified)
  -- kind: rss | hn | arxiv | github_releases | scrape

items(id, source_id, url, canonical_url, url_hash UNIQUE,
      title, author, published_at, raw_text,
      simhash BIGINT, cluster_id, fetched_at)

item_enrichment(item_id PK, tags TEXT[], entities TEXT[],
                importance SMALLINT,      -- 0..10
                summary TEXT,
                embedding VECTOR(768),
                model_used, enriched_at)

clusters(id, canonical_item_id, member_count, top_importance)

users(id, telegram_id UNIQUE, username, lang, timezone,
      digest_mode,               -- instant | daily | weekly | off
      digest_hour, min_importance SMALLINT DEFAULT 5,
      created_at, is_active)

user_topics(user_id, tag)          -- taxonomy dan
user_keywords(user_id, keyword)    -- erkin matn: "MCP", "Anthropic"

-- IDEMPOTENCY GUARD — eng muhim jadval
deliveries(user_id, cluster_id, sent_at, message_id,
           PRIMARY KEY(user_id, cluster_id))

feedback(user_id, cluster_id, vote SMALLINT, created_at)  -- +1 / -1
```

`deliveries` dagi `PRIMARY KEY(user_id, cluster_id)` — ikki marta yuborishga qarshi
yagona ishonchli himoya. Kod xato qilsa ham DB to'xtatadi. Buni birinchi kundan qo'y.

---

## 8. Shaxsiylashtirish (bosqichma-bosqich)

- **P1 — deterministik:** `tags ∩ user_topics`, `importance >= user.min_importance`,
  keyword OR-match. Debug qilish oson, natija tushunarli.
- **P2 — embedding:** user erkin matnda qiziqishini yozadi ("Claude limitlari va MCP
  asboblari qiziq") → embed → item embedding bilan cosine.
  Aralash ball: `0.6 * tag_match + 0.4 * cosine`.
- **P3 — feedback loop:** 👍/👎 tugmalari → user embedding ni yoqqaniga yaqinlashtir,
  yoqmaganidan uzoqlashtir + teg og'irliklarini sozla.

---

## 9. Yetkazish (delivery)

- **instant** — faqat `importance >= 8`. Kam, lekin qimmatli (model chiqishi, limit o'zgarishi).
- **daily** — user `timezone` idagi `digest_hour` da.
- **weekly** — dushanba yig'masi.

Telegram limit: global 30 msg/sek. 50 user uchun muammo yo'q, lekin baribir semaphore
bilan yubor — keyin o'sganda qayta yozmaysan.

---

## 10. Fazalar

### P0 — Skelet (2-3 kun)
- Python loyiha (`uv`), SQLite (Postgres ga keyin `SQLAlchemy` bilan og'riqsiz ko'chadi)
- 5 ta RSS manba hardcoded
- `fetch → dedupe(url hash) → Gemini batch classify → console print`
- O'zingga bitta Telegram xabar

**Maqsad:** pipeline boshidan oxirigacha ishlaydi. Sifat hali muhim emas.

### P1 — Multi-user MVP ✅ tugadi
- ✅ aiogram bot: `/start`, `/topics`, `/freq`, `/preview`, `/pause`, `/stop`
- ✅ `users`, `user_topics`, `deliveries` jadvallari
- ✅ APScheduler: har 20 daqiqada pipeline + yetkazish (`max_instances=1`, `coalesce`)
- ✅ Leksik dedupe (Jaccard, simhash emas — yuqoriga qara)
- ✅ Per-user importance threshold + mavzu filtri + timezone bo'yicha vaqt
- ✅ Anthropic manbasi (release notes markdown) + Claude Code releases
- ✅ **Alembic** — baseline migratsiya, `init_db` startda `upgrade head` qiladi.
  Drift sinovdan o'tkazildi: sun'iy ustun qo'shilganda `alembic check` uni tutdi.
- ✅ **Docker + compose** — sirlar obrazda yo'q, volume da ma'lumot saqlanadi
  (ikki konteyner bilan tekshirilgan)
- ❌ **Postgres — rad etildi, hozircha.** Sabab quyida.

**Holat:** uchdan-uchgacha tekshirilgan. @get_news_for_me_bot da haqiqiy foydalanuvchi
ro'yxatdan o'tdi, `/topics` bilan 5 ta mavzu tanladi, klaviatura yetib bordi.

### Prefilter — rejadan olib tashlandi

Reja uni "300 → 120 item, LLM chaqiruvning 60% i tejaladi" deb asoslagan edi.
O'lchov boshqa raqam berdi: 8 ta manba 14 kun uchun jami 131 item beradi, ya'ni
**kuniga ~10-30 ta**. 20 tadan batch qilinsa — kuniga 1-2 chaqiruv, kvota 1500.

Ya'ni hozir kvotaning ~0.1% i ishlatiladi. 60% ni tejash — nolning 60% i.
Prefilter yechadigan muammo mavjud emas. Manba soni 10 barobar oshsa qaytamiz.

### P2 — Sifat
- ✅ `trafilatura` bilan to'liq matn — quyida, eng katta topilma shu yerda
- ✅ Manba ishonch darajasi ishlatildi (canonical tanlash, render paytida)
- ⏳ Embedding dedupe + cluster
- ⏳ Mini App: teg tanlash UI, digest tarixi
- ⏳ 👍/👎 feedback tugmalari

### To'liq matn — dastur asosiy vazifasida jimgina yiqilayotgan ekan

O'lchov: 169 ta itemning 86 tasi 400 belgidan kam matn bilan kelgan. Hugging Face
feed ida esa matn maydoni **umuman yo'q** — faqat sarlavha va link.

`trafilatura` qo'shilgach o'rtacha matn:

| Manba | oldin | keyin |
|---|---|---|
| Hugging Face | **0** | 11766 |
| Hacker News | 186 | 7012 |
| OpenAI News | 144 | 5530 |
| TechCrunch | 162 | 2929 |
| Ars Technica | 1008 | 1606 |
| Claude release notes | 429 | **429** (himoyalangan) |

Kalta itemlar: 86/169 → **19/171**.

**Asosiy topilma.** Eski baholarni saqlab, to'liq matn bilan qayta baholadim.
144 tadan 54 tasining bahosi o'zgardi. Ular orasida:

```
GPT-5.6: Frontier intelligence that scales with your ambition   (openai.com/index/gpt-5-6)
  kalta matn (144 belgi):   2/10  "Marketing overview of the GPT-5.6 model family."
  to'liq matn (20000):     10/10  "OpenAI announced general availability of the
                                   GPT-5.6 model family, introducing an 'ultra'
                                   setting for parallel agent coordination."
```

`min_importance=5` da: **yuborilmasdi → yuboriladi.**

OpenAI ning flagship model e'loni — bu dastur mavjud bo'lish sababining o'zi —
jimgina tashlanardi. Hech qanday xato, hech qanday log. Faqat sukut.

**Rubric aybdor emas edi.** Ilgari "taxmin bandi zaif" deb tashxis qo'ygandim
(«Kimi 3 *expected to*» 6 ball olgani uchun). Noto'g'ri edi. Faqat marketing
lead ini ko'rgan model uchun "2 = marketing" — *to'g'ri* javob. Model ishlagan,
biz uni ochlikda qoldirgan ekanmiz. Promptni tuzatish muammoni yashirardi.

Boshqa yo'nalishda ham to'g'irlandi: `v2.1.204` 6 → 2, `llm-meta-ai 0.1` 6 → 2.
Kontekstsiz baho shunchaki shovqin bo'lar ekan — ikkala tomonga.

19 tasi hali kalta: ba'zi saytlar botni rad etadi (techdirt 403). Ular feed
lead ida qoladi — bu pol, yiqilish emas.

### P3 — Chuqurlik (~1 hafta)
- Active research agent (Gemini + `google_search` grounding), kunlik top-3
- Embedding shaxsiylashtirish
- Admin panel: manba qo'shish/o'chirish, LLM chiqishini ko'rish, user statistika, manual re-run
- O'zbekcha summary (Gemini yaxshi uddalaydi)

---

## 11. Fayl strukturasi

```
Ogoh/
  pyproject.toml
  docker-compose.yml
  .env.example
  alembic/
  src/ogoh/
    config.py
    taxonomy.py
    scheduler.py            # APScheduler joblar
    db/
      models.py
      session.py
    sources/
      base.py               # Source protocol: fetch() -> list[RawItem]
      rss.py
      hackernews.py
      arxiv.py
      github_releases.py
      scrape/
        anthropic.py
        openai.py
      registry.py
    pipeline/
      ingest.py
      normalize.py          # url canonicalize + trafilatura extract
      dedupe.py             # simhash + embedding cluster
      enrich.py             # LLM batch classify + summarize
      match.py              # user ↔ item
      digest.py             # xabar yig'ish
    llm/
      base.py               # LLMProvider protocol
      gemini.py
      groq.py               # fallback
      prompts.py
    bot/
      main.py               # aiogram
      handlers/
      keyboards.py
    api/
      main.py               # FastAPI: Mini App + admin
      routes/
  web/                      # Vite + React — /app (Mini App), /admin (panel)
```

---

## 12. Xarajat hisobi

Kuniga ~300 ta yangilik yig'iladi, prefilter dan keyin ~120 tasi LLM ga boradi.

| Ish | Chaqiruv/kun |
|---|---|
| Classify + summarize (20 ta/batch) | ~6 |
| Embedding (100 ta/batch) | ~2 |
| Active research (top-3) | ~10 |
| **Jami** | **~20** |

Gemini free limit: **1500/kun**. Ishlatish: **~1%**.

10-50 user uchun key rotatsiyasi kerak emas. Pul xarajati: faqat VPS ~€4/oy.

---

## 13. Xavflar (e'tibordan qochadiganlari)

1. **Anthropic da RSS yo'q → scrape.** Ular sahifa HTML ini o'zgartirsa scraper buziladi
   va **jimgina** 0 item qaytaradi. Bu eng yomon holat — xato ko'rinmaydi, shunchaki yangilik
   kelmay qo'yadi. Yechim: har manbaga "0 item topildi" alerti qo'y.
   *(P0 da `ingest_all` da amalga oshirilgan.)*

2. **Arxiv feed lar.** ✅ *P0 da topildi va tuzatildi.* OpenAI feed i butun arxivini beradi —
   2015 yildan boshlab 1036 ta item. Ikkita zarar: (a) birinchi ishga tushirish 10 yillik
   tarixni enrich qiladi; (b) jiddiyrog'i — digest `fetched_at` bo'yicha filtrlagani uchun
   arxivdagi hamma narsa "yangi" ko'rinadi va **2015 yilgi GPT e'loni importance=10 olib
   birinchi digestni boshqaradi.**
   Yechim: `max_age_days=14` ingest da + digest oynasi `coalesce(published_at, fetched_at)`
   bo'yicha, `fetched_at` bo'yicha emas. Natija: 1122 → 103 item.
3. **Dedupe ishlamasa** — user bir yangilikni 10 marta oladi, bir kunda chiqib ketadi.
   Shuning uchun dedupe P1 da, P2 da emas.
4. **LLM importance drift** — bir kuni hamma narsa 8, ertasi hammasi 4. Yechim: promptda
   aniq rubric ber, bahoni *absolyut* qil, "bugungilar orasida" emas.
   *(P0 da `llm/prompts.py` da amalga oshirilgan.)*
5. **LLM batch dan kam verdict qaytaradi.** 20 ta item yuborib 19 ta javob olsang va
   pozitsiya bo'yicha moslashtirsang — xulosalar siljiydi va **noto'g'ri maqolaga noto'g'ri
   summary yopishadi.** Yechim: index bo'yicha moslashtir, yetishmaganini tashla.
   *(P0 da `pipeline/enrich.py` da amalga oshirilgan.)*
6. **Ikki instance ko'tarilsa** ingest ikki marta ketadi. `deliveries` PK yuborishni himoya
   qiladi, lekin ingest uchun ham Postgres advisory lock qo'y.
7. **Free tier shartlari o'zgaradi.** `LLMProvider` abstraksiyasi shuning uchun kerak.
8. **Telegram bot token** — `.env`, `.gitignore`, hech qachon logga yozma.

---

## 14. Ochiq savollar (keyin hal qilinadi)

- Summary tili: o'zbekcha, inglizcha, yoki user tanlaydi? (`users.lang` ustuni bor, lekin
  P3 gacha ishlatilmaydi)
- Retention: `raw_text` ni necha kundan keyin o'chirish? (taklif: 90 kun, metadata qoladi)
- Manba qo'shishni userlarga ochish kerakmi, yoki faqat admin?

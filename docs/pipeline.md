# Pipeline details

Reference for the enrichment, menu extraction and maintenance workflows. The
[README](../README.md) covers the essentials.

## Workflows

| Workflow | Purpose |
| --- | --- |
| `scrape.yml` | Full weekly run: list, enrich, menus, publish, commit. |
| `update-new.yml` | Only places added since a date (or a given list of names). |
| `update-one.yml` | One place, website only. |
| `update-menu-one.yml` | One place, menu only (photos/vision). |
| `update-fudo-one.yml` | One place, Fudo store (`menu.fu.do`). |
| `update-menus-batch.yml` | Menus for a batch of places. |
| `rebuild-doc.yml` | Regenerate the Doc from the JSONL without re-listing. |
| `recover-menus.yml` | Recover menus from previous successful runs. |

## Environment variables

| Variable | Default | What it does |
| --- | --- | --- |
| `MAPS_LIST_URL` | URL in the workflow | Public Google Maps list to read. |
| `MAPS_ENRICH` | `1` | Enrich with website and reviews. |
| `MAPS_ENRICH_DAYS` | `30` | Enrichment cache lifetime. |
| `MAPS_HEADLESS` | `1` | `0` opens a window (needed for reviews). |
| `MAPS_OCR` | `1` in CI | OCR for scanned PDFs and menu images. |
| `MAPS_WEBSITE_SEARCH` | `1` | Search the web when Maps has no website. |
| `MAPS_WEBSITE_MENU` | `0` | Scan menu pages on websites. |
| `MAPS_MENU_ACTOR` | `unitbytes` | `unitbytes`, `nomad` or `none`. |
| `MAPS_VISION` | `1` | Gemini vision fallback for hard menus. |
| `MAPS_VISION_PLACES` | `12` | Places per run for vision. |
| `MAPS_VISION_PHOTOS` | `3` | Photos per place for vision. |
| `MAPS_VISION_CONCURRENCY` | `2` | Parallel vision calls. |
| `SERPAPI_KEY` | — | Google search (250 free searches/month). |
| `BRAVE_API_KEY` | — | Fallback search when SerpAPI fails. |
| `GEMINI_API_KEY` | — | Validation and vision. |
| `APIFY_TOKEN` | — | Structured menus from Google Maps photos. |
| `GDOC_ID` | — | Google Doc to publish to. |
| `GOOGLE_SA_JSON` | — | Service account JSON (CI). |
| `UBER_EATS_API_URL` | — | Proxy that exposes Uber Eats menus. |

## Website and review enrichment

The Google list does not say what each place sells. For every place the script
opens the Maps card, takes its website and looks for dishes in the site text
(and in a menu page or PDF if there is one). It also reads the **topics Google
extracts from reviews** (for example "empanadas 19", "dulces 17", "hamburguesas
12") and the review text, then adds to the Doc:

```text
- **Web:** https://www.quimeysushi.cl/
- **Menciona en su web:** hamburguesa, pizza, sushi, pasta, gyosa
- **Menciona en reseñas:** hamburguesa, empanada, completo, chilenito, dulces, jugo
```

The lexicon includes dishes, sweets and products: hamburguesa, pizza, sushi,
pasta, empanada, completo, torta, pastel, galleta, alfajor, brownie, cupcake,
donut, cheesecake, helado, chocolate, churro, flan, budín, chilenito, medialuna,
factura, croissant, postre, jugo, and more.

It is a **mention**, not a guarantee: it can come from a review or a site
section, and it does not cover menus that only exist as images. In this list, 67
of 100 places have a website and 37 showed dishes from the website.

- Reviews and topics only load in the card with a **window**, which is why the
  workflow uses `xvfb` and `MAPS_HEADLESS=0`. Locally, run with `--no-headless`.
- Cache: 30 days (`MAPS_ENRICH_DAYS`) plus an internal version that forces a
  re-extraction when the enrichment changes.
- The first run takes ~15–25 minutes; later runs do not repeat cards.
- Disable: `MAPS_ENRICH=0` or `--no-enrich`.
- Force: `--refresh-enrichment`.

## Website search (SerpAPI + Brave + Gemini)

If the Maps card has no website (`_extract_website` / `discover_links` empty),
the pipeline looks for it on its own:

- Query `"<name>" sin gluten <comuna/address>` to **SerpAPI** (Google,
  `SERPAPI_KEY`, 250 free searches/month); if the key is missing or it fails
  (403/429/error), it falls back to **Brave Search API** (`BRAVE_API_KEY`, free
  plan, JSON, no anti-bot blocking). Standard library `urllib` only, no extra
  browser. Top 5, discarding social/aggregator sites (Instagram, Facebook,
  TikTok, Tripadvisor, Uber Eats, Rappi, PedidosYa).
- Gemini (`GEMINI_API_KEY`, the same vision secret; without a key nothing is
  accepted) validates name + address overlap. It only accepts a strong match:
  `score >= 0.85` and a URL that is among the candidates (a URL invented by the
  LLM or a namesake is always rejected).
- If accepted, the website is treated like the Maps one (`_site_dishes`,
  Fudo/Shopify/etc. adapters, photos as fallback) and the origin is recorded:
  `website_source='search'` in SQLite and `metadata.website_source` in the JSONL
  (`'maps'` when it comes from Maps).
- Applies to `run` enrichment and to the `update_new_places` fallback after
  `discover_links`. If both search engines block/run out of quota or there is no
  strong match, it degrades silently and the place stays as it is
  (`needs_manual`): a wrong website is worse than none, the URL is never
  invented. In GitHub Actions both search engines get their key from secrets
  (`SERPAPI_KEY`, `BRAVE_API_KEY`).
- Control: `MAPS_WEBSITE_SEARCH=1` by default; `MAPS_WEBSITE_SEARCH=0` or
  `python -m maps_gluten run --no-website-search` turns it off;
  `--website-search` forces it even if the env is 0 (the flag wins). Soft rate
  limit (1.1 s between searches; Brave free allows 1 qps). The validation model
  can be changed with `GEMINI_SEARCH_MODEL` (default
  `gemini-flash-lite-latest`).

## OCR of scanned menus

With `MAPS_OCR=1` (on in the workflow):

- **PDFs** are read first with `pypdf`. If they have no text (scanned), they are
  rendered with `pypdfium2` and passed through Tesseract (`spa+eng`).
- On websites, if the menu page has too little text, up to 3 candidate images
  are downloaded (no logos or icons) and OCR'd.
- GitHub Actions installs `tesseract-ocr` and `tesseract-ocr-spa`. Locally:
  `brew install tesseract tesseract-lang` or the equivalent package.

Limits: quality depends on the photo; menus with very small, tilted or
multi-column text, or a complex background, can fail. High-resolution OCR does
work on photos tagged `menu` by UnitBytes, but it can still insert fragments or
lose prices.

## Menus from Google Maps photos (UnitBytes + OCR)

Status 2026-11-05: UnitBytes + high-resolution OCR extracted **3,121 dishes from
54 places**. Added to the **916 dishes from 14 places** recovered from the Nomad
datasets, the Doc has **4,037 dishes in 62 places**. The other 38 have no menu
photos and keep reviews/website only.

How it works:

- The `unitbytes/google-maps-photos-scraper` actor with `category: menu` returns
  the photos from the Menu tab (up to 8 per place).
- They are downloaded at **high resolution**, converted to grayscale,
  upscaled/downscaled to ~1,800–2,600 px, auto-contrasted and OCR'd with
  Tesseract `spa+eng` and `psm 6/11`.
- Dishes and prices are parsed; the result goes to the Doc as
  `- **Carta (Google Maps):** ...`, to `metadata.menu` and to `menus.jsonl`.
- Cost: ~$0.00025 per photo; 263 photos ≈ **$0.07**, inside Apify's free $5.
- Cache 30 days (`menu_at`). `MAPS_MENU_ACTOR=unitbytes` and
  `MAPS_WEBSITE_MENU=0`.
- Photo URLs are stored in SQLite (`menu_photos_json`) and the last successful
  UnitBytes runs are reused, so updating the same place again does not scrape it
  again.

### Vision fallback (Gemini)

If OCR for a place returns fewer than 2 dishes, the photo is sent to Gemini
(vision) and whatever it reads is added. It is automatic and covers handwritten
or hard-to-read menus, like the Yoko Sea Food blackboard.

- Uses `GEMINI_API_KEY` (free in Google AI Studio) and `MAPS_VISION=1`.
- Model order: `gemini-flash-lite-latest` (cheapest) → `gemini-3.5-flash` →
  `gemini-3.6-flash`. If a model returns **503** (saturated) it moves to the
  next; if it returns **429** (quota) it stops.
- Limit: `MAPS_VISION_PLACES` (12 per run) and `MAPS_VISION_PHOTOS` (3 photos
  per place).
- A model can be pinned with `GEMINI_VISION_MODEL=gemini-3.6-flash`.
- If vision finds 2+ dishes, OCR fragments without a price are discarded.

Enable it with the `APIFY_TOKEN` secret:

1. Create a free account at https://console.apify.com/sign-up (no card; includes
   **$5 of usage per month**).
2. Copy your API token from *Settings → Integrations*.
3. In GitHub → *Settings → Secrets and variables → Actions*, create the
   `APIFY_TOKEN` secret with that value.
4. Trigger the workflow. The first run processes every place; afterwards it
   refreshes when `menu_at` is older than `MAPS_ENRICH_DAYS` days (30).

Outputs:

- `### Carta` in the `.md` and in the Doc, with `#### Categoría` and one dish per
  line (`- Plato — $precio`).
- `metadata.menu` in the main JSONL.
- `data/mis_lugares_sin_gluten_menus.jsonl`: one row per dish, with category and
  price.

OCR can insert fragments and prices can be missing; it is a mention, not a
certified menu. Verify allergens and prices with the place.

`MAPS_MENU_ACTOR` accepts `unitbytes` (default), `none` (disabled) or `nomad`
(managed/BYO actor). `MAPS_WEBSITE_MENU=1` keeps the website menu scan; it is
`0` because UnitBytes already covers Maps photos.

## Updating a single menu

To re-read the menu photos of one place (without touching the rest):

```bash
gh workflow run update-menu-one.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag \
  -f place=Yoko
```

- Uses the SQLite photo cache; if it does not exist, it reuses the last UnitBytes
  run or scrapes only that place.
- By default it uses **Gemini vision** (flash-lite, the cheapest model) and
  **skips Tesseract**, so it installs no system packages.
- `-f ocr=true` enables Tesseract as a fallback (slower).
- `-f refresh=true` ignores the photo cache and scrapes again.
- Publishes the Doc and commits `data/`.

Locally:

```bash
APIFY_TOKEN='...' GEMINI_API_KEY='...' \
GDOC_ID='<doc-id>' \
GOOGLE_APPLICATION_CREDENTIALS='/path/service-account.json' \
.venv/bin/python scripts/update_menu_place.py --place Yoko --publish
```

## Fudo stores (menu.fu.do)

If Google Maps shows `menu.fu.do` in the Menu tab, save the URL in
`data/menu_urls.json`:

```json
{
  "Café Aquelarre": "https://menu.fu.do/cafeaquelarre"
}
```

And update only that menu:

```bash
gh workflow run update-fudo-one.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag \
  -f place='Café Aquelarre'
```

It also accepts `-f menu_url='https://menu.fu.do/...'` if it is not in the file.
The extractor reads the full catalog (products, categories and prices) even if
the store is closed; "closed" only blocks orders.

## Uber Eats adapter (proxy/scraper required)

The Uber Eats adapter does not scrape Uber Eats directly: it calls a local proxy
that exposes `GET /stores/menu?store=<id>` and returns JSON
`{sections:[{categories:[{title,items:[{name,price,description,link}]}]}]}`. It
requires the **`UBER_EATS_API_URL`** variable:

- **Local**: `UBER_EATS_API_URL=http://localhost:8000 python
  scripts/update_new_places.py --places 'El Patio Cafe' --refresh --no-photos`
- **GitHub Actions**: the `UBER_EATS_API_URL` secret is passed by
  `update-new.yml` (the public proxy URL is missing — for now in CI the adapter
  returns an explicit error `UBER_EATS_API_URL no configurado (requiere el
  proxy/scraper de Uber Eats)` and the place stays `needs_manual`).
- For CI you would have to expose the proxy (e.g. a self-hosted runner or a
  temporary public URL) and create the `UBER_EATS_API_URL` secret with that
  value; meanwhile, in Actions the menu for Uber Eats places comes from photos
  (`photos=true`).

## Normalization and tags (P0)

Before publishing, the pipeline separates what is publishable from what is
doubtful:

- `scripts/normalize_menus.py`: cleans names, splits descriptions, normalizes
  prices (CLP/EUR), dedupes, assigns categories and diet tags.
- `scripts/apply_normalization.py`: applies the result to the JSONL, the
  `_menus.jsonl` and SQLite.
- `scripts/rebuild_markdown.py`: regenerates the Doc with `### Qué vende` +
  `### Carta`.
- `menus_review.jsonl` and `menus_rejected.jsonl`: items that are not published
  and are kept for re-extraction.

```bash
python scripts/normalize_menus.py \
  --places data/mis_lugares_sin_gluten.jsonl \
  --menus data/mis_lugares_sin_gluten_menus.jsonl \
  --out-dir data/normalized

python scripts/apply_normalization.py \
  --places data/mis_lugares_sin_gluten.jsonl \
  --normalized-dir data/normalized \
  --out-dir data \
  --db data/historial_lugares.db

python scripts/rebuild_markdown.py --publish
```

Gemini vision runs with concurrency limited by `MAPS_VISION_CONCURRENCY`
(default `2`) and loading recent datasets uses up to 4 threads. Adjust that
value if your quota can take more.

To rebuild the Doc from the JSONL without re-listing the 100:

```bash
gh workflow run rebuild-doc.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag
```

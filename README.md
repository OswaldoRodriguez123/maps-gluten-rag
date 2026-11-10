# maps-gluten-rag

[![scrape](https://github.com/OswaldoRodriguez123/maps-gluten-rag/actions/workflows/scrape.yml/badge.svg)](https://github.com/OswaldoRodriguez123/maps-gluten-rag/actions/workflows/scrape.yml)

Turns a shared Google Maps list of gluten-free places into two files ready for a
knowledge base (RAG):

- `data/mis_lugares_sin_gluten.md` — one `##` block per place, ideal for
  NotebookLM or any semantic index.
- `data/mis_lugares_sin_gluten.jsonl` — one JSON line per place, with `text` and
  `metadata`, ideal for embeddings.
- `data/mis_lugares_sin_gluten_menus.jsonl` — one line per dish (name, price,
  category, ingredients, allergens, nutrition) when Apify is configured.

```markdown
## Alma Chilanga
- **Ubicación:** Av. Las Condes 9111, 7591238 Las Condes, Región Metropolitana
- **Categoría:** Restaurante mexicano
- **Valoración:** 4.5 / 5
- **Enlace:** https://www.google.com/maps?cid=308593624422457697
- **Web:** http://www.almachilanga.cl/
- **Menciona en su web:** tacos
- **Menciona en reseñas:** sushi, tacos, tortilla

### Carta
- Tacos de Cochinita (3)
- Tacos de Pastor (3)
- Flan de la Abuela
```

The local source of truth is `data/historial_lugares.db` (SQLite). In GitHub
Actions that file lives in the workflow cache, not in the repo. Every run
upserts: it keeps Google's `saved_on` date and only marks as new the places that
did not exist before.

The extractor opens the public list with Playwright and reads the internal
`entitylist/getlist` endpoint, which returns every place with name, address,
coordinates, `ftid` and save date. It then walks the DOM rows to add the rating
and category, which that endpoint does not include. If the endpoint changes, it
falls back to reading the rows directly.

## Two ways to run it

| | GitHub Actions | Local |
| --- | --- | --- |
| Install | nothing on your Mac | Python + Playwright |
| Depends on your machine | no | Mac turned on |
| Cost | free (public repo) | free |
| Data lives in | repo + Drive/raw URL | your disk |

The rest of this document assumes GitHub Actions.

## GitHub Actions

1. Create the repository and push the project (the workflow runs at 03:00
   Bogotá time).
2. In *Settings → Actions → General*, keep *Read and write permissions*
   enabled if your organization restricts it.
3. Optional: in *Settings → Secrets and variables → Actions → Variables*, create
   `MAPS_LIST_URL` with your link. If you skip it, the URL in the workflow is
   used.
4. Trigger the first run from *Actions → Actualizar lista de Google Maps → Run
   workflow*.

What the workflow (`.github/workflows/scrape.yml`) does:

- installs Python 3.12, the dependencies and Chromium;
- runs `python -m maps_gluten run`;
- enriches with each place's website and review topics (if `MAPS_ENRICH=1`);
- queries Apify for the structured menu if `APIFY_TOKEN` is set;
- commits `data/*.md` and `data/*.jsonl` if anything changed;
- caches `data/historial_lugares.db` in Actions to keep dedup between runs (the
  file is git-ignored);
- copies the result to a Google Doc if `GDOC_ID` is set;
- publishes the `.md`, `.jsonl` and `_menus.jsonl` as a downloadable artifact;
- runs every Monday at **13:00 Chile time**. It schedules two crons (16:00 and
  17:00 UTC) and a step checks the local hour, so it stays at 1 pm across
  daylight saving changes;
- uses `America/Santiago` and `es-CL` for dates and text.

GitHub's cron can be a few minutes late under load. It does not need your Mac
on. If you add places before Monday, trigger the workflow by hand from
*Actions → Run workflow*.

### Google Doc for NotebookLM (recommended)

The workflow copies the result into a Google Doc of yours. NotebookLM accepts
that Doc as a source and has a sync button, so you do not depend on a raw URL.

Set it up once:

1. Create an empty Google Doc and copy its ID from the URL
   (`https://docs.google.com/document/d/<ID>/edit`).
2. In Google Cloud create a project and enable the **Google Docs API**.
3. Create a **service account** (IAM → Service accounts), no roles. Generate a
   JSON key and download it.
4. Share the Doc with the service account email
   (`...@....iam.gserviceaccount.com`) as **Editor**.
5. In GitHub → *Settings → Secrets and variables → Actions*:
   - secret `GOOGLE_SA_JSON`: the full JSON contents.
   - variable `GDOC_ID`: the Doc ID.
6. Run the workflow. The *Publicar en Google Doc* step fills the Doc.
7. In NotebookLM add the Doc from Google Drive. To get the new version, press
   **Sync** on the source.

The service account can only touch that Doc because you shared it explicitly. If
you prefer not to set this up, the repo's raw URL still works as a NotebookLM
source:

```text
https://raw.githubusercontent.com/OswaldoRodriguez123/maps-gluten-rag/main/data/mis_lugares_sin_gluten.md
```

## What it extracts

- **Website and review mentions.** The Google list does not say what each place
  sells. The script opens each place in Maps, takes its website and looks for
  dishes in the site text (and in a menu page or PDF if there is one). It also
  reads the **topics Google extracts from reviews** and the review text. It is a
  *mention*, not a guarantee: it can come from a review or a site section, and
  it does not cover menus that only exist as images.
- **Website search when Maps has none.** Query `"<name>" sin gluten
  <comuna/address>` to SerpAPI, falling back to Brave Search, and validate the
  match with Gemini (name + address overlap, `score >= 0.85`, URL must be one of
  the candidates). A wrong website is worse than none, so the URL is never
  invented; if nothing matches, the place stays `needs_manual`.
- **OCR of scanned menus.** PDFs are read with `pypdf`; scanned ones are
  rendered with `pypdfium2` and passed through Tesseract (`spa+eng`). On
  websites, up to 3 candidate images are OCR'd when the menu page has too little
  text.
- **Menus from Google Maps photos.** The `unitbytes/google-maps-photos-scraper`
  actor returns the photos from the Menu tab (up to 8 per place); they are
  downloaded at high resolution, preprocessed and OCR'd. If OCR returns fewer
  than 2 dishes, the photo goes to Gemini vision as a fallback.
- **Normalization.** `scripts/normalize_menus.py` cleans names, splits
  descriptions, normalizes prices (CLP/EUR), dedupes, assigns categories and
  diet tags. `scripts/apply_normalization.py` applies the result to the JSONL,
  `_menus.jsonl` and SQLite. `scripts/rebuild_markdown.py` regenerates the Doc.

Full details, environment variables and adapters (Fudo, Shopify, WooCommerce,
Uber Eats, JSON-LD) are in [docs/pipeline.md](docs/pipeline.md).

## Updating a single place

To test or fix one place without listing all 100 or using Apify:

```bash
gh workflow run update-one.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag \
  -f place=Crumbless
```

The workflow restores the cache, updates **only** that place, publishes the
Google Doc, saves the cache and commits. It does not touch the other 99 or the
menus already extracted. It works with normal sites and SPA stores: it first
tries plain HTTP parsing, then renders with Playwright and extracts products
from JSON-LD, price/dish anchors and product routes.

Locally:

```bash
GOOGLE_APPLICATION_CREDENTIALS='/path/service-account.json' \
GDOC_ID='<doc-id>' \
.venv/bin/python scripts/update_place.py --place Crumbless --publish
```

## Updating only new places

When you add places to the list you do not need to reprocess all 100.
`update-new.yml`:

1. saves a baseline of the places that already existed;
2. refreshes the list without enriching everything;
3. selects only the new ones (or those with `first_observed_at` since the given
   date);
4. tries platform adapters: Fudo, Apparta/Tu Mesa, Rappi, WooCommerce, Shopify,
   JSON-LD, rendered web and photos;
5. normalizes, publishes and leaves a report.

Before refreshing the list, the workflow syncs SQLite from the repo JSONL, so a
stale Actions cache cannot delete menus already published.

```bash
gh workflow run update-new.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag \
  -f since=2026-11-05 \
  -f places='' \
  -f photos=true
```

Inputs: `since` (ISO date, defaults to 7 days ago), `places` (comma-separated
names), `dry_run`, `photos` (use Google Maps photos as a last resort) and
`refresh` (reprocess places that already have a menu).

The result lands in `reports/new_places_<date>.jsonl`. Places that could not be
resolved appear as `needs_manual`; those are the only ones worth reviewing by
hand.

## Output format

- Each place is a `##`.
- `### Qué vende`: the place's categories (Sandwiches, Empanadas, Pizzas...),
  even without prices.
- `- **Dietético:**`: whether the place is 100% gluten-free, or how many dishes
  are gluten-free/vegan/lactose-free.
- `### Carta`: dishes with prices, grouped by `#### Categoría`, with
  `[sin gluten]`, `[vegano]`, `[sin lactosa]` tags when they apply.

NotebookLM allows 500,000 words per source and 50 sources per notebook; the full
Doc uses about 35,000 words.

## Local (optional)

```bash
cd ~/repos/maps-gluten-rag
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
cp .env.example .env        # set MAPS_LIST_URL
./run_daily.sh
```

To schedule it at 03:00 on macOS:

```bash
./scripts/install_launchd.sh
```

On Linux: `0 3 * * * cd /path/maps-gluten-rag && ./run_daily.sh >> logs/cron.log 2>&1`.

Useful options:

```bash
--url URL              # overrides MAPS_LIST_URL
--out DIR              # output folder
--basename NAME        # file name
--no-headless          # open a window (useful if Google blocks headless)
--channel chrome|msedge|""   # real browser or Playwright's
--debug                # saves HTML and network responses
```

## Private lists

The GitHub workflow can only read public lists. If your list stops being shared,
the script fails without touching the database and says so in the log. For
private lists, run locally with `python -m maps_gluten login`, which stores a
Chromium profile in `.auth/`; that profile must never be pushed to GitHub.

## Structure

```text
maps-gluten-rag/
├── .github/workflows/       # scrape, update-*, rebuild-doc, recover-menus
├── maps_gluten/
│   ├── extract.py           # list endpoint + DOM fallback
│   ├── enrich.py            # website, reviews and OCR
│   ├── apify.py             # structured menu (optional)
│   ├── store.py             # SQLite, dedup and .md / .jsonl outputs
│   └── cli.py               # `login`, `run` and `publish`
├── scripts/                 # one-off updaters, normalization, launchd
├── data/                    # final .md / .jsonl outputs
├── run_daily.sh
├── .env.example
└── requirements.txt
```

## Known limits

- `entitylist/getlist` is an internal endpoint, not a public API. It can change
  without notice; the DOM fallback and `--debug` exist for that.
- Rating and category do not come in the list payload: they are taken from the
  DOM rows. Google does not show them for some places, so those end up without a
  rating or category.
- Dishes are detected by keywords on the website, in PDFs, in menu images with
  OCR and in the place's reviews. It is not a structured menu: there can be
  false positives, and places without a website or reviews are missing.
- The Apify menu is an AI estimate: allergens and nutrition can be wrong. Check
  with the place before using them for health decisions.
- Review Google Maps' terms of use before automating it daily. For personal,
  low-volume use this is common; do not use it as a service for third parties.
- If the list is private and Google invalidates the session, `run` fails without
  touching the database and tells you in the log. Run `login` again.

## License

MIT. See [LICENSE](LICENSE).

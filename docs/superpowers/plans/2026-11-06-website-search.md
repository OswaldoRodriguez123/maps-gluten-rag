# Website Search fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recuperar la web de un local cuando Google Maps no la trae, validándola con LLM antes de aceptarla, para que el resto del pipeline funcione sin búsqueda manual.

**Architecture:** Módulo nuevo `maps_gluten/website_search.py` con solo stdlib + `GEMINI_API_KEY` (patrón `photos.py`); fallback en `enrich.py` y en `update_new_places.py` solo si `website` es `None`; procedencia `website_source='search'` persistida en `Place`/`store.py`.

**Tech Stack:** Python 3.12, `urllib.request`, `html.parser`, Playwright (ya en repo), Google Generative Language API REST vía `urllib` (ya usada en `photos.py`).

**Spec:** `docs/superpowers/specs/2026-11-06-website-search-design.md`

## Global Constraints

- Sin dependencias nuevas; solo `urllib`, `html.parser`, `json`, `time`, `unicodedata`.
- Reusar `GEMINI_API_KEY`; sin clave no se acepta ningún candidato.
- `MAPS_WEBSITE_SEARCH=1` por defecto; si falla el buscador o hay 429, degradar a `None` sin cortar el run.
- No tocar `entitylist/getlist` ni el scraper de lista; un match débil deja `needs_manual`.

## Review Focus

- **DuckDuckGo bloquea (403/429/consent):** el buscador devuelve HTML de bloqueo; el usuario espera que el run siga y el local quede `needs_manual`, no que crashee. Test en Task 1.
- **Nombre genérico sin dirección útil (ej. "Café", "Restaurante"):** el usuario espera que no se acepte una web cualquiera; el LLM debe devolver score bajo. Test en Task 1.
- **Solo hay perfiles sociales (Instagram/Facebook/TikTok):** el usuario espera `None`, no un Instagram como `website`. Test en Task 1.
- **Cuota Gemini 429:** el usuario espera degradación silenciosa a `None` y que el resto de locales siga. Test en Task 1.
- **Sucursal homónima en otra comuna:** el usuario espera no aceptar la web de otra sucursal; exigir overlap de token de dirección. Test en Task 1.

---

## File Structure

- **Crea:** `maps_gluten/website_search.py` — query, fetch `html.duckduckgo.com/html/`, parse, filtro de sociales/agregadores, validación Gemini REST, orquestador `search_website`.
- **Modifica:** `maps_gluten/extract.py` — agrega `website_source: str | None` a `Place`.
- **Modifica:** `maps_gluten/enrich.py` — fallback tras `_extract_website` que llame `search_website` si `website` es `None`, setea `website_source='search'`.
- **Modifica:** `maps_gluten/store.py` — columna `website_source`, migración, `UPSERT` y `write_jsonl` metadata.
- **Modifica:** `maps_gluten/cli.py` — lee `MAPS_WEBSITE_SEARCH`, `GEMINI_SEARCH_MODEL`, pasa flag a `scrape_list`.
- **Modifica:** `scripts/update_new_places.py` — fallback tras `discover_links` si `website` vacío, persiste en `place_links.json` y `metadata`.
- **Crea:** `tests/test_website_search.py` — tests unitarios con HTML mockeado y `urllib` mockeado.
- **Modifica:** `.env.example`, `README.md` — flags y nota de provenance.

---

### Task 1: Núcleo `website_search.py`

**Files:**
- Create: `maps_gluten/website_search.py`
- Test: `tests/test_website_search.py`

**Interfaces:**
- Consumes: `os.getenv("GEMINI_SEARCH_MODEL", "gemini-flash-lite-latest")`, patrón REST de `photos.py:123-157`.
- Produces:
  - `build_search_query(name: str, address: str | None) -> str`
  - `fetch_candidates(query: str, *, timeout: int = 12) -> list[dict]` donde cada `dict` es `{"url": str, "title": str, "snippet": str}`
  - `filter_candidates(candidates: list[dict]) -> list[dict]`
  - `llm_validate(name: str, address: str | None, candidates: list[dict], api_key: str) -> tuple[str | None, float]` (url, score 0.0–1.0)
  - `search_website(name: str, address: str | None, *, api_key: str | None, timeout: int = 12) -> tuple[str | None, float, str | None]` (url, score, error)
  - `DEFAULT_SEARCH_MODEL = "gemini-flash-lite-latest"` y `BAD_HOST_RE` para sociales.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_search_query_strips_and_adds_comuna():
    assert build_search_query("Café Bicka", "Av. Luis Pasteur 6156, Vitacura") == '"Café Bicka" sin gluten Vitacura Av Luis Pasteur 6156'

def test_fetch_candidates_parses_duckduckgo_html():
    # fixture con 3 resultados: 1 oficial, 1 tripadvisor, 1 instagram
    # assert len(fetch_candidates("x")) == 3
    # assert urls preservan orden y decodifican uddg

def test_filter_candidates_drops_social_and_keeps_official():
    # assert instagram/facebook/tiktok/uber-eats/ra998 fuera
    # assert max 5

def test_llm_validate_requires_name_and_address_overlap(tmp_path, monkeypatch):
    # monkeypatch urlopen -> JSON {"url": "https://bickacafe.cl/", "score": 0.92, "reason": "ok"}
    # assert llm_validate(...) == ("https://bickacafe.cl/", 0.92)
    # monkeypatch score 0.4 -> assert (None, 0.4)

def test_search_website_returns_none_when_no_api_key():
    # assert search_website("Café", "Av X", api_key=None) == (None, 0.0, None)

def test_search_website_degrades_on_block_and_429(monkeypatch):
    # urlopen raise 403 -> (None, 0.0, "blocked")
    # urlopen raise 429 -> (None, 0.0, "quota")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_website_search.py -v`
Expected: FAIL con `ModuleNotFoundError: maps_gluten.website_search` o `ImportError`.

- [ ] **Step 3: Implement `maps_gluten/website_search.py`**

Implementa las 6 firmas de Interfaces con stdlib: `build_search_query` (usa `_normalize`, extrae comuna como último token tras coma si existe), `fetch_candidates` hace `GET https://html.duckduckgo.com/html/?q={quote_plus(query)}` con `UA` de `photos.py`, parse con `HTMLParser` sobre `a.result__a` + `a.result__snippet`, decodifica `uddg`, `filter_candidates` excluye `instagram.com|facebook.com|tiktok.com|tripadvisor|ubereats|rappi|pedidosya` y limita a 5, `llm_validate` hace `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=...` con prompt "Devuelve SOLO JSON {url, score, reason}; acepta solo si nombre coincide y hay overlap de dirección; score<0.85 => url null", reusa `_parse` como en `photos.py:_parse_vision_json`. `search_website` orquesta `build->fetch->filter->llm_validate` y acepta solo si `score>=0.85`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_website_search.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/website_search.py tests/test_website_search.py
git commit -m "feat: add website_search core with DuckDuckGo and LLM validation"
```

---

### Task 2: Integración en `enrich.py` + procedencia en `store.py` y `extract.py`

**Files:**
- Modify: `maps_gluten/extract.py` (dataclass `Place`)
- Modify: `maps_gluten/enrich.py` (`enrich_places`, `_extract_website`)
- Modify: `maps_gluten/store.py` (SCHEMA, MIGRATIONS, UPSERT, `write_jsonl`)
- Modify: `maps_gluten/cli.py` (env)
- Test: `tests/test_website_search.py` (nuevo test `test_enrich_places_uses_search_fallback`), `tests/test_store_contract.py` (add cobertura)

**Interfaces:**
- Consumes: `search_website(name, address, *, api_key, timeout) -> (url, score, error)` de Task 1.
- Produces:
  - `Place.website_source: str | None` (`"maps"` | `"search"` | `None`)
  - `enrich_places(..., search_enabled: bool = True, gemini_api_key: str | None = None)` — si `search_enabled` y `_extract_website` es `None` y hay `api_key`, llama `search_website` y si `score>=0.85` setea `place.website=url`, `place.website_source='search'`.
  - `store.MIGRATIONS += ("website_source", "TEXT")`, `UPSERT` conserva con `COALESCE(NULLIF(...))`, `write_jsonl` metadata incluye `website_source`.

- [ ] **Step 1: Write the failing tests**

```python
def test_enrich_places_uses_search_fallback(monkeypatch):
    # place con url Maps, monkeypatch page + search_website -> ("https://ejemplo.cl/", 0.9, None)
    # assert place.website == "https://ejemplo.cl/" and place.website_source == "search"
    # con score 0.3 -> assert website is None

def test_store_persists_website_source():
    # save() con Place(website_source="search") y reload metadata -> assert website_source == "search"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_website_search.py tests/test_store_contract.py -v`
Expected: FAIL con `TypeError: unexpected keyword argument 'search_enabled'` o `website_source` ausente.

- [ ] **Step 3: Implement integration**

En `extract.py` agrega campo con default `None`. En `enrich.py` importa `search_website` dentro de la función (evitar ciclo), ejecuta fallback solo si `not website` y `search_enabled and gemini_api_key`, mide tiempo con `time.sleep(0.5)` entre búsquedas para rate-limit suave. En `store.py` ejecuta migración y expone en `metadata`. En `cli.py` lee `MAPS_WEBSITE_SEARCH` (`_env_bool` default `True`) y `GEMINI_API_KEY`, pásalo a `scrape_list` (que a su vez lo pasa a `enrich_places`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_website_search.py tests/test_store_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/extract.py maps_gluten/enrich.py maps_gluten/store.py maps_gluten/cli.py tests/
git commit -m "feat: wire website search fallback in enrich and persist provenance"
```

---

### Task 3: Integración en `update_new_places.py` (flujo de locales nuevos)

**Files:**
- Modify: `scripts/update_new_places.py` (`main`, loop de targets)
- Test: `tests/test_update_new_places.py` (nuevo test `test_update_new_places_uses_search_when_maps_empty`)

**Interfaces:**
- Consumes: `search_website` de Task 1, `Place.website_source` de Task 2, `links` de `discover_links` (`maps_links.py`).
- Produces: `stored_links[ftid]["website"]` y `metadata["website"]` actualizados cuando Maps no trae web, más `record["metadata"]["website_source"] = "search"`; si no hay match, `links` queda como antes y el reporte marca `needs_manual` (sin cambio de formato).

- [ ] **Step 1: Write the failing test**

```python
def test_update_new_places_uses_search_when_maps_empty(monkeypatch, tmp_path):
    # stored_links sin website, discover_links -> website None, mock search_website -> ("https://nuevo.cl/", 0.95, None)
    # assert stored_links[ftid]["website"] == "https://nuevo.cl/"
    # assert metadata website_source == "search"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_update_new_places.py::test_update_new_places_uses_search_when_maps_empty -v`
Expected: FAIL con `assert None == "https://nuevo.cl/"`.

- [ ] **Step 3: Implement fallback en `update_new_places.py`**

Tras `links = discover_links(...)` y si `not links.get("website") and not metadata.get("website")`, si `MAPS_WEBSITE_SEARCH` y `GEMINI_API_KEY`, llama `search_website(name, address)`. Si aceptado, setea `links["website"]=url`, `links["name"]=name`, y al construir `PlaceContext` usa ese website. Respeta `--dry-run` (no escribe `stored_links`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_update_new_places.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/update_new_places.py tests/test_update_new_places.py
git commit -m "feat: use website search fallback for new places without web"
```

---

### Task 4: Cableado CLI/env + docs + verificación final

**Files:**
- Modify: `maps_gluten/cli.py` (ya tocado en Task 2, completar flags), `.env.example`, `README.md`
- Test: verificación manual `python scripts/update_new_places.py --places 'Café Kanela' --dry-run` (solo si hay clave)

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: `MAPS_WEBSITE_SEARCH=1` documentado, `--no-website-search` en `cli.py run`, y sección README "Búsqueda de web cuando Maps no la trae (DuckDuckGo + Gemini)".

- [ ] **Step 1: Add CLI flag test**

```python
def test_cli_parses_no_website_search():
    args = _build_parser().parse_args(["run", "--no-website-search"])
    assert args.website_search is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_website_search.py::test_cli_parses_no_website_search -v`
Expected: FAIL (flag no existe).

- [ ] **Step 3: Implement flag + docs**

Agrega `--website-search/--no-website-search` (`BooleanOptionalAction`, default `None` -> usa `MAPS_WEBSITE_SEARCH`), actualiza `.env.example` y README con origen, umbral 0.85 y degradación.

- [ ] **Step 4: Run full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS total, sin regresiones en `test_platform_*`.

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/cli.py .env.example README.md
git commit -m "docs: document website search fallback and flags"
```

---

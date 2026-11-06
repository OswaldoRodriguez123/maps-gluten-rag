# Website Search con Playwright + GEMINI_API_KEY en .env.example

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el buscador de web (DuckDuckGo) funcione de verdad en CI usando Playwright en lugar de urllib (evita el anti-bot/anomaly de DDG), y documentar GEMINI_API_KEY en .env.example (ya se usa para visión y ya se pasa en el workflow).

**Architecture:**
- `fetch_candidates` cambia de `urllib.request` a Playwright: navega a DuckDuckGo HTML, parsea `a.result__a` + `a.result__snippet` desde el DOM renderizado.
- `search_website` acepta `page` o `browser` opcional de Playwright. Si se pasa `page`, lo usa directamente; si se pasa `browser`, crea una página temporal; si no, lanza un browser temporal (modo standalone para tests).
- `enrich_places` pasa el `page` ya abierto (está en ficha de Maps; se reusa para DDG).
- `update_new_places` pasa el `browser` compartido.
- `.env.example` agrega línea comentada `# GEMINI_API_KEY=` (ya se pasa en scrape.yml vía secrets).

**Tech Stack:** Python 3.12, Playwright (ya en repo), urllib solo para Gemini LLM (ya usado en photos.py).

**Spec:** `docs/superpowers/specs/2026-11-06-website-search-design.md`

## Global Constraints
- No dependencias nuevas (Playwright ya está en requirements.txt).
- `GEMINI_API_KEY` reusado (ya existe como secreto en GitHub Actions para visión).
- `MAPS_WEBSITE_SEARCH=1` por defecto; degrade silencioso si DDG falla o 429/403.
- Umbral 0.85, candidato debe estar en la lista (anti-alucinación), `needs_manual` si no hay match.
- No tocar `entitylist/getlist` ni el scraper de lista.

## Review Focus
- **DDG anomaly/anti-bot:** Playwright resuelve el bloqueo que `urllib` sufría. Test debe verificar que `fetch_candidates` navega a DDG y extrae resultados del DOM renderizado.
- **Reuso de page en enrich_places:** `page` de Maps se usa también para DDG; después de la búsqueda debe seguir sirviendo para el siguiente lugar (o no romper el flow).
- **Browser compartido en update_new_places:** `browser` se pasa al fallback y se reusa entre locales.
- **Sin GEMINI_API_KEY:** `search_website` devuelve `(None, 0.0, None)` sin red.
- **Threshold 0.85:** score bajo => `None`, no se acepta.
- **URL inventada por LLM:** se rechaza si no está entre candidatos.

## File Structure
- Modify: `maps_gluten/website_search.py` — Playwright en fetch_candidates, params page/browser en search_website.
- Modify: `maps_gluten/enrich.py` — pasar page a search_website.
- Modify: `scripts/update_new_places.py` — pasar browser al _apply_search_fallback.
- Modify: `.env.example` — agregar `# GEMINI_API_KEY=` comentado.
- Modify: `tests/test_website_search.py` — reescribir tests para Playwright (mockeado o browser real).
- Test: `tests/test_store_contract.py` (ya existe, verificar que no rompa).

---

### Task 1: Playwright en website_search.py

**Files:**
- Modify: `maps_gluten/website_search.py`

**Interfaces:**
- Consumes: `sync_playwright` de playwright.
- Produces:
  - `fetch_candidates(query, *, timeout=12, page=None) -> list[dict]` — navega a DDG con Playwright, parsea resultados.
  - `search_website(name, address, *, api_key, timeout=12, page=None, browser=None) -> (url, score, error)` — acepta page/browser opcional.
  - `DEFAULT_SEARCH_MODEL`, `ACCEPT_THRESHOLD=0.85`, `BAD_HOST_RE` (mismo).
  - `_launch_temp_browser()` helper para modo standalone (tests).

- [ ] **Step 1: Implement fetch_candidates con Playwright**
  - Reemplazar `urllib.request.urlopen` por navegación Playwright a `DDG_URL + "?q=" + quote_plus(query)`.
  - Esperar a que cargue `a.result__a` (o timeout).
  - Extraer con `page.eval_on_selector_all` o `page.query_selector_all`.
  - Decodificar `uddg` como antes.
  - Si no hay `page` parámetro, crear browser temporal con `sync_playwright()`.

- [ ] **Step 2: Agregar page/browser a search_website**
  - Firma: `search_website(name, address, *, api_key, timeout=12, page=None, browser=None)`.
  - Si `page`: usarlo directamente para fetch_candidates.
  - Si `browser`: `page = browser.new_page()`, usar, cerrar página al final.
  - Si ninguno: `sync_playwright()`, `chromium.launch(headless=True)`, nueva página, usar, cerrar todo.
  - Mantener degradación 403/429/excepción → `(None, 0.0, error)`.

- [ ] **Step 3: Run tests to verify they pass**
  - Reescribir tests de test_website_search.py para Playwright (ver Task 5).

- [ ] **Step 4: Commit**
  ```bash
  git add maps_gluten/website_search.py
  git commit -m "feat: website_search DuckDuckGo via Playwright instead of urllib"
  ```

---

### Task 2: Pasar page en enrich_places (enrich.py)

**Files:**
- Modify: `maps_gluten/enrich.py`

**Interfaces:**
- Consumes: `page` (ya disponible en `enrich_places(page, ...)`).
- Produces: llamada `search_fn(place.name, place.address, api_key=gemini_api_key, page=page)`.

- [ ] **Step 1: Modificar llamada a search_fn en enrich_places**
  - Línea ~748: agregar `page=page` a la llamada.

- [ ] **Step 2: Run tests**
  - `.venv/bin/python -m pytest tests/test_website_search.py tests/test_store_contract.py -v`

- [ ] **Step 3: Commit**

---

### Task 3: Pasar browser en update_new_places.py

**Files:**
- Modify: `scripts/update_new_places.py`

**Interfaces:**
- Consumes: `browser` (ya disponible en el `with sync_playwright()` block).
- Produces: `_apply_search_fallback(..., browser=browser)` y pasar a `search_website`.

- [ ] **Step 1: Modificar _apply_search_fallback para aceptar y pasar browser**
  - Agregar parámetro `browser=None` y pasarlo a `search_website(..., browser=browser)`.

- [ ] **Step 2: Run tests**
  - `.venv/bin/python -m pytest tests/test_update_new_places.py -v`

- [ ] **Step 3: Commit**

---

### Task 4: Documentar GEMINI_API_KEY en .env.example

**Files:**
- Modify: `.env.example`

**Interfaces:**
- Produces: línea `# GEMINI_API_KEY=` comentado cerca de las demás claves de API.

- [ ] **Step 1: Agregar línea comentada**
  - Después de `# GEMINI_SEARCH_MODEL=gemini-flash-lite-latest`, agregar `# GEMINI_API_KEY=` (o cerca de donde están las demás keys).

- [ ] **Step 2: Commit**

---

### Task 5: Tests para Playwright + suite completa

**Files:**
- Modify: `tests/test_website_search.py`

**Interfaces:**
- Consumes: `sync_playwright` para tests.
- Produces: tests que mockeen o usen Playwright real para fetch_candidates, llm_validate, search_website.

- [ ] **Step 1: Reescribir tests**
  - `test_fetch_candidates_parses_duckduckgo_html`: mockea `page.goto` y `page.eval_on_selector_all` o usa HTML fixture inyectado.
  - `test_search_website_degrades_on_block_and_429`: mantener (errores de red).
  - `test_search_website_returns_none_when_no_api_key`: mantener.
  - `test_llm_validate_*`: mantener (mockean urllib para Gemini).
  - `test_search_website_end_to_end`: mockea page de Playwright + LLM.

- [ ] **Step 2: Run full suite**
  - `.venv/bin/python -m pytest -q` → 44+ passed, no regressions.

- [ ] **Step 3: Commit**

---

### Task 6: Push directo a main (sin PR)

**Files:**
- Commit acumulado de Tasks 1-5.

- [ ] **Step 1: git push origin main** (sin PR, como pidió el usuario).

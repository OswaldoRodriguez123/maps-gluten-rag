# Brave Search como fallback (borra DuckDuckGo) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Reemplazar el fallback DuckDuckGo (bloqueado en IPs datacenter) por Brave Search API en `website_search`, dejando la cadena SerpAPI → Brave → LLM.

**Architecture:** Se porta el cliente Brave de bailoteca (`sources/brave.py`) a `maps_gluten/website_search.py`, adaptado a devolver `(candidatos, status)` como `fetch_candidates_serpapi`. `search_website` intenta SerpAPI; si falla o no hay key, intenta Brave; el resto (filtro, `platform_urls`, validación Gemini, umbral 0.85) no cambia. Se elimina todo el código DDG/Playwright del módulo (`urlparse` sigue haciendo falta; `UA` lo usan SerpAPI y Brave).

**Tech Stack:** Python 3 stdlib (`urllib`), pytest, requests no requerido.

## Global Constraints

- Sin dependencias nuevas: solo stdlib.
- `search_website` mantiene el contrato `(official_url, score, status, platform_urls)`.
- Statuses posibles tras el cambio: `None` (SerpAPI ok), `"brave_fallback"` (SerpAPI falló, Brave ok), `"no_serpapi_key"` (sin SERPAPI_KEY, Brave ok), `"blocked"` (403 en el motor que se intentó), `"quota"` (429), `"error"` (otro fallo), `"no_search_key"` (ninguna key configurada).
- Brave: `country=cl`, `search_lang=es`, `count=10`, `safesearch=moderate`, header `X-Subscription-Token`. NUNCA loguear la key.
- Toda URL sigue exigiendo validación Gemini ≥ 0.85 o no se acepta.

## Review Focus

1. Brave responde 200 pero `web`/`results` malformado → se trata como `[]` + `status` ok con 0 candidatos (degrada a `needs_manual`, no crashea). Test: payload `{}`.
2. Brave 403/429/500 → `blocked`/`quota`/`error` → `search_website` degrada sin excepción. Tests dedicados.
3. Sin ninguna key → `(None, 0.0, "no_search_key", {})` sin tocar la red. Test con `urlopen` que explota.
4. LLM inventa URL (homónimo) → sigue rechazada aunque Brave la liste; comportamiento existente, tests existentes.
5. SERPAPI_KEY set pero SerpAPI caído + Brave ok → status `brave_fallback` y URL aceptada. Test con ambos mockeados.

---

### Task 1: Cliente Brave + tests

**Files:**
- Modify: `maps_gluten/website_search.py`
- Test: `tests/test_website_search.py`

**Interfaces:**
- Produces: `fetch_candidates_brave(query: str, *, api_key: str | None, timeout: int = 10) -> tuple[list[dict], str | None]` — cada dict es `{"url","title","snippet"}`; status `None` ok, `"no_key"`, `"blocked"` (403), `"quota"` (429), `"error"`. `BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"`.

- [x] **Step 1: Write the failing tests** — en `tests/test_website_search.py`, sección `--- 2. fetch_candidates ---`: reemplazar `test_fetch_candidates_parses_duckduckgo_html` por tests de Brave: (a) payload `{"web":{"results":[{url,title,description},...]}}` → parsea url/title/snippet, salta entradas sin url/title; (b) 403 → `([], "blocked")`, 429 → `([], "quota")`, 500 → `([], "error")`, api_key None → `([], "no_key")`; (c) payload `{}` → `([], None)`. Mock con `monkeypatch.setattr("urllib.request.urlopen", fake)` devolviendo `_FakeResponse` con JSON. URL contiene `q=` encoded y header `X-Subscription-Token`.
- [x] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_website_search.py -k brave -v` → FAIL (función no existe).
- [x] **Step 3: Implement** `fetch_candidates_brave` en `website_search.py` tras `fetch_candidates_serpapi`, misma forma que el de SerpAPI pero GET con params (`q`, `count=10`, `country=cl`, `search_lang=es`, `safesearch=moderate`) y header `X-Subscription-Token`. Snippet = `description` de Brave. Mantener `.[:10]`.
- [x] **Step 4: Run to verify pass** — mismo comando → PASS.

### Task 2: `search_website` SerpAPI → Brave; borrar DDG

**Files:**
- Modify: `maps_gluten/website_search.py` (docstring, constantes, borrados, firma)
- Modify: `maps_gluten/cli.py` (help text → SerpAPI/Brave)
- Test: `tests/test_website_search.py`

**Interfaces:**
- Consumes: `fetch_candidates_brave` (Task 1).
- Produces: `search_website(name, address, *, api_key, timeout=12) -> tuple[str|None, float, str|None, dict]` — **sin** params `page`/`browser`.

- [x] **Step 1: Rewrite the failing tests** — `test_search_website_degrades_on_block_and_429`: mockear `fetch_candidates_serpapi` → `([], "error")` y `fetch_candidates_brave` para 403/429 → `(None, 0.0, "blocked"|"quota", {})`; y caso SerpAPI error + Brave ok → status `brave_fallback`. `test_search_website_end_to_end_accepts_strong_match`: mockear ambas fetch functions (serpapi → `([], "no_key")`, brave → 3 candidatos bickacafe/tripadvisor/instagram), `urlopen` → LLM 0.91 → assert `(url, score, "no_serpapi_key")`. Añadir test `test_search_website_no_search_key`: sin env keys → `(None, 0.0, "no_search_key", {})` y `urlopen` que explota no se llama. Usar `monkeypatch.delenv(..., raising=False)` / `setenv` para aislar `SERPAPI_KEY`/`BRAVE_API_KEY` del entorno local.
- [x] **Step 2: Run to verify fails**.
- [x] **Step 3: Implement** — en `website_search.py`: borrar `DDG_URL`, `_decode_uddg`, `_DDGParser`, `fetch_candidates`, `_launch_temp_browser`, `_close_temp_browser`, constantes/`import HTMLParser` huérfanos; `search_website` lee `BRAVE_API_KEY` del env; flujo: serpapi (si key) → si sin candidatos y brave_key → brave; status según Global Constraints (sin ninguna key → `no_search_key`; brave ok → `brave_fallback` si serpapi_key, si no `no_serpapi_key`; todo falló y brave dio blocked/quota → ese status; si no → `error`). Quitar params `page`/`browser` de la firma y de su docstring; actualizar docstring del módulo y `cli.py` help.
- [x] **Step 4: Run to verify pass** — `pytest tests/test_website_search.py -v`.

### Task 3: Callers sin `page`/`browser`

**Files:**
- Modify: `maps_gluten/enrich.py:740` (quitar `page=page` del `search_fn(...)`; `page` sigue siendo de Maps)
- Modify: `scripts/update_new_places.py` (`_apply_search_fallback`: quitar param `browser` y pasarlo al fn; call-site en ~line 403 quitar `browser=browser`)
- Modify: `tests/test_website_search.py` (`test_enrich_places_uses_search_fallback`: `_fake_search` sin `page=`, quitar asserts de `captured["page"]`)
- Modify: `tests/test_update_new_places.py:213` (fake sin `browser=` si quedó sin uso)

- [x] **Step 1:** Aplicar cambios; buscar restos con `grep -n "fetch_candidates\b\|_DDGParser\|DDG\|html.duckduckgo\|page=_fake\|browser=browser" -r maps_gluten scripts tests`.
- [x] **Step 2:** `.venv/bin/python -m pytest tests/ -v` → todo PASS (fijarse en tests de `update_new_places` y `enrich`).

### Task 4: CI, .env.example, README, serpapi-test

**Files:**
- Modify: `.github/workflows/scrape.yml` y `update-new.yml` (añadir `BRAVE_API_KEY: ${{ secrets.BRAVE_API_KEY }}` junto a SERPAPI_KEY)
- Modify: `.github/workflows/serpapi-test.yml` (status sentinel: aceptar `no_serpapi_key`/`no_search_key`)
- Modify: `.env.example` (comentario: SerpAPI + Brave fallback; añadir `# BRAVE_API_KEY=` y `# SERPAPI_KEY=`)
- Modify: `README.md` (título sección → SerpAPI/Brave; bullets: cadena SerpAPI → Brave → Gemini; quitar DDG/403 narrativa vieja; mencionar `BRAVE_API_KEY`; statuses actualizados)

- [x] **Step 1:** Aplicar ediciones.
- [x] **Step 2:** `grep -ri "duckduckgo\|ddg" README.md .env.example .github maps_gluten scripts tests` → solo hits históricos en `docs/superpowers/` (no tocar) o cero.

### Task 5: Copiar key (sin imprimirla) y verificar

- [x] **Step 1:** `gh secret set BRAVE_API_KEY --repo OswaldoRodriguez123/maps-gluten-rag < <(grep '^BRAVE_API_KEY=' /Users/oswaldorodriguez/repos/bailoteca/parser/.env | cut -d= -f2-)`.
- [x] **Step 2:** Añadir `BRAVE_API_KEY=...` al `.env` local con la misma extracción (`>> .env`), sin mostrar el valor. (gitignored ✓)
- [x] **Step 3:** Suite completa: `.venv/bin/python -m pytest tests/ -q` → PASS; `git diff --stat` revisión visual; reportar. **No commitear** salvo que el usuario lo pida.

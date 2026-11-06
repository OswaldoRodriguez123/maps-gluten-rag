# Actualización automática de locales nuevos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar un workflow que descubra locales nuevos, detecte su plataforma y extraiga su carta estructurada, sin reprocesar los locales existentes.

**Architecture:** Un orquestador (`scripts/update_new_places.py`) selecciona locales nuevos, descubre links de Google Maps y prueba adaptadores en `maps_gluten/platforms/`. Cada adaptador devuelve `MenuItem`s; el orquestador escribe el contrato actual, normaliza y publica.

**Tech Stack:** Python 3.12, Playwright, requests, SQLite, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-06-new-places-platform-detection-design.md`

## Global Constraints

- No reprocesar todos los locales por defecto.
- No borrar una carta existente si la extracción nueva queda en 0 publicables.
- `source` debe viajar en `_menus.jsonl` y en SQLite.
- `first_observed_at` es la vara de “nuevo”, no `first_seen`.
- `--dry-run` no escribe datos ni llama a Apify/Gemini.
- Todo el texto de datos va en español.
- GitHub Actions, sin dependencia de la Mac.
- Sin suite completa de tests; usar `unittest` con fixtures para los parsers.

## Review Focus

- **Shopify con 429:** `products.json` bloqueado debe caer a UCP, luego a sitemap + navegador; nunca debe dejar el local sin carta si había una.
- **Apparta con variantes:** un ítem con `prices_list` de varias marcas/tamaños no debe colapsar en un solo precio; debe generar variantes.
- **Reporte final:** un `ok` de extracción con 0 publicables debe terminar como `needs_manual`.
- **Dry-run:** no debe escribir `place_links.json`, SQLite, JSONL ni Doc.
- **Locales nuevos sin web:** deben terminar en `needs_manual`, no en error fatal.

---

### Task 1: Contrato de datos y `first_observed_at`

**Files:**
- Modify: `maps_gluten/store.py`
- Modify: `scripts/normalize_menus.py`
- Test: `tests/test_store_contract.py`

**Interfaces:**
- Consumes: `store.save(conn, key, title, places, today)`.
- Produces: columna `places.first_observed_at`; `metadata.first_observed_at` en el JSONL; `write_menus_jsonl` conserva `source`, `status`, `kind`, `dietary_tags`, `price_display`.

- [ ] **Step 1: Write the failing test**

```python
import sqlite3, tempfile
from pathlib import Path
from maps_gluten import store
from maps_gluten.extract import Place

def test_first_observed_at_is_set_once():
    with tempfile.TemporaryDirectory() as tmp:
        conn = store.connect(Path(tmp) / "t.db")
        p = Place(ftid="abc", name="X", url="https://maps", saved_on="2020-01-01")
        store.save(conn, "list", "L", [p], "2026-11-06")
        first = conn.execute("SELECT first_observed_at FROM places WHERE ftid='abc'").fetchone()[0]
        store.save(conn, "list", "L", [p], "2026-11-07")
        second = conn.execute("SELECT first_observed_at FROM places WHERE ftid='abc'").fetchone()[0]
        assert first == "2026-11-06"
        assert second == "2026-11-06"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_store_contract -v`
Expected: FAIL por columna inexistente.

- [ ] **Step 3: Implementar la migración y la conservación de `source`**

En `store.py`:
- agregar `first_observed_at TEXT` al `SCHEMA` y a `MIGRATIONS`;
- en `connect`, backfill `UPDATE places SET first_observed_at = COALESCE(first_seen, last_seen) WHERE first_observed_at IS NULL`;
- incluir `first_observed_at` en el `INSERT`/`UPSERT` con el valor `today` (no actualizarlo en conflicto);
- incluir `first_observed_at` en el metadata del JSONL;
- en `write_menus_jsonl`, agregar al `record` los campos `source`, `status`, `kind`, `dietary_tags`, `price_display`.

En `normalize_menus.py`, agregar `apparta` a `STORE_SOURCES`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_store_contract -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/store.py scripts/normalize_menus.py tests/test_store_contract.py
git commit -m "feat: first_observed_at y preservar source en menus"
```

---

### Task 2: Base de adaptadores y registro

**Files:**
- Create: `maps_gluten/platforms/__init__.py`
- Create: `maps_gluten/platforms/base.py`
- Test: `tests/test_platforms_base.py`

**Interfaces:**
- Produces:
  - `MenuItem(name, price=None, category=None, description=None, url=None, source="web")`
  - `MenuResult(status, items=[], source="web", url=None, error=None)`
  - `PlaceContext(record, place_id, name, website, menu_url, order_urls, session, browser=None, allow_photos=True, dry_run=False, max_items=500)`
  - `Adapter` protocol con `name`, `detect(ctx) -> bool`, `extract(ctx) -> MenuResult`
  - `extract(ctx) -> MenuResult` que recorre `ADAPTERS` y devuelve el primer `ok` o `needs_manual`.

- [ ] **Step 1: Write the failing test**

```python
from maps_gluten.platforms import MenuItem, MenuResult, extract
from maps_gluten.platforms.base import PlaceContext
# fake adapter que detecta y devuelve un item
# assert extract(ctx).status == "ok" y len(items)==1
# sin adaptadores que detecten: assert status == "needs_manual"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_platforms_base -v`
Expected: FAIL por imports.

- [ ] **Step 3: Implementar `base.py` y el registro**

`__init__.py` importa los adaptadores y define `ADAPTERS` en orden: Fudo, Apparta, WooCommerce, Shopify, JsonLd, Render, Photos. Para evitar imports circulares, los adaptadores se importan dentro de `extract()` o en `__init__` al final.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_platforms_base -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/platforms tests/test_platforms_base.py
git commit -m "feat: base de adaptadores de plataforma"
```

---

### Task 3: Adaptador Fudo

**Files:**
- Create: `maps_gluten/platforms/fudo.py`
- Test: `tests/test_platform_fudo.py`

**Interfaces:**
- Consumes: `maps_gluten.fudo.fetch_menu(url) -> list[dict]`.
- Produces: `FudoAdapter.extract(ctx) -> MenuResult` con `source="fudo"`.

- [ ] **Step 1: Write the failing test**

```python
# monkeypatch fudo.fetch_menu para devolver [{"name": "Torta", "price": "$10.000", "category": "Tortas"}]
# assert adapter.detect(ctx) y extract(ctx).items[0].name == "Torta"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_platform_fudo -v`
Expected: FAIL.

- [ ] **Step 3: Implementar `FudoAdapter`**

`detect` si `menu.fu.do` está en `ctx.menu_url` o `ctx.website`. `extract` llama `fetch_menu`, convierte a `MenuItem`, devuelve `MenuResult("ok", ...)` o `empty`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_platform_fudo -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/platforms/fudo.py tests/test_platform_fudo.py
git commit -m "feat: adaptador Fudo"
```

---

### Task 4: Adaptador Apparta / Tu Mesa

**Files:**
- Create: `maps_gluten/platforms/apparta.py`
- Create: `tests/fixtures/apparta_menu.json`
- Test: `tests/test_platform_apparta.py`

**Interfaces:**
- Consumes: `ctx.menu_url`, `ctx.session`.
- Produces: `AppartaAdapter.extract(ctx) -> MenuResult` con `source="apparta"`.

- [ ] **Step 1: Write the failing test**

Fixture con dos ítems: uno con `prices_list` de 350/500 cc y labels `Sin Gluten`. Assert que se generan 2 ítems para ese producto, que el precio es `$4.500`/`$5.500` y que la descripción contiene `Sin Gluten`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_platform_apparta -v`
Expected: FAIL.

- [ ] **Step 3: Implementar el parser**

- `detect`: host `menu.tu-mesa.com` o `api.apparta.co`.
- `_parse_url`: extraer `branch_id` y `slug` con `r"menu\.tu-mesa\.com/([^/]+)/(\d+)/menu"`.
- `_fetch`: GET `https://api.apparta.co/establishment-menu-items` con `$client[source]=menuWeb`, `$client[establishment_branch_id]`, `$client[establishment_slug]`.
- `_items`: por cada producto, parsear `prices_list`; por cada variante, nombre `base - variante`; labels + descripción; precio `$X`.
- Evitar duplicados por nombre.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_platform_apparta -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/platforms/apparta.py tests/fixtures/apparta_menu.json tests/test_platform_apparta.py
git commit -m "feat: adaptador Apparta"
```

---

### Task 5: WooCommerce, JSON-LD y web renderizada

**Files:**
- Create: `maps_gluten/platforms/woocommerce.py`
- Create: `maps_gluten/platforms/jsonld.py`
- Create: `maps_gluten/platforms/render.py`
- Test: `tests/test_platform_web.py`

**Interfaces:**
- `WooCommerceAdapter.extract(ctx) -> MenuResult` con `source="woocommerce"`.
- `JsonLdAdapter.extract(ctx) -> MenuResult` con `source="web-jsonld"`.
- `RenderAdapter.extract(ctx) -> MenuResult` con `source="web-render"`.

- [ ] **Step 1: Write the failing tests**

- Woo: fixture con `prices.price=4990`, `currency_minor_unit=0`, categoría `Sin gluten`; assert `$4.990`.
- JSON-LD: fixture `Product` con `offers.price=15900`; assert `$15.900`.
- Render: fake page que devuelve `["Pizza Margarita"]`; assert item sin precio.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_platform_web -v`
Expected: FAIL.

- [ ] **Step 3: Implementar los tres adaptadores**

- Woo: `detect` con `GET /wp-json/wc/store/products?per_page=1`; `extract` pagina de 100 en 100.
- JSON-LD: reutilizar la lógica de `crawl_web_products.page_products` (copiar las funciones privadas necesarias).
- Render: `detect` si hay website; `extract` usa `enrich._render_site_products(ctx.browser.new_page(), ctx.website)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_platform_web -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/platforms/woocommerce.py maps_gluten/platforms/jsonld.py maps_gluten/platforms/render.py tests/test_platform_web.py
git commit -m "feat: adaptadores Woo, JSON-LD y render"
```

---

### Task 6: Adaptador Shopify

**Files:**
- Create: `maps_gluten/platforms/shopify.py`
- Create: `tests/fixtures/shopify_ucp.json`
- Test: `tests/test_platform_shopify.py`

**Interfaces:**
- `ShopifyAdapter.extract(ctx) -> MenuResult` con `source="shopify"` o `"web-render"` si solo hay DOM.

- [ ] **Step 1: Write the failing test**

Fixture UCP con 2 productos y `pagination.has_next_page=True`; assert que el parser sigue el cursor y devuelve 3 ítems con precio. Agregar un caso donde `products.json` responde 429 y el adaptador debe caer a UCP sin fallar.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_platform_shopify -v`
Expected: FAIL.

- [ ] **Step 3: Implementar el adaptador**

- `detect`: `products.json` responde JSON, o home contiene `Shopify`, o sitemap tiene `sitemap_products`.
- `_products_json`: paginar `products.json`.
- `_ucp`: GET `/.well-known/ucp`, obtener endpoint MCP, `initialize`, `tools/call search_catalog` con `filters.available=false`, `pagination.limit=100`, seguir cursor.
- `_sitemap`: leer `sitemap.xml`, juntar `sitemap_products_*.xml`, abrir cada ficha con Playwright y parsear JSON-LD `Product`/`ProductGroup`.
- Si no hay JSON-LD, usar precio DOM y `source="web-render"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_platform_shopify -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/platforms/shopify.py tests/fixtures/shopify_ucp.json tests/test_platform_shopify.py
git commit -m "feat: adaptador Shopify con UCP y sitemap"
```

---

### Task 7: Fotos y descubrimiento de links de Maps

**Files:**
- Create: `maps_gluten/platforms/photos.py`
- Create: `maps_gluten/platforms/maps_links.py`
- Test: `tests/test_platform_photos_links.py`

**Interfaces:**
- `PhotosAdapter.extract(ctx) -> MenuResult` con `source="photo"`; devuelve `needs_manual` si no hay `APIFY_TOKEN`.
- `discover_links(record, browser) -> dict` con `website`, `menu`, `order`.

- [ ] **Step 1: Write the failing test**

- Photos: con `allow_photos=False`, assert `status == "needs_manual"`.
- Maps links: fake page con anchors `https://menu.fu.do/x` y `tel:`; assert `menu` correcto y `order` vacío.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_platform_photos_links -v`
Expected: FAIL.

- [ ] **Step 3: Implementar**

- `PhotosAdapter`: construir `Place` desde `ctx.record`, llamar `photos.enrich_menus_photos` con `APIFY_TOKEN`, parsear `place.menu_json`.
- `maps_links`: adaptar `scripts/scan_maps_links.py` a una función; devolver links y proveedores.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_platform_photos_links -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add maps_gluten/platforms/photos.py maps_gluten/platforms/maps_links.py tests/test_platform_photos_links.py
git commit -m "feat: adaptadores de fotos y links de Maps"
```

---

### Task 8: Orquestador `update_new_places.py`

**Files:**
- Create: `scripts/update_new_places.py`
- Test: `tests/test_update_new_places.py`

**Interfaces:**
- CLI:
  - `--places` (coma), `--since` (ISO), `--baseline` (JSON), `--data-dir`, `--db`, `--dry-run`, `--refresh`, `--photos/--no-photos`, `--max-items`, `--finalize`, `--dump-baseline`.
- `select_targets(places, baseline, since, names, refresh) -> list[dict]`.
- `backup_rows(...)`, `replace_rows(...)`, `write_report(...)`.

- [ ] **Step 1: Write the failing test**

`select_targets` con 3 lugares: uno en baseline, uno nuevo sin baseline, uno con `first_observed_at` reciente. Assert que selecciona los 2 correctos y excluye el que ya tiene menú.

Agregar tests de:
- `--dry-run` no escribe `_menus.jsonl` ni `place_links.json`;
- `--finalize` restaura el backup cuando el target quedó con 0 publicables;
- un lugar sin adaptador disponible termina en `needs_manual`, no en excepción.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_update_new_places -v`
Expected: FAIL.

- [ ] **Step 3: Implementar**

- Cargar JSONL; `--dump-baseline` escribe `{ftid: name}`.
- `select_targets`: nombres explícitos, `ftid` no en baseline, `first_observed_at >= since`; excluir `menu_count > 0` salvo `--refresh`.
- `--dry-run`: no escribe nada; imprime resultados.
- Extracción: para cada target, cargar `place_links.json`; si falta, `discover_links`; construir `PlaceContext`; llamar `platforms.extract`.
- Escritura: backup de filas previas; borrar filas del target; agregar nuevas; escribir reporte fase 1.
- `--finalize`: leer JSONL y reporte; contar `menu_count`; restaurar backup si 0; actualizar estado; escribir reporte final.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_update_new_places -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/update_new_places.py tests/test_update_new_places.py
git commit -m "feat: orquestador de locales nuevos"
```

---

### Task 9: Workflow `update-new.yml`

**Files:**
- Create: `.github/workflows/update-new.yml`

**Interfaces:**
- `workflow_dispatch` con `since`, `places`, `dry_run`, `photos`, `refresh`.
- Pasos: baseline, `run --no-enrich`, extracción, normalización, finalize, rebuild/publicar, commit, cache, artifact.

- [ ] **Step 1: Crear el workflow**

Copiar la estructura de `update-one.yml`, agregar cache del SQLite y los inputs. Usar `MAPS_ENRICH=0`, `MAPS_APIFY=0`, `MAPS_HEADLESS=1`.

- [ ] **Step 2: Verificar sintaxis**

Run: `python - <<'PY'` con `yaml.safe_load` si PyYAML está disponible; si no, revisar manualmente.
Expected: sin errores de indentación.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/update-new.yml
git commit -m "ci: workflow de locales nuevos"
```

---

### Task 10: Documentación y prueba real

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-11-06-new-places-platform-detection-design.md` si cambia algo.

- [ ] **Step 1: Documentar**

Agregar sección “Actualizar solo locales nuevos” con:
- cuándo usarlo;
- inputs del workflow;
- cómo leer el reporte;
- qué significa `needs_manual`;
- que los sitios personalizados siguen siendo manuales.

- [ ] **Step 2: Verificación**

Run:
```bash
python -m unittest discover -s tests -v
python -m py_compile scripts/update_new_places.py maps_gluten/platforms/*.py
python scripts/update_new_places.py --dump-baseline /tmp/baseline.json
python scripts/update_new_places.py --places "Bar El Bajo,BuganVilla,Biomercado" --dry-run
```
Expected: tests PASS, compilación sin errores, dry-run muestra 3 locales sin escribir datos.

- [ ] **Step 3: Corrida real (después de aprobar el plan)**

Disparar `update-new.yml` con `since` = fecha de ayer y revisar `reports/new_places_<fecha>.jsonl`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: actualizar solo locales nuevos"
```

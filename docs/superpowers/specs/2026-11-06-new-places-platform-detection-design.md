# Actualización automática de locales nuevos por plataforma

**Fecha:** 2026-11-06  
**Estado:** diseño propuesto, pendiente de aprobación

## 1. Intención

Cuando se agreguen locales nuevos a la lista de Google Maps, quiero ejecutar **un solo workflow** que:

1. descubra solo esos locales nuevos;
2. detecte qué plataforma usa cada uno (Fudo, WooCommerce, Shopify, Apparta/Tu Mesa, web genérica, etc.);
3. extraiga la carta o catálogo de forma estructurada;
4. lo incorpore al JSONL, al Markdown y al Google Doc;
5. deje un reporte claro de los locales que no pudo resolver, para pedir ayuda manual solo en esos casos.

El objetivo es que el conocimiento que hoy aplicamos a mano quede en código y que los locales nuevos no dependan de una persona.

## 2. Objetivos

- Workflow manual `update-new.yml` con fecha, nombres opcionales y modo dry-run.
- Script orquestador `scripts/update_new_places.py`.
- Registro de adaptadores por plataforma con dos operaciones: `detect()` y `extract()`.
- Adaptadores iniciales: Fudo, Apparta/Tu Mesa, Rappi, WooCommerce, Shopify, JSON-LD genérico, web renderizada y fotos (OCR/Gemini).
- Escritura en el contrato de datos existente (`data/mis_lugares_sin_gluten_menus.jsonl`, JSONL principal, SQLite).
- Reporte `reports/new_places_<fecha>.jsonl` con estado por local.
- No reprocesar los 100 locales existentes cuando solo se piden los nuevos.
- No romper cartas ya existentes si un adaptador falla.

## 3. No objetivos

- No hacer scraping a medida para cada web particular; esos casos quedan marcados como `needs_manual`.
- No garantizar 100% de cobertura ni precios perfectos.
- No reemplazar la normalización P0 ni el quality gate.
- No crear una base de datos nueva; se reutiliza SQLite + JSONL.
- No ejecutarlo en horario automático; será manual mientras se estabiliza.

## 4. Anti-objetivos

- Procesar todos los locales por defecto.
- Publicar nombres generados por OCR sin pasar por normalización.
- Borrar una carta existente porque un adaptador devolvió cero ítems.
- Depender de la Mac o de una sesión interactiva.

## 5. Restricciones

- GitHub Actions, Python 3.12, Playwright, `requests`.
- Sin costo obligatorio: Apify/Gemini solo si los secretos existen.
- Shopify suele responder 429 en `products.json`; debe haber fallback.
- Google Maps cambia el DOM; el descubrimiento de links debe ser tolerante a fallos.
- Los textos y categorías se publican en español.

## 6. Enfoques considerados

### A. Registro de adaptadores por plataforma (elegido)

Un módulo `maps_gluten/platforms/` con una interfaz común. El orquestador prueba adaptadores en orden y se queda con el primero que devuelva ítems estructurados.

- **Ventaja:** agregar una plataforma nueva es agregar un archivo; el flujo principal no crece.
- **Ventaja:** se pueden probar adaptadores por separado con fixtures.
- **Costo:** una capa de abstracción más.

### B. Un script único con `if/elif` por dominio

Todo el conocimiento de plataformas vive en un solo archivo.

- **Ventaja:** rápido de escribir al principio.
- **Costo:** se convierte en un monolito difícil de mantener y de testear.

### C. Configuración YAML por dominio

Un archivo de configuración indica selectores y endpoints por sitio.

- **Ventaja:** alguien no programador podría agregar sitios simples.
- **Costo:** los sitios reales igual necesitan código; la configuración se vuelve un lenguaje propio. No compensa para este volumen.

**Decisión:** A.

## 7. Arquitectura

```
maps_gluten/
  platforms/
    __init__.py        # registro y orden de adaptadores
    base.py            # MenuItem, MenuResult, Adapter
    fudo.py
    appartta.py
    woocommerce.py
    shopify.py
    jsonld.py
    render.py
    photos.py
    maps_links.py
scripts/
  update_new_places.py
.github/workflows/
  update-new.yml
data/
  place_links.json     # links descubiertos por local
  menu_urls.json       # se mantiene para Fudo
reports/
  new_places_<fecha>.jsonl
```

### Interfaz de adaptador

```python
@dataclass
class MenuItem:
    name: str
    price: str | None
    category: str | None = None
    description: str | None = None
    url: str | None = None
    source: str = "web"

@dataclass
class MenuResult:
    status: str          # ok | empty | needs_manual | error
    items: list[MenuItem]
    source: str
    url: str | None = None
    error: str | None = None

class Adapter(Protocol):
    name: str
    def detect(self, ctx: PlaceContext) -> bool: ...
    def extract(self, ctx: PlaceContext) -> MenuResult: ...
```

`PlaceContext` contiene el registro del JSONL, URLs conocidas, sesión HTTP, browser Playwright opcional y opciones (`photos`, `dry_run`, etc.).

## 8. Flujo del orquestador

### 8.1 Descubrir los nuevos

1. Antes de refrescar la lista, guardar los `ftid` existentes en un baseline temporal.
2. Ejecutar `python -m maps_gluten run --no-enrich` para traer la lista actualizada sin enriquecer todos los locales.
3. Seleccionar targets:
   - si se pasó `--places`, solo esos nombres;
   - si no, los `ftid` que no estaban en el baseline;
   - además, los que tengan `first_observed_at` desde `--since`;
   - excluir los que ya tienen `menu_count > 0`, salvo `--refresh`.

`first_observed_at` será una columna nueva de SQLite: se setea una sola vez, cuando el local entra por primera vez a la base, y no se sobreescribe. No se usa `first_seen`, porque hoy ese campo copia `saved_on` de Google y no representa cuándo lo vimos nosotros.

La opción por defecto será `--since` = hace 7 días, para cubrir el caso “los agregué ayer” aunque el baseline falle.

### 8.2 Descubrir links del local

Si no hay URL de carta conocida:

- abrir la ficha de Google Maps;
- capturar web, “Carta”, “Pedir en línea” y proveedores (Fudo, Apparta, Rappi, PedidosYa, UberEats);
- guardar en `data/place_links.json`.

Esto reutiliza la lógica de `scripts/scan_maps_links.py`, pero como módulo.

### 8.3 Probar adaptadores

Orden:

1. **Fudo** — host `menu.fu.do`; `maps_gluten.fudo.fetch_menu`.
2. **Apparta/Tu Mesa** — host `menu.tu-mesa.com` o `api.apparta.co`; API `establishment-menu-items`.
3. **WooCommerce** — `/wp-json/wc/store/products`.
4. **Shopify** — `products.json`; si 429, UCP MCP; si no, sitemap + JSON-LD con Playwright.
5. **JSON-LD genérico** — reutiliza `crawl_web_products.page_products`.
6. **Web renderizada** — reutiliza `enrich._render_site_products`.
7. **Fotos** — UnitBytes + OCR/Gemini, solo si no hubo ítems y hay `APIFY_TOKEN`.

Se detiene en el primer adaptador que devuelva al menos un ítem. Si ninguno devuelve nada, el local queda `needs_manual`.

### 8.4 Escribir datos

Para cada local target:

- guardar un snapshot de sus filas previas en `reports/new_places_backup.jsonl` si ya tenía carta;
- borrar sus filas previas de `_menus.jsonl`, `menus_review.jsonl` y `menus_rejected.jsonl`;
- agregar las filas nuevas con `source` del adaptador;
- no tocar los demás locales;
- si el adaptador falla, no borrar nada.

Después de normalizar, el orquestador corre en modo `--finalize`:

- lee cuántos ítems publicables quedaron por local;
- si un local tenía carta previa y quedó con **0 publicables**, restaura el snapshot y lo marca `needs_manual` (no se pierde la carta anterior);
- si quedó con menos del 50% de lo que tenía y menos de 5 ítems, lo marca `needs_manual` pero no restaura automáticamente (requiere revisión);
- actualiza el reporte con el estado final.

Después:

```bash
python scripts/normalize_menus.py ...
python scripts/apply_normalization.py ...
python scripts/update_new_places.py --finalize ...
python scripts/rebuild_markdown.py --publish
```

## 9. Detalle de adaptadores

### Fudo

- Detección: URL contiene `menu.fu.do`.
- Extracción: `fetch_menu(url)`.
- URL: `data/menu_urls.json` o link descubierto en Maps.

### Apparta / Tu Mesa

- Detección: URL contiene `menu.tu-mesa.com` o `api.apparta.co`.
- Parseo del branch id desde `/slug/<id>/menu`.
- GET `https://api.apparta.co/establishment-menu-items` con:
  - `$client[source]=menuWeb`
  - `$client[establishment_branch_id]=<id>`
  - `$client[establishment_slug]=<slug>`
- Cada ítem puede tener `prices_list` con variantes de tamaño o marca. Se genera un ítem por variante: `Nombre - 350 cc`, `Gin - Hendrick's`.
- Labels (`Sin Gluten`, `Vegano`, etc.) se agregan a la descripción para que el normalizador las detecte.

### Rappi

- Detección: `order_urls` con un link `rappi.cl/restaurantes/...`.
- Extracción: GET de la página y parseo del JSON-LD `Restaurant` → `hasMenu` → secciones e ítems.
- Precio desde `offers.price`; categoría desde `MenuSection.name`.
- Es el mismo mecanismo que se usó a mano para Gusto's.

### WooCommerce

- Detección: `GET /wp-json/wc/store/products?per_page=1` responde JSON de lista.
- Extracción paginada con `per_page=100`; precios en unidades menores según `currency_minor_unit`.
- Categorías desde `categories[0].name`.

### Shopify

- Intento 1: `GET /products.json?limit=250&page=N`.
- Si 429/403:
  - leer `/.well-known/ucp`;
  - usar el endpoint MCP `search_catalog` con paginación;
  - si el MCP devuelve vacío, usar `sitemap_products_*.xml` + Playwright por ficha;
  - parsear JSON-LD `Product`/`ProductGroup` y `offers`/`hasVariant`.
- Si una ficha no tiene JSON-LD, usar el precio visible del DOM y marcar el ítem con `source=web-render` (no como `shopify`), para que pase por el quality gate como extracción débil.

### JSON-LD genérico

- Reutiliza `crawl_web_products.page_products`.
- Máximo configurable de productos por local (por defecto 100).

### Web renderizada

- Reutiliza `enrich._render_site_products`.
- Solo nombres y precios si aparecen; el quality gate decide qué publicar.

### Fotos

- Reutiliza `photos.enrich_menus_photos`.
- Solo como último recurso.
- Si no hay `APIFY_TOKEN`, se omite y se marca `needs_manual`.

### Maps links

- Abre la ficha con Playwright.
- Captura `website`, links externos, botón “Carta” y popup de “Pedir en línea”.
- Persiste en `data/place_links.json` para no repetir la visita.

## 10. Contrato de datos

`data/mis_lugares_sin_gluten_menus.jsonl` conserva el esquema actual:

```json
{
  "place_id": "0x...",
  "place": "Nombre",
  "address": "Dirección",
  "name": "Producto",
  "price": "$4.500",
  "category": "Categoría",
  "description": "Descripción o etiquetas",
  "source": "apparta",
  "url": "https://..."
}
```

Fuentes nuevas: `apparta`, `web-jsonld`, `web-render`.

`normalize_menus.py` tratará como fuentes de tienda/carta estructurada a `fudo`, `apparta`, `rappi`, `woocommerce`, `shopify` y `web-jsonld`. `web-render` queda como fuente débil y no recibe la indulgencia de nombres largos.

Para que el `source` no se pierda en la siguiente corrida, `store.write_menus_jsonl` incluirá `source`, `status`, `kind`, `dietary_tags` y `price_display` al reconstruir `_menus.jsonl` desde SQLite. `normalize_menus` ya lee `source`; solo hay que conservarlo.

`data/place_links.json` se indexa por `ftid` (estable), no por nombre:

```json
{
  "0x9691ca6855b98a79:0x8715ffa5cbdffed6": {
    "name": "Bar El Bajo",
    "website": "http://www.barelbajo.cl/",
    "menu": "https://menu.tu-mesa.com/bar-el-bajo/7689/menu",
    "order": [
      {"provider": "Apparta", "url": "https://menu.tu-mesa.com/..."}
    ]
  }
}
```

`data/menu_urls.json` se mantiene como espejo de compatibilidad para Fudo: si se descubre una URL `menu.fu.do`, se escribe en ambos archivos. La fuente de verdad es `place_links.json`; la normalización no necesita consultarlo porque el `source` viaja en cada fila.

## 11. Workflow `update-new.yml`

`workflow_dispatch` con:

- `since`: fecha ISO, por defecto hace 7 días.
- `places`: nombres separados por coma, opcional.
- `dry_run`: booleano, por defecto `false`.
- `photos`: booleano, por defecto `true`.
- `refresh`: booleano, por defecto `false`.

Pasos:

1. checkout, Python, dependencias, Playwright, cache del SQLite.
2. baseline de `ftid` existentes.
3. `python -m maps_gluten run --no-enrich` con `MAPS_ENRICH=0`, `MAPS_APIFY=0`.
4. `python scripts/update_new_places.py --since ... [--places ...] [--dry-run]`.
5. normalizar y aplicar.
6. `python scripts/update_new_places.py --finalize` para restaurar cartas vaciadas y cerrar el reporte.
7. reconstruir y publicar (salvo dry-run).
8. commit de `data/` y reporte como artefacto.
9. guardar cache del SQLite.

## 12. Manejo de fallos

- Cada local se procesa en su propio `try/except`; un fallo no corta el resto.
- Estados del reporte: `ok`, `empty`, `needs_manual`, `error`.
- Si un adaptador falla, se prueba el siguiente.
- Si todos fallan, el local se marca `needs_manual` y no se borra su carta anterior.
- El workflow termina en 0 aunque haya `needs_manual`; el reporte es la señal.
- Rate limits: backoff exponencial simple y pausas entre requests.

### Reporte final

`reports/new_places_<fecha>.jsonl` se escribe en dos fases:

1. extracción: `place`, `ftid`, `platform`, `extraction_status`, `extracted_count`, `urls`, `error`;
2. finalize: agrega `publishable_count`, `review_count`, `rejected_count` y `status` final.

Un local con extracción `ok` pero **0 publicables** después del quality gate se marca `needs_manual`, no `ok`.

### Dry-run

`--dry-run` permite lecturas de red (Maps, webs, APIs) pero:

- no escribe JSONL, SQLite, `place_links.json`, reportes ni Doc;
- no llama a Apify ni Gemini;
- imprime el resumen por stdout.

Así se puede probar un local sin gastar cuota ni ensuciar datos.

## 13. Verificación

- Fixtures pequeños para los parsers:
  - Apparta: respuesta de Bar El Bajo.
  - Shopify: producto JSON-LD y respuesta MCP.
  - WooCommerce: respuesta de Biomercado.
  - Fudo: respuesta de SERSAYAAN.
- `--dry-run` contra 3 locales conocidos (Bar El Bajo, BuganVilla, Biomercado).
- Corrida real contra los locales nuevos de Viña; revisar `reports/new_places_<fecha>.jsonl`.
- `python -m py_compile` de los módulos nuevos.
- No se agrega suite completa de tests; el usuario prioriza datos claros sobre tests.

## 14. Riesgos

- Shopify puede seguir bloqueando; el fallback MCP/sitemap/browser es obligatorio.
- El DOM de Google Maps puede cambiar; el descubrimiento de links debe fallar suave.
- Los catálogos grandes aumentan el tamaño del Doc; se puede limitar con `--max-items`.
- Sitios 100% personalizados seguirán necesitando trabajo manual; el reporte los aísla.

## 15. Decisiones tomadas en la revisión

- **No se borra una carta previa si la extracción nueva queda en 0 publicables.** Se restaura el snapshot y se marca `needs_manual`.
- **El reporte se cierra después de normalizar**, no antes; un `ok` de extracción no basta.
- **El `source` se conserva en SQLite y en `_menus.jsonl`** para que la siguiente corrida no lo reclasifique como `photo`.
- **`place_links.json` se indexa por `ftid`**; `menu_urls.json` queda como espejo de Fudo.
- **`first_observed_at` es la vara para “nuevo”**, no `first_seen`/`saved_on`.
- **`web-render` es fuente débil**; `apparta`, `shopify`, `woocommerce`, `fudo` y `web-jsonld` son fuentes estructuradas.
- **`--dry-run` no escribe nada ni gasta Apify/Gemini.**

## 16. Rollout

1. Implementar adaptadores y orquestador.
2. Probar con fixtures y dry-run.
3. Agregar workflow y documentación en README.
4. Correr con los locales nuevos de Viña.
5. Revisar el reporte y publicar.
6. Dejar los scripts manuales existentes como respaldo.

# maps-gluten-rag

Extrae los lugares de una lista compartida de Google Maps, elimina duplicados y genera dos archivos listos para una base de conocimiento (RAG):

- `data/mis_lugares_sin_gluten.md` — un bloque `##` por local, ideal para NotebookLM o cualquier índice semántico.
- `data/mis_lugares_sin_gluten.jsonl` — una línea JSON por local, con `text` y `metadata`, ideal para embeddings.
- `data/mis_lugares_sin_gluten_menus.jsonl` — una línea por plato (nombre, precio, categoría, ingredientes, alérgenos y nutrición) cuando Apify está configurado.

La fuente de verdad local es `data/historial_lugares.db` (SQLite). En GitHub Actions ese archivo vive en la caché del workflow, no en el repo. Cada corrida hace *upsert*: conserva la fecha de guardado de Google (`saved_on`) y solo marca como nuevos los lugares que no existían.

El extractor abre la lista pública con Playwright y lee el endpoint interno `entitylist/getlist`, que devuelve todos los lugares con nombre, dirección, coordenadas, `ftid` y fecha de guardado. Después recorre las filas del DOM para enriquecer con la valoración y la categoría, que ese endpoint no incluye. Si el endpoint cambia, cae a un respaldo que lee directamente las filas.

## Dos formas de ejecutarlo

| | GitHub Actions | Local |
| --- | --- | --- |
| Instalación | ninguna en tu Mac | Python + Playwright |
| Depende de tu equipo | no | Mac encendido |
| Costo | gratis (repo público) | gratis |
| Datos en | repo + Drive/URL raw | tu disco |

El resto de este documento asume GitHub Actions, que es lo que pediste.

## GitHub Actions

1. Crea el repositorio y sube el proyecto (el workflow corre a las 03:00 de Bogotá).
2. En *Settings → Actions → General*, deja habilitado *Read and write permissions* si tu organización lo restringe.
3. Opcional: en *Settings → Secrets and variables → Actions → Variables*, crea `MAPS_LIST_URL` con tu enlace. Si no la creas, se usa la URL incluida en el workflow.
4. Dispara la primera corrida desde *Actions → Actualizar lista de Google Maps → Run workflow*.

Qué hace el workflow (`.github/workflows/scrape.yml`):

- instala Python 3.12, las dependencias y Chromium;
- ejecuta `python -m maps_gluten run`;
- enriquece con la web de cada local y con los temas de sus reseñas (si `MAPS_ENRICH=1`);
- consulta Apify para la carta estructurada si `APIFY_TOKEN` está configurado;
- hace commit de `data/*.md` y `data/*.jsonl` si cambió algo;
- guarda `data/historial_lugares.db` en la caché de Actions para mantener el dedup entre corridas (el archivo está en `.gitignore`);
- copia el resultado a un Google Doc si `GDOC_ID` está configurado;
- publica el `.md`, el `.jsonl` y `_menus.jsonl` como artefacto descargable;
- corre todos los lunes a las **13:00 de Chile**. Programa dos crons (16:00 y 17:00 UTC) y un paso comprueba la hora local, así sigue siendo la 1 pm cuando cambia el horario de verano.
- usa `America/Santiago` y `es-CL` para fechas y textos.

El cron de GitHub puede retrasarse unos minutos cuando hay carga. No requiere tu Mac encendido. Si agregas lugares antes del lunes, dispara el workflow a mano desde *Actions → Run workflow*.

### Google Doc para NotebookLM (recomendado)

El workflow copia el resultado a un Google Doc tuyo. NotebookLM acepta ese Doc como fuente y trae un botón de sincronizar, así que no dependes de una URL raw.

Configúralo una vez:

1. Crea un Google Doc vacío y copia su ID de la URL (`https://docs.google.com/document/d/<ID>/edit`).
2. En Google Cloud crea un proyecto y habilita **Google Docs API**.
3. Crea una **cuenta de servicio** (IAM → Cuentas de servicio), sin roles. Genera una clave JSON y descárgala.
4. Comparte el Doc con el email de la cuenta de servicio (`...@....iam.gserviceaccount.com`) como **Editor**.
5. En GitHub → *Settings → Secrets and variables → Actions*:
   - secreto `GOOGLE_SA_JSON`: el contenido completo del JSON.
   - variable `GDOC_ID`: el ID del Doc.
6. Corre el workflow. El paso *Publicar en Google Doc* rellena el Doc.
7. En NotebookLM agrega el Doc desde Google Drive. Cuando quieras la versión nueva, pulsa **Sincronizar** en la fuente.

La cuenta de servicio solo puede tocar ese Doc porque se lo compartiste explícitamente. Si prefieres no configurar todo esto, la URL raw del repo sigue funcionando como fuente de NotebookLM:

```
https://raw.githubusercontent.com/OswaldoRodriguez123/maps-gluten-rag/main/data/mis_lugares_sin_gluten.md
```

## Enriquecido con web y reseñas

La lista de Google no dice qué vende cada local. Para acercarse, el script abre la ficha de cada lugar en Maps, toma su sitio web y busca platos en el texto de la web (y en una página de menú o PDF si existe). Además lee los **temas que Google extrae de las reseñas** (por ejemplo “empanadas 19”, “dulces 17”, “hamburguesas 12”) y el texto de las opiniones. Luego agrega al Doc:

```
- **Web:** https://www.quimeysushi.cl/
- **Menciona en su web:** hamburguesa, pizza, sushi, pasta, gyosa
- **Menciona en reseñas:** hamburguesa, empanada, completo, chilenito, dulces, jugo
```

El léxico incluye platos, dulces y productos: hamburguesa, pizza, sushi, pasta, empanada, completo, torta, pastel, galleta, alfajor, brownie, cupcake, donut, cheesecake, helado, chocolate, churro, flan, budín, chilenito, medialuna, factura, croissant, postre, jugo, etc.

Es una **mención**, no una garantía: puede venir de una reseña o de una sección del sitio, y no cubre cartas que están solo en imágenes. En esta lista, 67 de 100 locales tienen web y 37 mostraban platos desde la web.

- Las reseñas y los temas solo cargan en la ficha con **ventana**; por eso el workflow usa `xvfb` y `MAPS_HEADLESS=0`. En local, ejecuta con `--no-headless`.
- Caché: 30 días (`MAPS_ENRICH_DAYS`) más una versión interna que fuerza una re-extracción cuando cambia el enriquecido.
- La primera corrida tarda ~15–25 minutos; las siguientes no repiten las fichas.
- Desactivar: `MAPS_ENRICH=0` o `--no-enrich`.
- Forzar: `--refresh-enrichment`.

### Búsqueda de web cuando Maps no la trae (DuckDuckGo + Gemini)

Si la ficha de Maps no trae web (`_extract_website` / `discover_links` vacíos), el pipeline la busca solo — sin que la pongas a mano:

- Query `"<nombre>" sin gluten <comuna/dirección>` a DuckDuckGo HTML (solo stdlib `urllib`, sin API paga ni navegador extra), top 5, descartando sociales/agregadores (Instagram, Facebook, TikTok, Tripadvisor, Uber Eats, Rappi, PedidosYa).
- Gemini (`GEMINI_API_KEY`, el mismo secret de visión; sin clave no se acepta nada) valida nombre + overlap de dirección. Solo acepta match fuerte: `score >= 0.85` y URL que esté entre los candidatos (una URL inventada por el LLM o un homónimo se rechaza siempre).
- Si acepta, la web se trata igual que la de Maps (`_site_dishes`, adaptadores Fudo/Shopify/etc., fotos como respaldo) y queda constancia de origen: `website_source='search'` en SQLite y en `metadata.website_source` del JSONL (`'maps'` cuando viene de Maps).
- Aplica al enriquecido de `run` y al fallback de `update_new_places` tras `discover_links`. Si el buscador bloquea (403) o hay cuota (429), o no hay match fuerte, degrada en silencio y el local sigue como hoy (`needs_manual`): una web equivocada es peor que ninguna, nunca se inventa la URL.
- Control: `MAPS_WEBSITE_SEARCH=1` por defecto; `MAPS_WEBSITE_SEARCH=0` o `python -m maps_gluten run --no-website-search` lo apaga; `--website-search` lo fuerza aunque el env esté en 0 (el flag gana, si no se usa el env). Rate limit suave (0.5 s entre búsquedas).

### OCR de cartas escaneadas

Con `MAPS_OCR=1` (activo en el workflow):

- Los **PDF** se leen primero con `pypdf`. Si no tienen texto (escaneados), se renderizan con `pypdfium2` y se pasan por Tesseract (`spa+eng`).
- En las webs, si la página de menú no tiene texto suficiente, se descargan hasta 3 imágenes candidatas (sin logos ni iconos) y se les aplica OCR.
- En GitHub Actions se instala `tesseract-ocr` y `tesseract-ocr-spa`. En local: `brew install tesseract tesseract-lang` o el paquete equivalente.

Límites: la calidad depende de la foto; cartas con letra muy pequeña, inclinadas, en columnas o con fondo complejo pueden fallar. El OCR en alta resolución sí funciona sobre las fotos etiquetadas como `menu` que devuelve UnitBytes; aun así puede meter fragmentos o perder precios.

### Carta desde las fotos de Google Maps (UnitBytes + OCR)

Estado 2026-11-05: UnitBytes + OCR en alta resolución extrajo **3.121 platos de 54 locales**. Sumados a los **916 platos de 14 locales** recuperados de los datasets de Nomad, el Doc tiene **4.037 platos en 62 locales**. Los otros 38 no tienen fotos de menú y quedan con reseñas/web.

Cómo funciona:

- El actor `unitbytes/google-maps-photos-scraper` con `category: menu` devuelve las fotos de la pestaña Carta (hasta 8 por local).
- Se descargan en **alta resolución**, se convierten a gris, se upscalean/downscalean a ~1.800–2.600 px, se les aplica autocontraste y se OCR con Tesseract `spa+eng` y `psm 6/11`.
- Se parsean platos y precios; el resultado va al Doc como `- **Carta (Google Maps):** ...`, a `metadata.menu` y a `menus.jsonl`.
- Costo: ~$0.00025 por foto; 263 fotos ≈ **$0.07**, dentro de los $5 gratis de Apify.
- Caché 30 días (`menu_at`). `MAPS_MENU_ACTOR=unitbytes` y `MAPS_WEBSITE_MENU=0`.
- Las URLs de las fotos se guardan en SQLite (`menu_photos_json`) y también se reutilizan las últimas corridas exitosas de UnitBytes, así que actualizar otra vez el mismo local no vuelve a raspar.

#### Respaldo con visión (Gemini)

Si el OCR de un local devuelve menos de 2 platos, se manda la foto a Gemini (visión) y se agrega lo que lea. Es automático y cubre cartas manuscritas o con letra difícil, como el pizarrón de Yoko Sea Food.

- Usa `GEMINI_API_KEY` (gratis en Google AI Studio) y `MAPS_VISION=1`.
- Orden de modelos: `gemini-flash-lite-latest` (el más barato) → `gemini-3.5-flash` → `gemini-3.6-flash`. Si un modelo responde **503** (saturado) pasa al siguiente; si responde **429** (cuota) se detiene.
- Límite: `MAPS_VISION_PLACES` (12 por corrida) y `MAPS_VISION_PHOTOS` (3 fotos por local).
- Se puede fijar un modelo con `GEMINI_VISION_MODEL=gemini-3.6-flash`.
- Si la visión encuentra 2+ platos, descarta los fragmentos de OCR sin precio.

Se activa con el secreto `APIFY_TOKEN`:

1. Crea una cuenta gratis en https://console.apify.com/sign-up (sin tarjeta; incluye **$5 de uso al mes**).
2. Copia tu API token en *Settings → Integrations*.
3. En GitHub → *Settings → Secrets and variables → Actions*, crea el secreto `APIFY_TOKEN` con ese valor.
4. Dispara el workflow. La primera corrida procesa todos los locales; después se refresca cuando `menu_at` tenga más de `MAPS_ENRICH_DAYS` días (30).

Salidas:

- `### Carta` en el `.md` y en el Doc, con `#### Categoría` y un plato por línea (`- Plato — $precio`).
- `metadata.menu` en el JSONL principal.
- `data/mis_lugares_sin_gluten_menus.jsonl`: una fila por plato, con categoría y precio.

El OCR puede meter fragmentos y los precios pueden faltar; es una mención, no una carta certificada. Verifica alérgenos y precios con el local.

`MAPS_MENU_ACTOR` acepta `unitbytes` (por defecto), `none` (desactivado) o `nomad` (actor gestionado/BYO). `MAPS_WEBSITE_MENU=1` mantiene el scan de menús en webs; está en `0` porque UnitBytes ya cubre las fotos de Maps.

### Actualizar un solo local

Para probar o corregir un local sin listar los 100 ni usar Apify:

```bash
gh workflow run update-one.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag \
  -f place=Crumbless
```

El workflow restaura la caché, actualiza **solo** ese local, publica el Google Doc, guarda la caché y hace commit. No toca los otros 99 ni los menús ya extraídos.

Funciona con webs normales y con tiendas SPA:

- Primero intenta el parseo HTTP normal (`_site_dishes`).
- Si no hay texto, renderiza la página con Playwright y extrae productos por **JSON-LD**, anclas con precio/palabra de plato y rutas de producto (`/product`, `/shop`, `/menu`, `/tienda`, etc.).
- No depende de `menu.fu.do`; ese host solo queda como atajo de rendimiento para la corrida masiva.

También se puede ejecutar en local:

```bash
GOOGLE_APPLICATION_CREDENTIALS='/ruta/service-account.json' \
GDOC_ID='1N67XQI2sXARoeZe6wz87JlmH-a5Z83exgBiz9Q_j1H0' \
.venv/bin/python scripts/update_place.py --place Crumbless --publish
```

### Actualizar solo locales nuevos

Cuando agregues locales a la lista, no hace falta reprocesar los 100. El workflow `update-new.yml`:

1. guarda un baseline de los locales que ya existían;
2. refresca la lista sin enriquecer todos;
3. selecciona solo los nuevos (o los que tengan `first_observed_at` desde la fecha indicada);
4. prueba adaptadores por plataforma: Fudo, Apparta/Tu Mesa, Rappi, WooCommerce, Shopify, JSON-LD, web renderizada y fotos;
5. normaliza, publica y deja un reporte.

Antes de refrescar la lista, el workflow sincroniza SQLite desde los JSONL del repo. Así un cache viejo de Actions no puede borrar cartas ya publicadas.

```bash
gh workflow run update-new.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag \
  -f since=2026-11-05 \
  -f places='' \
  -f photos=true
```

Inputs:

- `since`: fecha ISO. Si se omite, usa hace 7 días.
- `places`: nombres separados por coma. Si se omite, usa el baseline + fecha.
- `dry_run`: prueba sin escribir datos ni publicar.
- `photos`: usar fotos de Google Maps como último recurso.
- `refresh`: reprocesar locales que ya tienen carta.

El resultado queda en `reports/new_places_<fecha>.jsonl`. Los locales que no se pudieron resolver aparecen como `needs_manual`; esos son los únicos que conviene revisar a mano.

Dry-run local:

```bash
.venv/bin/python scripts/update_new_places.py \
  --places 'Bar El Bajo' --refresh --no-photos --dry-run
```

### Actualizar la carta de un solo local

Para releer las fotos de menú de un local (sin tocar el resto), usa:

```bash
gh workflow run update-menu-one.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag \
  -f place=Yoko
```

- Usa la caché de fotos de SQLite; si no existe, reutiliza la última corrida de UnitBytes o raspa solo ese local.
- Por defecto usa **visión Gemini** (flash-lite, el modelo más barato) y **omite Tesseract**, así que no instala paquetes del sistema.
- `-f ocr=true` activa Tesseract como respaldo (más lento).
- `-f refresh=true` ignora la caché de fotos y vuelve a raspar.
- Publica el Doc y hace commit de `data/`.

En local:

```bash
APIFY_TOKEN='...' GEMINI_API_KEY='...' \
GDOC_ID='1N67XQI2sXARoeZe6wz87JlmH-a5Z83exgBiz9Q_j1H0' \
GOOGLE_APPLICATION_CREDENTIALS='/ruta/service-account.json' \
.venv/bin/python scripts/update_menu_place.py --place Yoko --publish
```

### Carta desde una tienda Fudo (menu.fu.do)

Si Google Maps muestra `menu.fu.do` en la pestaña Carta, guarda la URL en `data/menu_urls.json`:

```json
{
  "Café Aquelarre": "https://menu.fu.do/cafeaquelarre"
}
```

Y actualiza solo esa carta:

```bash
gh workflow run update-fudo-one.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag \
  -f place='Café Aquelarre'
```

También acepta `-f menu_url='https://menu.fu.do/...'` si no está en el archivo. El extractor lee el catálogo completo (productos, categorías y precios) aunque la tienda esté cerrada; “cerrado” solo bloquea pedidos.

### Formato del Doc y reconstrucción

El Doc es la fuente para NotebookLM:

- Cada local es un `##`.
- `### Qué vende`: categorías del local (Sandwiches, Empanadas, Pizzas...), aunque no tengan precio.
- `- **Dietético:**`: si el local es 100% sin gluten, o cuántos platos son sin gluten/veganos/sin lactosa.
- `### Carta`: platos con precio, agrupados por `#### Categoría`, con etiquetas `[sin gluten]`, `[vegano]`, `[sin lactosa]` cuando corresponden.
- NotebookLM permite 500.000 palabras por fuente y 50 fuentes por cuaderno; el Doc completo usa ~35.000 palabras.

### Normalización y etiquetas (P0)

Antes de publicar, el pipeline separa lo publicable de lo dudoso:

- `scripts/normalize_menus.py`: limpia nombres, separa descripciones, normaliza precios (CLP/EUR), deduplica, asigna categorías y etiquetas dietéticas.
- `scripts/apply_normalization.py`: aplica el resultado al JSONL, al `_menus.jsonl` y a SQLite.
- `scripts/rebuild_markdown.py`: regenera el Doc con `### Qué vende` + `### Carta`.
- `menus_review.jsonl` y `menus_rejected.jsonl`: ítems que no se publican y quedan para reextraer.

Comandos:

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

La visión Gemini corre con concurrencia limitada por `MAPS_VISION_CONCURRENCY` (por defecto `2`) y la carga de datasets recientes usa hasta 4 hilos. Ajusta ese valor si tu cuota aguanta más.

Para reconstruir el Doc desde los JSONL sin volver a listar los 100:

```bash
gh workflow run rebuild-doc.yml \
  --repo OswaldoRodriguez123/maps-gluten-rag
```

## Local (opcional)

```bash
cd ~/repos/maps-gluten-rag
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
cp .env.example .env        # pon MAPS_LIST_URL
./run_daily.sh
```

Para programarlo a las 03:00 en macOS:

```bash
./scripts/install_launchd.sh
```

En Linux: `0 3 * * * cd /ruta/maps-gluten-rag && ./run_daily.sh >> logs/cron.log 2>&1`.

### Opciones útiles

```bash
--url URL              # sobrescribe MAPS_LIST_URL
--out DIR              # carpeta de salida
--basename NOMBRE      # nombre de los archivos
--no-headless          # abre ventana (útil si Google bloquea headless)
--channel chrome|msedge|""   # navegador real o el de Playwright
--debug                # guarda HTML y respuestas de red
```

## Listas privadas

El workflow de GitHub solo puede leer listas públicas. Si tu lista deja de estar compartida, el script falla sin tocar la base y lo dice en el log. Para listas privadas hay que ejecutar en local con `python -m maps_gluten login`, que guarda un perfil de Chromium en `.auth/`; ese perfil no debe subirse a GitHub.

## Estructura

```
maps-gluten-rag/
├── .github/workflows/scrape.yml
├── maps_gluten/
│   ├── extract.py      # endpoint de la lista + respaldo DOM
│   ├── enrich.py       # web, reseñas y OCR
│   ├── apify.py        # carta estructurada (opcional)
│   ├── store.py        # SQLite, deduplicación y salidas .md / .jsonl
│   └── cli.py          # comandos `login`, `run` y `publish`
├── scripts/
│   ├── install_launchd.sh
│   └── sync_drive.sh
├── launchd/com.mapsgluten.scraper.plist.template
├── run_daily.sh
├── .env.example
└── requirements.txt
```

## Límites que conviene tener claros

- `entitylist/getlist` es un endpoint interno, no una API pública. Puede cambiar sin aviso; el respaldo DOM y `--debug` existen para eso.
- La valoración y la categoría no vienen en el payload de la lista: se toman de las filas del DOM. Google no las muestra para algunos locales, así que esos quedan sin valoración o sin categoría.
- Los platos se detectan por palabras clave en la web, en PDFs, en imágenes de menú con OCR y en las reseñas del local. No es un menú estructurado: puede haber falsos positivos y faltan los locales sin web ni reseñas.
- La carta de Apify es una estimación de IA: los alérgenos y la nutrición pueden estar mal. Verifica con el local antes de usarlos para decisiones de salud.
- Revisa los términos de uso de Google Maps antes de automatizarlo a diario. Para un uso personal y de bajo volumen es lo habitual; no lo uses como servicio para terceros.
- Si la lista es privada y Google invalida la sesión, `run` falla sin tocar la base y te lo dice en el log. Vuelve a ejecutar `login`.

# maps-gluten-rag

Extrae los lugares de una lista compartida de Google Maps, elimina duplicados y genera dos archivos listos para una base de conocimiento (RAG):

- `data/mis_lugares_sin_gluten.md` — un bloque `##` por local, ideal para NotebookLM o cualquier índice semántico.
- `data/mis_lugares_sin_gluten.jsonl` — una línea JSON por local, con `text` y `metadata`, ideal para embeddings.

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
- hace commit de `data/*.md` y `data/*.jsonl` si cambió algo;
- guarda `data/historial_lugares.db` en la caché de Actions para mantener el dedup entre corridas (el archivo está en `.gitignore`);
- publica el `.md` y el `.jsonl` como artefacto descargable;
- corre todos los días a las 08:00 UTC (03:00 en Colombia).

El cron de GitHub puede retrasarse unos minutos cuando hay carga. No requiere tu Mac encendido.

### Consumirlo desde el teléfono

Si el repo es **público**, la URL raw es una fuente de texto perfecta para NotebookLM:

```
https://raw.githubusercontent.com/OswaldoRodriguez123/maps-gluten-rag/main/data/mis_lugares_sin_gluten.md
```

En la app de NotebookLM (Android) crea un cuaderno, elige *Agregar fuente → Sitio web* y pega esa URL. También puedes descargar el `.md` desde el artefacto y subirlo como archivo. NotebookLM toma una instantánea: cuando la lista cambie, vuelve a sincronizar o agrega la fuente de nuevo.

Si el repo es **privado**, la URL raw no sirve sin credenciales. En ese caso hay que subir el archivo a Google Drive (por ejemplo con `rclone` y una cuenta de servicio) y agregarlo desde Drive.

Si tu versión de NotebookLM no acepta `.md`, sube el mismo contenido con extensión `.txt`.

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
│   ├── store.py        # SQLite, deduplicación y salidas .md / .jsonl
│   └── cli.py          # comandos `login` y `run`
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
- Revisa los términos de uso de Google Maps antes de automatizarlo a diario. Para un uso personal y de bajo volumen es lo habitual; no lo uses como servicio para terceros.
- Si la lista es privada y Google invalida la sesión, `run` falla sin tocar la base y te lo dice en el log. Vuelve a ejecutar `login`.

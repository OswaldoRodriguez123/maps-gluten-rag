from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import extract, store


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m maps_gluten",
        description="Extrae los lugares de una lista de Google Maps a Markdown y JSONL.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="Abre un navegador para iniciar sesión en Google una vez.")
    login.add_argument("--profile", help="Carpeta del perfil persistente (por defecto MAPS_PROFILE_DIR o .auth).")
    login.add_argument("--channel", help="Canal de Chromium (chrome, msedge). Vacío usa el navegador de Playwright.")
    login.add_argument("--locale", default=os.getenv("MAPS_LOCALE", "es-CO"))
    login.add_argument("--timezone", default=os.getenv("MAPS_TIMEZONE", "America/Bogota"))

    run = sub.add_parser("run", help="Extrae la lista y actualiza la base local.")
    run.add_argument("--url", help="URL de la lista (por defecto MAPS_LIST_URL).")
    run.add_argument("--out", help="Carpeta de salida (por defecto MAPS_OUT_DIR o data).")
    run.add_argument("--basename", help="Nombre base de los archivos (por defecto MAPS_OUT_BASENAME).")
    run.add_argument("--db", help="Ruta de la base SQLite (por defecto <out>/historial_lugares.db).")
    run.add_argument("--profile", help="Carpeta del perfil persistente.")
    run.add_argument("--channel", help="Canal de Chromium (chrome, msedge). Vacío usa el de Playwright.")
    run.add_argument("--locale", default=os.getenv("MAPS_LOCALE", "es-CO"))
    run.add_argument("--timezone", default=os.getenv("MAPS_TIMEZONE", "America/Bogota"))
    run.add_argument("--debug", action="store_true", help="Guarda HTML y respuestas de red en <out>/debug.")
    run.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Ejecutar el navegador sin ventana (por defecto MAPS_HEADLESS o sí).",
    )
    run.add_argument(
        "--enrich",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Buscar la web del local y mencionar platos (por defecto MAPS_ENRICH o sí).",
    )
    run.add_argument(
        "--enrich-days",
        type=int,
        default=None,
        help="Días de caché del enriquecido (por defecto MAPS_ENRICH_DAYS o 30).",
    )
    run.add_argument(
        "--refresh-enrichment",
        action="store_true",
        help="Ignora la caché y vuelve a enriquecer todos los locales.",
    )
    run.add_argument(
        "--refresh-place",
        action="append",
        default=[],
        help="Fuerza el enriquecido de los locales cuyo nombre contenga este texto (repetible).",
    )
    run.add_argument(
        "--ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="OCR en PDFs escaneados e imágenes de menú (por defecto MAPS_OCR o no).",
    )

    publish = sub.add_parser("publish", help="Copia el Markdown generado a un Google Doc.")
    publish.add_argument("--doc-id", help="ID del Google Doc (por defecto GDOC_ID).")
    publish.add_argument("--out", help="Carpeta de salida (por defecto MAPS_OUT_DIR o data).")
    publish.add_argument("--basename", help="Nombre base del archivo (por defecto MAPS_OUT_BASENAME).")
    return parser


def _resolve(value: str | None, env: str, fallback: str) -> str:
    return value or os.getenv(env) or fallback


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    profile = Path(_resolve(getattr(args, "profile", None), "MAPS_PROFILE_DIR", ".auth"))
    channel = getattr(args, "channel", None)
    if channel is None:
        channel = os.getenv("MAPS_BROWSER_CHANNEL", "chrome")
    channel = channel or None

    if args.command == "login":
        extract.login(profile, channel, args.locale, args.timezone)
        print(f"Perfil guardado en {profile.resolve()}")
        return 0

    if args.command == "publish":
        from . import gdocs

        doc_id = args.doc_id or os.getenv("GDOC_ID", "")
        if not doc_id:
            print("Falta GDOC_ID o --doc-id.", file=sys.stderr)
            return 2
        out_dir = Path(_resolve(args.out, "MAPS_OUT_DIR", "data"))
        basename = _resolve(args.basename, "MAPS_OUT_BASENAME", "mis_lugares_sin_gluten")
        path = out_dir / f"{basename}.md"
        if not path.exists():
            print(f"No existe {path}. Ejecuta `run` primero.", file=sys.stderr)
            return 1
        try:
            count = gdocs.update_document(doc_id, path.read_text(encoding="utf-8"))
        except Exception as error:
            print(f"Error al actualizar el Google Doc: {error}", file=sys.stderr)
            return 1
        print(f"Google Doc actualizado: {gdocs.document_url(doc_id)} ({count} bloques)")
        return 0

    url = _resolve(args.url, "MAPS_LIST_URL", "")
    if not url:
        print("Falta la URL de la lista. Define MAPS_LIST_URL o usa --url.", file=sys.stderr)
        return 2

    out_dir = Path(_resolve(args.out, "MAPS_OUT_DIR", "data"))
    basename = _resolve(args.basename, "MAPS_OUT_BASENAME", "mis_lugares_sin_gluten")
    db_path = Path(args.db) if args.db else out_dir / "historial_lugares.db"
    headless = args.headless if args.headless is not None else _env_bool("MAPS_HEADLESS", True)
    debug = args.debug or _env_bool("MAPS_DEBUG", False)
    enrich_enabled = args.enrich if args.enrich is not None else _env_bool("MAPS_ENRICH", True)
    ocr_enabled = args.ocr if args.ocr is not None else _env_bool("MAPS_OCR", False)
    vision_key = os.getenv("GEMINI_API_KEY", "").strip() or None
    vision_enabled = _env_bool("MAPS_VISION", bool(vision_key)) and bool(vision_key)
    try:
        vision_places = int(os.getenv("MAPS_VISION_PLACES", "12"))
    except ValueError:
        vision_places = 12
    try:
        vision_photos = int(os.getenv("MAPS_VISION_PHOTOS", "3"))
    except ValueError:
        vision_photos = 3
    apify_token = os.getenv("APIFY_TOKEN", "").strip()
    apify_enabled = _env_bool("MAPS_APIFY", True) and bool(apify_token)
    menu_actor = os.getenv("MAPS_MENU_ACTOR", "unitbytes").strip().lower()
    website_dishes = _env_bool("MAPS_WEBSITE_MENU", True)
    apify_language = os.getenv("APIFY_LANGUAGE", "es")
    try:
        apify_photos = int(os.getenv("APIFY_MAX_PHOTOS", "8"))
    except ValueError:
        apify_photos = 8
    try:
        apify_charge = float(os.getenv("APIFY_MAX_CHARGE_USD", "2.0"))
    except ValueError:
        apify_charge = 2.0
    try:
        apify_concurrency = int(os.getenv("APIFY_CONCURRENCY", "5"))
    except ValueError:
        apify_concurrency = 5
    try:
        enrich_days = args.enrich_days if args.enrich_days is not None else int(os.getenv("MAPS_ENRICH_DAYS", "30"))
    except ValueError:
        enrich_days = 30
    timezone = ZoneInfo(args.timezone)
    today = datetime.now(timezone).date().isoformat()

    conn = store.connect(db_path)
    try:
        cache = store.enrichment_cache(conn) if (enrich_enabled or apify_enabled) else {}
        if args.refresh_place:
            terms = [term.lower() for term in args.refresh_place]
            for row in conn.execute("SELECT ftid, name FROM places"):
                name = (row["name"] or "").lower()
                if any(term in name for term in terms):
                    cache.setdefault(row["ftid"], {})["enriched_at"] = None
        try:
            key, title, places, complete = extract.scrape_list(
                url=url,
                profile=profile,
                headless=headless,
                channel=channel,
                locale=args.locale,
                timezone=args.timezone,
                debug_dir=out_dir / "debug" if debug else None,
                enrich=enrich_enabled,
                enrich_cache=cache,
                enrich_days=enrich_days,
                enrich_force=args.refresh_enrichment,
                today=today,
                enrich_ocr=ocr_enabled,
                website_dishes=website_dishes,
            )
        except Exception as error:
            print(f"Error al extraer la lista: {error}", file=sys.stderr)
            return 1

        if not places:
            print("La lista no devolvió lugares. No se modificó la base.", file=sys.stderr)
            return 1

        if apify_enabled:
            today_date = date.fromisoformat(today)
            targets = []
            for place in places:
                info = cache.get(place.ftid) or {}
                menu_at = info.get("menu_at")
                if not menu_at:
                    targets.append(place)
                    continue
                try:
                    if (today_date - date.fromisoformat(menu_at)).days >= enrich_days:
                        targets.append(place)
                except ValueError:
                    targets.append(place)
            if targets and menu_actor != "none":
                try:
                    if menu_actor == "unitbytes":
                        from . import photos

                        count = photos.enrich_menus_photos(
                            targets,
                            apify_token,
                            max_photos=apify_photos,
                            max_charge_usd=apify_charge,
                            today=today,
                            vision_key=vision_key if vision_enabled else None,
                            vision_max_photos=vision_photos,
                            vision_max_places=vision_places,
                        )
                    else:
                        from . import apify

                        count = apify.enrich_menus(
                            targets,
                            apify_token,
                            language=apify_language,
                            max_photos=apify_photos,
                            max_charge_usd=apify_charge,
                            concurrency=apify_concurrency,
                            today=today,
                        )
                    print(f"Menú ({menu_actor}): {count} platos en {len(targets)} locales")
                except Exception as error:
                    print(f"Menú ({menu_actor}): {error}", file=sys.stderr)

        total, new = store.save(conn, key, title, places, today, replace=complete)
        md_path = out_dir / f"{basename}.md"
        jsonl_path = out_dir / f"{basename}.jsonl"
        menus_path = out_dir / f"{basename}_menus.jsonl"
        store.write_markdown(conn, key, md_path, today)
        store.write_jsonl(conn, key, jsonl_path)
        store.write_menus_jsonl(conn, key, menus_path)
    finally:
        conn.close()

    print(f"Lista: {title or key}")
    print(f"Encontrados: {len(places)} | En la base: {total} | Nuevos: {new}")
    print(f"Markdown: {md_path}")
    print(f"JSONL:    {jsonl_path}")
    print(f"Menús:    {menus_path}")
    return 0

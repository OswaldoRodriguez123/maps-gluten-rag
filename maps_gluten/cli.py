from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
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
    timezone = ZoneInfo(args.timezone)
    today = datetime.now(timezone).date().isoformat()

    try:
        key, title, places, complete = extract.scrape_list(
            url=url,
            profile=profile,
            headless=headless,
            channel=channel,
            locale=args.locale,
            timezone=args.timezone,
            debug_dir=out_dir / "debug" if debug else None,
        )
    except Exception as error:
        print(f"Error al extraer la lista: {error}", file=sys.stderr)
        return 1

    if not places:
        print("La lista no devolvió lugares. No se modificó la base.", file=sys.stderr)
        return 1

    conn = store.connect(db_path)
    try:
        total, new = store.save(conn, key, title, places, today, replace=complete)
        md_path = out_dir / f"{basename}.md"
        jsonl_path = out_dir / f"{basename}.jsonl"
        store.write_markdown(conn, key, md_path, today)
        store.write_jsonl(conn, key, jsonl_path)
    finally:
        conn.close()

    print(f"Lista: {title or key}")
    print(f"Encontrados: {len(places)} | En la base: {total} | Nuevos: {new}")
    print(f"Markdown: {md_path}")
    print(f"JSONL:    {jsonl_path}")
    return 0

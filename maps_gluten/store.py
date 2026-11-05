from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from .extract import Place
from .render import (
    categories_from_items,
    dietary_line,
    dietary_summary,
    menu_lines,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    ftid       TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    address    TEXT,
    category   TEXT,
    rating     TEXT,
    reviews    TEXT,
    note       TEXT,
    url        TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    saved_on   TEXT,
    lat        REAL,
    lng        REAL,
    website    TEXT,
    dishes     TEXT,
    review_dishes TEXT,
    enriched_at TEXT,
    enrich_version INTEGER,
    menu_dishes TEXT,
    menu_json   TEXT,
    menu_at     TEXT,
    menu_photos_json TEXT,
    menu_photos_at   TEXT
);

CREATE TABLE IF NOT EXISTS lists (
    list_key TEXT PRIMARY KEY,
    title    TEXT,
    last_run TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS list_places (
    list_key TEXT NOT NULL,
    ftid     TEXT NOT NULL,
    PRIMARY KEY (list_key, ftid)
);
"""

UPSERT = """
INSERT INTO places (
    ftid, name, address, category, rating, reviews, note, url,
    first_seen, last_seen, saved_on, lat, lng, website, dishes, review_dishes,
    enriched_at, enrich_version, menu_dishes, menu_json, menu_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(ftid) DO UPDATE SET
    name    = excluded.name,
    address = COALESCE(NULLIF(excluded.address, ''), places.address),
    category = COALESCE(NULLIF(excluded.category, ''), places.category),
    rating  = COALESCE(NULLIF(excluded.rating, ''), places.rating),
    reviews = COALESCE(NULLIF(excluded.reviews, ''), places.reviews),
    note    = COALESCE(NULLIF(excluded.note, ''), places.note),
    url     = excluded.url,
    last_seen = excluded.last_seen,
    first_seen = COALESCE(NULLIF(excluded.saved_on, ''), places.first_seen),
    saved_on = COALESCE(NULLIF(excluded.saved_on, ''), places.saved_on),
    lat      = COALESCE(excluded.lat, places.lat),
    lng      = COALESCE(excluded.lng, places.lng),
    website  = COALESCE(NULLIF(excluded.website, ''), places.website),
    dishes   = COALESCE(NULLIF(excluded.dishes, ''), places.dishes),
    review_dishes = COALESCE(NULLIF(excluded.review_dishes, ''), places.review_dishes),
    enriched_at = COALESCE(NULLIF(excluded.enriched_at, ''), places.enriched_at),
    enrich_version = COALESCE(excluded.enrich_version, places.enrich_version),
    menu_dishes = COALESCE(NULLIF(excluded.menu_dishes, ''), places.menu_dishes),
    menu_json   = COALESCE(NULLIF(excluded.menu_json, ''), places.menu_json),
    menu_at     = COALESCE(NULLIF(excluded.menu_at, ''), places.menu_at)
"""

MIGRATIONS = (
    ("saved_on", "TEXT"),
    ("lat", "REAL"),
    ("lng", "REAL"),
    ("website", "TEXT"),
    ("dishes", "TEXT"),
    ("review_dishes", "TEXT"),
    ("enriched_at", "TEXT"),
    ("enrich_version", "INTEGER"),
    ("menu_dishes", "TEXT"),
    ("menu_json", "TEXT"),
    ("menu_at", "TEXT"),
    ("menu_photos_json", "TEXT"),
    ("menu_photos_at", "TEXT"),
)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(places)")}
    for column, kind in MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE places ADD COLUMN {column} {kind}")
    return conn


def photo_cache(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """URLs de fotos de menú ya descargadas por UnitBytes, por local."""
    cached: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT ftid, menu_photos_json FROM places "
        "WHERE menu_photos_json IS NOT NULL AND menu_photos_json != ''"
    ):
        try:
            urls = json.loads(row["menu_photos_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(urls, list):
            values = [str(url) for url in urls if url]
            if values:
                cached[row["ftid"]] = values
    return cached


def save_photo_cache(
    conn: sqlite3.Connection, photos: dict[str, list[str]], today: str
) -> None:
    for ftid, urls in photos.items():
        if not urls:
            continue
        conn.execute(
            "UPDATE places SET menu_photos_json = ?, menu_photos_at = ? WHERE ftid = ?",
            (json.dumps(urls, ensure_ascii=False), today, ftid),
        )
    conn.commit()


def save(
    conn: sqlite3.Connection,
    key: str,
    title: str | None,
    places: list[Place],
    today: str,
    replace: bool = False,
) -> tuple[int, int]:
    if replace:
        conn.execute("DELETE FROM list_places WHERE list_key = ?", (key,))
    new = 0
    for place in places:
        exists = conn.execute("SELECT 1 FROM places WHERE ftid = ?", (place.ftid,)).fetchone()
        if not exists:
            new += 1
        first_seen = place.saved_on or today
        conn.execute(
            UPSERT,
            (
                place.ftid,
                place.name,
                place.address,
                place.category,
                place.rating,
                place.reviews,
                place.note,
                place.url,
                first_seen,
                today,
                place.saved_on,
                place.lat,
                place.lng,
                place.website,
                place.dishes,
                place.review_dishes,
                place.enriched_at,
                place.enrich_version,
                place.menu_dishes,
                place.menu_json,
                place.menu_at,
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO list_places (list_key, ftid) VALUES (?, ?)",
            (key, place.ftid),
        )
    conn.execute(
        """
        INSERT INTO lists (list_key, title, last_run) VALUES (?, ?, ?)
        ON CONFLICT(list_key) DO UPDATE SET title = excluded.title, last_run = excluded.last_run
        """,
        (key, title, today),
    )
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) FROM list_places WHERE list_key = ?", (key,)
    ).fetchone()[0]
    return total, new


def enrichment_cache(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT ftid, website, dishes, review_dishes, enriched_at, enrich_version, menu_at FROM places"
    ).fetchall()
    return {
        row["ftid"]: {
            "website": row["website"],
            "dishes": row["dishes"],
            "review_dishes": row["review_dishes"],
            "enriched_at": row["enriched_at"],
            "enrich_version": row["enrich_version"],
            "menu_at": row["menu_at"],
        }
        for row in rows
    }


def _rows(conn: sqlite3.Connection, key: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT p.* FROM places p
        JOIN list_places lp ON lp.ftid = p.ftid
        WHERE lp.list_key = ?
        ORDER BY p.name COLLATE NOCASE
        """,
        (key,),
    ).fetchall()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _titles(rows: list[sqlite3.Row]) -> dict[str, str]:
    counts = Counter(row["name"] for row in rows)
    result: dict[str, str] = {}
    for row in rows:
        title = row["name"]
        if counts[title] > 1:
            extra = row["address"] or row["category"]
            if extra:
                title = f"{title} ({extra.split(',')[0].strip()})"
            result[row["ftid"]] = title
        else:
            result[row["ftid"]] = title
    return result


def _menu_items(menu_json: str | None) -> list[dict]:
    if not menu_json:
        return []
    try:
        items = json.loads(menu_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return items if isinstance(items, list) else []


def write_markdown(conn: sqlite3.Connection, key: str, path: Path, today: str) -> int:
    rows = _rows(conn, key)
    titles = _titles(rows)
    lines = [
        "# Base de Datos: Locales Sin Gluten Guardados en Google Maps",
        "",
        f"_Actualizado: {today} · {len(rows)} lugares · Fuente: lista de Google Maps_",
        "",
        "Cada sección corresponde a un local guardado por el usuario en Google Maps.",
        "",
    ]
    for row in rows:
        lines.append(f"## {titles[row['ftid']]}")
        lines.append(f"- **Ubicación:** {row['address'] or 'No disponible'}")
        if row["category"]:
            lines.append(f"- **Categoría:** {row['category']}")
        if row["rating"]:
            value = f"- **Valoración:** {row['rating']} / 5"
            if row["reviews"]:
                value += f" ({row['reviews']} reseñas)"
            lines.append(value)
        lines.append(f"- **Enlace:** {row['url']}")
        if row["website"]:
            lines.append(f"- **Web:** {row['website']}")
        if row["dishes"]:
            lines.append(f"- **Menciona en su web:** {row['dishes']}")
        if row["review_dishes"]:
            lines.append(f"- **Menciona en reseñas:** {row['review_dishes']}")
        items = _menu_items(row["menu_json"])
        summary = dietary_summary(items, row["name"], row["category"])
        if row["menu_dishes"] and not items:
            lines.append(f"- **Carta (Google Maps):** {row['menu_dishes']}")
        lines.append(f"- **Fecha de registro:** {row['saved_on'] or row['first_seen']}")
        if row["note"]:
            lines.append(f"- **Nota:** {row['note']}")
        diet = dietary_line(summary)
        if diet:
            lines.append(diet)
        categories = categories_from_items(items)
        if categories:
            lines.append("")
            lines.append("### Qué vende")
            lines.append("")
            lines.extend(f"- {category}" for category in categories)
            lines.append("")
        lines.extend(menu_lines(items, summary["gluten_free"]))
        lines.append("")
    _atomic_write(path, "\n".join(lines).rstrip() + "\n")
    return len(rows)


def write_jsonl(conn: sqlite3.Connection, key: str, path: Path) -> int:
    rows = _rows(conn, key)
    lines = []
    for row in rows:
        parts = [f"Local: {row['name']}"]
        if row["address"]:
            parts.append(f"Ubicación: {row['address']}")
        if row["category"]:
            parts.append(f"Categoría: {row['category']}")
        if row["rating"]:
            parts.append(f"Valoración: {row['rating']} de 5")
        if row["note"]:
            parts.append(f"Nota: {row['note']}")
        if row["dishes"]:
            parts.append(f"Su web menciona: {row['dishes']}")
        if row["review_dishes"]:
            parts.append(f"Sus reseñas mencionan: {row['review_dishes']}")
        if row["menu_dishes"]:
            parts.append(f"Carta en Google Maps: {row['menu_dishes']}")
        parts.append("Guardado en mi lista de lugares sin gluten en Google Maps")
        menu = []
        if row["menu_json"]:
            try:
                menu = json.loads(row["menu_json"])
            except (json.JSONDecodeError, TypeError):
                menu = []
        menu_compact = [
            {"name": dish.get("name"), "price": dish.get("price")}
            for dish in menu
            if dish.get("name")
        ]
        record = {
            "id": row["ftid"],
            "text": ". ".join(parts) + ".",
            "metadata": {
                "name": row["name"],
                "address": row["address"],
                "category": row["category"],
                "rating": row["rating"],
                "reviews": row["reviews"],
                "url": row["url"],
                "website": row["website"],
                "dishes": row["dishes"],
                "review_dishes": row["review_dishes"],
                "menu": menu_compact,
                "menu_count": len(menu_compact),
                "saved_on": row["saved_on"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "lat": row["lat"],
                "lng": row["lng"],
            },
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))
    return len(rows)


def write_menus_jsonl(conn: sqlite3.Connection, key: str, path: Path) -> int:
    rows = conn.execute(
        """
        SELECT p.ftid, p.name, p.address, p.menu_json FROM places p
        JOIN list_places lp ON lp.ftid = p.ftid
        WHERE lp.list_key = ? AND p.menu_json IS NOT NULL AND p.menu_json != ''
        ORDER BY p.name COLLATE NOCASE
        """,
        (key,),
    ).fetchall()
    lines: list[str] = []
    for row in rows:
        try:
            dishes = json.loads(row["menu_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        for dish in dishes:
            if not isinstance(dish, dict) or not dish.get("name"):
                continue
            record = {
                "place_id": row["ftid"],
                "place": row["name"],
                "address": row["address"],
                "name": dish.get("name"),
                "original_name": dish.get("original_name"),
                "category": dish.get("category"),
                "price": dish.get("price"),
                "description": dish.get("description"),
                "ingredients": dish.get("ingredients"),
                "allergens": dish.get("allergens"),
                "dietary_type": dish.get("dietary_type"),
                "is_alcoholic": dish.get("is_alcoholic"),
                "nutrition": dish.get("nutrition"),
            }
            lines.append(json.dumps(record, ensure_ascii=False))
    _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))
    return len(lines)

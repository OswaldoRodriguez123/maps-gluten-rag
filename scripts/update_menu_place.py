from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maps_gluten import gdocs, photos, store  # noqa: E402
from maps_gluten.extract import Place  # noqa: E402


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.lower().split())


def _text(metadata: dict) -> str:
    parts = [f"Local: {metadata['name']}"]
    if metadata.get("address"):
        parts.append(f"Ubicación: {metadata['address']}")
    if metadata.get("category"):
        parts.append(f"Categoría: {metadata['category']}")
    if metadata.get("rating"):
        parts.append(f"Valoración: {metadata['rating']} de 5")
    if metadata.get("dishes"):
        parts.append(f"Su web menciona: {metadata['dishes']}")
    if metadata.get("review_dishes"):
        parts.append(f"Sus reseñas mencionan: {metadata['review_dishes']}")
    menu = metadata.get("menu") or []
    if menu:
        values = []
        for dish in menu:
            name = dish.get("name")
            if not name:
                continue
            price = dish.get("price")
            values.append(f"{name} ({price})" if price else name)
        if values:
            parts.append("Carta en Google Maps: " + "; ".join(values))
    parts.append("Guardado en mi lista de lugares sin gluten en Google Maps")
    return ". ".join(parts) + "."


def _update_markdown(path: Path, url: str, dishes: str | None) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        enlace = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("- **Enlace:** ")
            and line.split("**Enlace:**", 1)[1].strip() == url
        )
    except StopIteration:
        raise SystemExit(f"No encontré el enlace {url} en {path}")
    start = next(index for index in range(enlace, -1, -1) if lines[index].startswith("## "))
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    section = [line for line in lines[start:end] if not line.startswith("- **Carta (Google Maps):**")]
    if dishes:
        insert_at = next(
            (index for index, line in enumerate(section) if line.startswith("- **Fecha de registro:**")),
            len(section) - 1,
        )
        section.insert(insert_at, f"- **Carta (Google Maps):** {dishes}")
    content = "\n".join(lines[:start] + section + lines[end:]).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")
    return content


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Actualiza la carta de un solo local desde sus fotos de menú."
    )
    parser.add_argument("--place", required=True, help="Nombre parcial del local.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--basename", default="mis_lugares_sin_gluten")
    parser.add_argument("--publish", action="store_true", help="Actualiza el Google Doc.")
    parser.add_argument("--db", help="Ruta opcional al SQLite para persistir la caché.")
    parser.add_argument("--max-photos", type=int, default=12)
    parser.add_argument("--vision-photos", type=int, default=3)
    parser.add_argument("--max-charge", type=float, default=0.5)
    parser.add_argument("--no-vision", action="store_true")
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument(
        "--refresh-photos",
        action="store_true",
        help="Ignora la caché de fotos de menú y vuelve a raspar UnitBytes.",
    )
    args = parser.parse_args()

    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        raise SystemExit("Falta APIFY_TOKEN")
    vision_key = None if args.no_vision else (os.getenv("GEMINI_API_KEY", "").strip() or None)

    data_dir = Path(args.data_dir)
    jsonl_path = data_dir / f"{args.basename}.jsonl"
    md_path = data_dir / f"{args.basename}.md"
    records = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    query = _normalize(args.place)
    target = next(
        (record for record in records if query in _normalize(record["metadata"]["name"])),
        None,
    )
    if target is None:
        raise SystemExit(f"No encontré un local que contenga {args.place!r}")

    metadata = target["metadata"]
    today = date.today().isoformat()
    connection = store.connect(Path(args.db)) if args.db else None
    photo_cache = store.photo_cache(connection) if connection else {}
    place = Place(
        ftid=target["id"],
        name=metadata["name"],
        address=metadata.get("address"),
        category=metadata.get("category"),
        rating=metadata.get("rating"),
        reviews=metadata.get("reviews"),
        note=None,
        url=metadata["url"],
        website=metadata.get("website"),
        dishes=metadata.get("dishes"),
        review_dishes=metadata.get("review_dishes"),
    )
    count = photos.enrich_menus_photos(
        [place],
        token,
        max_photos=args.max_photos,
        max_charge_usd=args.max_charge,
        today=today,
        vision_key=vision_key,
        vision_max_photos=args.vision_photos,
        vision_max_places=1,
        photo_cache=photo_cache,
        refresh_photos=args.refresh_photos,
        reuse_recent_runs=0 if args.refresh_photos else 5,
        ocr=not args.no_ocr,
    )
    if not place.menu_json:
        if connection:
            connection.close()
        print(f"Sin carta legible para {place.name} ({count} platos)")
        return 1

    dishes = json.loads(place.menu_json)
    metadata["menu"] = [
        {"name": dish.get("name"), "price": dish.get("price")}
        for dish in dishes
        if dish.get("name")
    ]
    metadata["menu_count"] = len(metadata["menu"])
    target["text"] = _text(metadata)
    jsonl_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    summary = photos._summary(dishes)
    markdown = _update_markdown(md_path, metadata["url"], summary)

    if connection:
        try:
            connection.execute(
                "UPDATE places SET menu_dishes = ?, menu_json = ?, menu_at = ? WHERE ftid = ?",
                (summary, place.menu_json, place.menu_at, target["id"]),
            )
            store.save_photo_cache(
                connection, {place.ftid: photo_cache.get(place.ftid, [])}, today
            )
            connection.commit()
        finally:
            connection.close()

    if args.publish:
        doc_id = os.getenv("GDOC_ID", "").strip()
        if not doc_id:
            raise SystemExit("Falta GDOC_ID para publicar")
        gdocs.update_document(doc_id, markdown)
        print(f"Doc actualizado: {gdocs.document_url(doc_id)}")

    print(f"Local: {place.name}")
    print(f"Platos ({len(dishes)}): {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

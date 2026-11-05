from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maps_gluten import store  # noqa: E402
from maps_gluten.render import categories_from_items, dietary_summary  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _summary(items: list[dict]) -> str | None:
    parts = []
    for item in items:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        price = item.get("price_display") or item.get("price")
        parts.append(f"{name} ({price})" if price else name)
    return "; ".join(parts) if parts else None


def _diet_text(dietary: dict) -> str | None:
    parts = []
    if dietary.get("gluten_free"):
        parts.append("local 100% sin gluten")
    elif dietary.get("gluten_free_items"):
        parts.append(f"{dietary['gluten_free_items']} platos sin gluten")
    if dietary.get("vegan_items"):
        parts.append(f"{dietary['vegan_items']} veganos")
    if dietary.get("lactose_free_items"):
        parts.append(f"{dietary['lactose_free_items']} sin lactosa")
    return ", ".join(parts) if parts else None


def _text(metadata: dict, dishes: list[dict], categories: list[str], dietary: dict) -> str:
    parts = [f"Local: {metadata['name']}"]
    if metadata.get("address"):
        parts.append(f"Ubicación: {metadata['address']}")
    if metadata.get("category"):
        parts.append(f"Categoría: {metadata['category']}")
    if metadata.get("rating"):
        parts.append(f"Valoración: {metadata['rating']} de 5")
    if metadata.get("website"):
        parts.append(f"Web: {metadata['website']}")
    if metadata.get("review_dishes"):
        parts.append(f"Sus reseñas mencionan: {metadata['review_dishes']}")
    if categories:
        parts.append("Qué vende: " + ", ".join(categories))
    diet = _diet_text(dietary)
    if diet:
        parts.append(f"Dietético: {diet}")
    if dishes:
        values = []
        for dish in dishes:
            name = dish["name"]
            price = dish.get("price_display")
            tags = dish.get("dietary_tags") or []
            label = f"{name} ({price})" if price else name
            if tags:
                label += f" [{', '.join(tags)}]"
            values.append(label)
        parts.append("Carta: " + "; ".join(values))
    parts.append("Guardado en mi lista de lugares sin gluten en Google Maps")
    return ". ".join(parts) + "."


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aplica la normalización P0 al JSONL y opcionalmente a la base."
    )
    parser.add_argument("--places", required=True)
    parser.add_argument("--normalized-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--db")
    parser.add_argument("--today", default=date.today().isoformat())
    args = parser.parse_args()

    places = _load_jsonl(Path(args.places))
    normalized_dir = Path(args.normalized_dir)
    publishable = _load_jsonl(normalized_dir / "menus_publishable.jsonl")
    review = _load_jsonl(normalized_dir / "menus_review.jsonl")
    rejected = _load_jsonl(normalized_dir / "menus_rejected.jsonl")
    place_categories = {
        row.get("place_id"): row.get("categories") or []
        for row in _load_jsonl(normalized_dir / "place_categories.jsonl")
    }
    place_dietary = {
        row.get("place_id"): row
        for row in _load_jsonl(normalized_dir / "place_dietary.jsonl")
    }

    by_place: dict[str, list[dict]] = {}
    for item in publishable:
        place_id = item.get("place_id")
        if place_id:
            by_place.setdefault(place_id, []).append(item)

    review_counts: dict[str, int] = {}
    for item in review:
        place_id = item.get("place_id")
        if place_id:
            review_counts[place_id] = review_counts.get(place_id, 0) + 1
    rejected_counts: dict[str, int] = {}
    for item in rejected:
        place_id = item.get("place_id")
        if place_id:
            rejected_counts[place_id] = rejected_counts.get(place_id, 0) + 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    updated = []
    for record in places:
        metadata = record["metadata"]
        place_id = record["id"]
        items = by_place.get(place_id, [])
        dishes = [
            item
            for item in items
            if item.get("kind") in (None, "dish") and item.get("status") in (None, "ok")
        ]
        categories = place_categories.get(place_id) or categories_from_items(items)
        dietary = place_dietary.get(place_id) or dietary_summary(
            items, metadata["name"], metadata.get("category")
        )
        metadata["menu"] = [
            {
                "name": item.get("name"),
                "price": item.get("price_display") or item.get("price"),
                "category": item.get("category"),
                "tags": item.get("dietary_tags") or [],
                "kind": item.get("kind") or "dish",
            }
            for item in dishes
        ]
        metadata["menu_count"] = len(dishes)
        metadata["place_categories"] = categories
        metadata["dietary"] = {
            "gluten_free": bool(dietary.get("gluten_free")),
            "gluten_free_items": dietary.get("gluten_free_items", 0),
            "vegan_items": dietary.get("vegan_items", 0),
            "lactose_free_items": dietary.get("lactose_free_items", 0),
        }
        metadata["menu_review_count"] = review_counts.get(place_id, 0)
        metadata["menu_rejected_count"] = rejected_counts.get(place_id, 0)
        record["text"] = _text(metadata, dishes, categories, dietary)
        updated.append(record)

    _write_jsonl(out_dir / "mis_lugares_sin_gluten.jsonl", updated)
    _write_jsonl(out_dir / "mis_lugares_sin_gluten_menus.jsonl", publishable)
    _write_jsonl(out_dir / "menus_review.jsonl", review)
    _write_jsonl(out_dir / "menus_rejected.jsonl", rejected)

    if args.db and Path(args.db).exists():
        connection = store.connect(Path(args.db))
        try:
            for record in updated:
                place_id = record["id"]
                metadata = record["metadata"]
                items = by_place.get(place_id, [])
                dishes = [
                    item
                    for item in items
                    if item.get("kind") in (None, "dish")
                    and item.get("status") in (None, "ok")
                ]
                summary = _summary(dishes) or _summary(
                    [item for item in items if item.get("kind") == "category"]
                )
                connection.execute(
                    "UPDATE places SET menu_dishes = ?, menu_json = ?, menu_at = ? WHERE ftid = ?",
                    (
                        summary,
                        json.dumps(items, ensure_ascii=False) if items else None,
                        args.today,
                        place_id,
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    print(
        f"Lugares: {len(updated)} · publicables: {len(publishable)} · "
        f"revisión: {len(review)} · rechazados: {len(rejected)}"
    )
    print(f"Salida: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

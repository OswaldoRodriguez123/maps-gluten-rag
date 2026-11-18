from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maps_gluten import store  # noqa: E402
from maps_gluten.extract import Place  # noqa: E402

BASENAME = "mis_lugares_sin_gluten"


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _summary(rows: list[dict]) -> str | None:
    parts = []
    for row in rows:
        name = row.get("name")
        if not name:
            continue
        price = row.get("price_display") or row.get("price")
        parts.append(f"{name} ({price})" if price else name)
    return "; ".join(parts) or None


def sync_db_from_jsonl(data_dir: Path, db_path: Path) -> int:
    places = _load(data_dir / f"{BASENAME}.jsonl")
    menus = _load(data_dir / f"{BASENAME}_menus.jsonl")
    by_place: dict[str, list[dict]] = {}
    for row in menus:
        place_id = row.get("place_id")
        if place_id:
            by_place.setdefault(place_id, []).append(row)
    today = date.today().isoformat()
    conn = store.connect(db_path)
    branch_seeds = []
    try:
        objects = []
        for record in places:
            metadata = record.get("metadata") or {}
            place_id = record.get("id")
            if not place_id:
                continue
            rows = by_place.get(place_id) or []
            branches = metadata.get("branches")
            if branches:
                for branch in branches:
                    branch_seeds.append(branch)
                    objects.append(
                        Place(
                            ftid=branch["ftid"],
                            name=metadata.get("name") or place_id,
                            address=branch.get("address"),
                            category=metadata.get("category"),
                            rating=branch.get("rating"),
                            reviews=branch.get("reviews"),
                            note=branch.get("note"),
                            url=branch.get("url") or "",
                            saved_on=branch.get("saved_on"),
                            lat=branch.get("lat"),
                            lng=branch.get("lng"),
                            website=metadata.get("website"),
                            website_source=branch.get("website_source")
                            or metadata.get("website_source"),
                            dishes=metadata.get("dishes"),
                            review_dishes=metadata.get("review_dishes"),
                            menu_dishes=_summary(rows),
                            menu_json=json.dumps(rows, ensure_ascii=False) if rows else None,
                            menu_at=today if rows else None,
                        )
                    )
                continue
            objects.append(
                Place(
                    ftid=place_id,
                    name=metadata.get("name") or place_id,
                    address=metadata.get("address"),
                    category=metadata.get("category"),
                    rating=metadata.get("rating"),
                    reviews=metadata.get("reviews"),
                    note=None,
                    url=metadata.get("url") or "",
                    saved_on=metadata.get("saved_on"),
                    lat=metadata.get("lat"),
                    lng=metadata.get("lng"),
                    website=metadata.get("website"),
                    website_source=metadata.get("website_source"),
                    dishes=metadata.get("dishes"),
                    review_dishes=metadata.get("review_dishes"),
                    menu_dishes=_summary(rows),
                    menu_json=json.dumps(rows, ensure_ascii=False) if rows else None,
                    menu_at=today if rows else None,
                )
            )
        if objects:
            store.save(conn, "sync", "sync", objects, today)
        for branch in branch_seeds:
            conn.execute(
                "UPDATE places SET"
                " first_observed_at = COALESCE(?, first_observed_at),"
                " last_seen = COALESCE(?, last_seen),"
                " saved_on = COALESCE(?, saved_on),"
                " first_seen = COALESCE(NULLIF(?, ''), first_seen)"
                " WHERE ftid = ?",
                (
                    branch.get("first_observed_at"),
                    branch.get("last_seen"),
                    branch.get("saved_on"),
                    branch.get("saved_on") or "",
                    branch["ftid"],
                ),
            )
        if branch_seeds:
            conn.commit()
    finally:
        conn.close()
    return len(objects)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sincroniza SQLite desde los JSONL del repo antes de refrescar la lista."
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--db", default="data/historial_lugares.db")
    args = parser.parse_args()
    count = sync_db_from_jsonl(Path(args.data_dir), Path(args.db))
    print(f"Sincronizados {count} lugares en {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

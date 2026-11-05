from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maps_gluten import store  # noqa: E402
from maps_gluten.apify import _clean_dish, _summary  # noqa: E402

API = "https://api.apify.com/v2"
DATA = Path(os.getenv("DATA_DIR", "data"))
BASENAME = os.getenv("MAPS_OUT_BASENAME", "mis_lugares_sin_gluten")
DB = DATA / "historial_lugares.db"
TOKEN = os.environ["APIFY_TOKEN"]
DATASETS = [
    value.strip()
    for value in os.getenv(
        "RECOVER_DATASETS",
        "USweTMlgSrsr9abEE,hXxaJZaEhbVOfxhTz,ErkCCk936LeWbJaTO,aT0zGZ9lkBWlNTErK",
    ).split(",")
    if value.strip()
]
TODAY = os.getenv("TODAY", date.today().isoformat())


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _cid(url: str) -> str:
    try:
        return parse_qs(urlparse(url or "").query).get("cid", [""])[0]
    except ValueError:
        return ""


def _fetch(dataset_id: str) -> list[dict]:
    request = urllib.request.Request(
        f"{API}/datasets/{dataset_id}/items?format=json&clean=true&limit=10000",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.load(response)
    return data if isinstance(data, list) else data.get("items", [])


def _match(item: dict, by_url: dict, by_cid: dict, by_ftid: dict, by_name: dict):
    url = item.get("place") or ""
    record = by_url.get(url) or by_cid.get(_cid(url))
    if record:
        return record
    resolved = item.get("resolvedPlaceUrl") or ""
    match = re.search(r"!1s(0x[0-9a-fA-F]+):(0x[0-9a-fA-F]+)", resolved)
    if match:
        record = by_ftid.get(f"{match.group(1)}:{match.group(2)}")
        if record:
            return record
    match = re.search(r"/maps/place/([^/@?]+)", resolved)
    if match:
        name = unquote(match.group(1)).replace("+", " ").strip().lower()
        for key, record in by_name.items():
            if key and name and (key in name or name in key):
                return record
    return None


def main() -> int:
    jsonl_path = DATA / f"{BASENAME}.jsonl"
    md_path = DATA / f"{BASENAME}.md"
    menus_path = DATA / f"{BASENAME}_menus.jsonl"

    records = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_url = {record["metadata"]["url"]: record for record in records}
    by_cid = {_cid(record["metadata"]["url"]): record for record in records}
    by_ftid = {record["id"]: record for record in records}
    by_name = {record["metadata"]["name"].strip().lower(): record for record in records}

    menus: dict[str, list[dict]] = {}
    seen: set[tuple] = set()
    for dataset_id in DATASETS:
        try:
            items = _fetch(dataset_id)
        except Exception as error:
            print(f"Dataset {dataset_id}: {error}", file=sys.stderr)
            continue
        for item in items:
            if item.get("recordType") != "DISH":
                continue
            record = _match(item, by_url, by_cid, by_ftid, by_name)
            if record is None:
                continue
            dish = _clean_dish(item)
            key = (record["id"], dish.get("name"), dish.get("price"), dish.get("category"))
            if key in seen:
                continue
            seen.add(key)
            menus.setdefault(record["id"], []).append(dish)
        print(f"Dataset {dataset_id}: {len(items)} filas")

    summary_by_url: dict[str, str] = {}
    for record in records:
        dishes = menus.get(record["id"]) or []
        if not dishes:
            continue
        metadata = record["metadata"]
        compact = [
            {"name": dish.get("name"), "price": dish.get("price")}
            for dish in dishes
            if dish.get("name")
        ]
        metadata["menu"] = compact
        metadata["menu_count"] = len(compact)
        menu_summary = _summary(dishes)
        if menu_summary:
            summary_by_url[metadata["url"]] = menu_summary

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
        if menu_summary:
            parts.append(f"Carta en Google Maps: {menu_summary}")
        parts.append("Guardado en mi lista de lugares sin gluten en Google Maps")
        record["text"] = ". ".join(parts) + "."

    _write(jsonl_path, "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n")

    lines = md_path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        output.append(line)
        if line.startswith("- **Enlace:** "):
            url = line.split("**Enlace:**", 1)[1].strip()
            menu_summary = summary_by_url.get(url)
            if menu_summary:
                next_index = index + 1
                if next_index < len(lines) and lines[next_index].startswith("- **Carta (Google Maps):**"):
                    index = next_index
                output.append(f"- **Carta (Google Maps):** {menu_summary}")
        index += 1
    _write(md_path, "\n".join(output).rstrip() + "\n")

    menu_lines: list[str] = []
    for record in records:
        dishes = menus.get(record["id"]) or []
        for dish in dishes:
            if not dish.get("name"):
                continue
            menu_lines.append(
                json.dumps(
                    {
                        "place_id": record["id"],
                        "place": record["metadata"]["name"],
                        "address": record["metadata"].get("address"),
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
                    },
                    ensure_ascii=False,
                )
            )
    _write(menus_path, "\n".join(menu_lines) + ("\n" if menu_lines else ""))

    connection = store.connect(DB)
    try:
        for record in records:
            dishes = menus.get(record["id"]) or []
            if not dishes:
                continue
            metadata = record["metadata"]
            payload = json.dumps(dishes, ensure_ascii=False)
            menu_summary = _summary(dishes)
            cursor = connection.execute(
                "UPDATE places SET menu_dishes = ?, menu_json = ?, menu_at = ? WHERE ftid = ?",
                (menu_summary, payload, TODAY, record["id"]),
            )
            if cursor.rowcount == 0:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO places (
                        ftid, name, address, category, rating, reviews, note, url,
                        first_seen, last_seen, saved_on, lat, lng,
                        menu_dishes, menu_json, menu_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        metadata.get("name"),
                        metadata.get("address"),
                        metadata.get("category"),
                        metadata.get("rating"),
                        metadata.get("reviews"),
                        None,
                        metadata.get("url"),
                        metadata.get("first_seen") or TODAY,
                        metadata.get("last_seen") or TODAY,
                        metadata.get("saved_on"),
                        metadata.get("lat"),
                        metadata.get("lng"),
                        menu_summary,
                        payload,
                        TODAY,
                    ),
                )
        connection.commit()
    finally:
        connection.close()

    print(f"Locales con carta: {len(summary_by_url)}")
    print(f"Platos: {len(menu_lines)}")
    print(f"Markdown: {md_path}")
    print(f"JSONL: {jsonl_path}")
    print(f"Menús: {menus_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

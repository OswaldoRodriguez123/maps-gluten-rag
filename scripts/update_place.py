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

from playwright.sync_api import sync_playwright  # noqa: E402

from maps_gluten import enrich, gdocs, store  # noqa: E402
from maps_gluten.text import one_line  # noqa: E402


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.lower().split())


def _text(metadata: dict, dishes: str | None) -> str:
    parts = [f"Local: {metadata['name']}"]
    if metadata.get("address"):
        parts.append(f"Ubicación: {metadata['address']}")
    if metadata.get("category"):
        parts.append(f"Categoría: {metadata['category']}")
    if metadata.get("rating"):
        parts.append(f"Valoración: {metadata['rating']} de 5")
    if dishes:
        parts.append(f"Su web menciona: {dishes}")
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
    section = [
        line for line in lines[start:end] if not line.startswith("- **Menciona en su web:**")
    ]
    if dishes:
        insert_at = next(
            (index for index, line in enumerate(section) if line.startswith("- **Web:**")),
            None,
        )
        if insert_at is None:
            insert_at = next(
                (index for index, line in enumerate(section) if line.startswith("- **Enlace:**")),
                len(section) - 1,
            )
        section.insert(insert_at + 1, f"- **Menciona en su web:** {one_line(dishes)}")
    content = "\n".join(lines[:start] + section + lines[end:]).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description="Actualiza un solo local desde su web.")
    parser.add_argument("--place", required=True, help="Nombre parcial del local.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--basename", default="mis_lugares_sin_gluten")
    parser.add_argument("--publish", action="store_true", help="Actualiza el Google Doc.")
    parser.add_argument("--db", help="Ruta opcional al SQLite para persistir la caché.")
    args = parser.parse_args()

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

    website = target["metadata"].get("website")
    if not website:
        raise SystemExit(f"{target['metadata']['name']} no tiene web registrada")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="es-CL", viewport={"width": 1400, "height": 1000})
        products = enrich._site_dishes(website, ocr=False)
        if not products:
            products = enrich._render_site_products(page, website)
        browser.close()

    dishes = ", ".join(products) if products else None
    target["metadata"]["dishes"] = dishes
    target["text"] = _text(target["metadata"], dishes)
    jsonl_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    markdown = _update_markdown(md_path, target["metadata"]["url"], dishes)

    if args.db and Path(args.db).exists():
        connection = store.connect(Path(args.db))
        try:
            connection.execute(
                "UPDATE places SET dishes = ?, enriched_at = ? WHERE ftid = ?",
                (dishes, date.today().isoformat(), target["id"]),
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

    print(f"Local: {target['metadata']['name']}")
    print(f"Web: {website}")
    print(f"Productos ({len(products)}): {dishes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

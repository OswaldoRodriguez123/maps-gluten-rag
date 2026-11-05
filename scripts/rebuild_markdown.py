from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maps_gluten import gdocs  # noqa: E402
from maps_gluten.render import document  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconstruye el Markdown del Doc con una carta por plato."
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--basename", default="mis_lugares_sin_gluten")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--doc-id", default=os.getenv("GDOC_ID", ""))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    records = [
        json.loads(line)
        for line in (data_dir / f"{args.basename}.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    menus_path = data_dir / f"{args.basename}_menus.jsonl"
    menus: dict[str, list[dict]] = {}
    if menus_path.exists():
        for line in menus_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            place_id = row.get("place_id")
            if not place_id:
                continue
            menus.setdefault(place_id, []).append(row)

    markdown = document(records, menus, date.today().isoformat())
    md_path = data_dir / f"{args.basename}.md"
    md_path.write_text(markdown, encoding="utf-8")
    print(f"Markdown: {md_path} ({len(markdown)} caracteres)")

    if args.publish:
        if not args.doc_id:
            raise SystemExit("Falta GDOC_ID o --doc-id")
        count = gdocs.update_document(args.doc_id, markdown)
        print(f"Doc actualizado: {gdocs.document_url(args.doc_id)} ({count} bloques)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

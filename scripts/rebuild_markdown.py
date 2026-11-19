from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maps_gluten import drive  # noqa: E402
from maps_gluten.render import document  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconstruye el Markdown para NotebookLM con una carta por plato."
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--basename", default="mis_lugares_sin_gluten")
    parser.add_argument("--publish", action="store_true")
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
    md_path = data_dir / f"{args.basename}.txt"
    md_path.write_text(markdown, encoding="utf-8")
    print(f"TXT: {md_path} ({len(markdown)} caracteres)")

    if args.publish:
        try:
            file_id = drive.sync_markdown(md_path)
        except Exception as error:
            raise SystemExit(f"Error al subir el .txt a Drive: {error}")
        if file_id:
            print(f"Drive actualizado: {md_path.name} (id {file_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

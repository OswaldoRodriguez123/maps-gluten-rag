import json
import tempfile
import unittest
from pathlib import Path

from maps_gluten import store
from scripts.sync_db_from_jsonl import sync_db_from_jsonl


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class SyncDbTest(unittest.TestCase):
    def test_menus_from_jsonl_are_preserved_in_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            place = {
                "id": "a",
                "metadata": {
                    "name": "A",
                    "url": "https://maps",
                    "address": None,
                    "category": None,
                    "rating": None,
                    "reviews": None,
                    "saved_on": "2026-11-01",
                },
            }
            write_jsonl(data_dir / "mis_lugares_sin_gluten.jsonl", [place])
            write_jsonl(
                data_dir / "mis_lugares_sin_gluten_menus.jsonl",
                [{"place_id": "a", "place": "A", "name": "Torta", "price": "$1.000"}],
            )
            db_path = Path(tmp) / "historial.db"
            sync_db_from_jsonl(data_dir, db_path)
            conn = store.connect(db_path)
            menu_json = conn.execute(
                "SELECT menu_json FROM places WHERE ftid='a'"
            ).fetchone()[0]
            conn.close()
            self.assertIn("Torta", menu_json or "")


if __name__ == "__main__":
    unittest.main()

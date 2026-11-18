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


class SyncChainTest(unittest.TestCase):
    def test_chain_record_seeds_one_place_per_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            chain = {
                "id": "h1",
                "metadata": {
                    "name": "Havanna",
                    "address": "Av. Apoquindo 3001",
                    "category": "Tienda de chocolates",
                    "rating": "4.7",
                    "reviews": "210",
                    "url": "https://maps/h1",
                    "website": "https://havanna.cl/",
                    "website_source": "maps",
                    "dishes": "chocolate",
                    "review_dishes": "alfajores",
                    "saved_on": "2026-11-10",
                    "chain": True,
                    "branches": [
                        {"ftid": "h1", "address": "Dir Uno", "rating": "4.7",
                         "reviews": "210", "url": "https://maps/h1", "saved_on": "2026-11-11",
                         "lat": -33.4, "lng": -70.6, "note": "p/ mamá",
                         "website_source": "maps", "first_observed_at": "2026-11-10",
                         "first_seen": "2026-11-10", "last_seen": "2026-11-15"},
                        {"ftid": "h2", "address": "Dir Dos", "rating": "4.8",
                         "reviews": "150", "url": "https://maps/h2", "saved_on": "2026-11-12",
                         "lat": -33.5, "lng": -70.7, "note": None,
                         "website_source": "search", "first_observed_at": "2026-11-12",
                         "first_seen": "2026-11-12", "last_seen": "2026-11-16"},
                    ],
                },
            }
            write_jsonl(data_dir / "mis_lugares_sin_gluten.jsonl", [chain])
            write_jsonl(
                data_dir / "mis_lugares_sin_gluten_menus.jsonl",
                [{"place_id": "h1", "place": "Havanna", "name": "Alfajor", "price": "$1.000"}],
            )
            db_path = Path(tmp) / "historial.db"
            count = sync_db_from_jsonl(data_dir, db_path)
            conn = store.connect(db_path)
            rows = conn.execute(
                "SELECT ftid, address, note, saved_on, first_seen, website,"
                " website_source, dishes, review_dishes, menu_json"
                " FROM places ORDER BY ftid"
            ).fetchall()
            conn.close()
        self.assertEqual(count, 2)
        self.assertEqual([r["ftid"] for r in rows], ["h1", "h2"])
        for r in rows:
            self.assertIn("Alfajor", r["menu_json"])
        self.assertEqual(rows[0]["note"], "p/ mamá")
        self.assertIsNone(rows[1]["note"])
        self.assertEqual(rows[0]["saved_on"], "2026-11-11")
        self.assertEqual(rows[0]["first_seen"], "2026-11-11")
        self.assertEqual(rows[0]["address"], "Dir Uno")
        self.assertEqual(rows[1]["address"], "Dir Dos")
        self.assertEqual(rows[0]["website_source"], "maps")
        self.assertEqual(rows[1]["website_source"], "search")
        self.assertEqual({r["dishes"] for r in rows}, {"chocolate"})

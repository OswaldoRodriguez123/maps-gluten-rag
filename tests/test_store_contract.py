import json
import tempfile
import unittest
from pathlib import Path

from maps_gluten import store
from maps_gluten.extract import Place


def make_place(ftid="abc", name="X", menu_json=None):
    return Place(
        ftid=ftid,
        name=name,
        address=None,
        category=None,
        rating=None,
        reviews=None,
        note=None,
        url="https://maps",
        saved_on="2020-01-01",
        menu_json=menu_json,
    )


class StoreContractTest(unittest.TestCase):
    def test_first_observed_at_is_set_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = store.connect(Path(tmp) / "t.db")
            store.save(conn, "list", "L", [make_place()], "2026-11-06")
            first = conn.execute(
                "SELECT first_observed_at FROM places WHERE ftid='abc'"
            ).fetchone()[0]
            store.save(conn, "list", "L", [make_place()], "2026-11-07")
            second = conn.execute(
                "SELECT first_observed_at FROM places WHERE ftid='abc'"
            ).fetchone()[0]
            conn.close()
        self.assertEqual(first, "2026-11-06")
        self.assertEqual(second, "2026-11-06")

    def test_menus_jsonl_preserves_source_and_quality_fields(self):
        item = {
            "name": "Torta",
            "price": "$10.000",
            "price_display": "$10.000",
            "category": "Tortas",
            "source": "apparta",
            "status": "ok",
            "kind": "dish",
            "dietary_tags": ["sin gluten"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            conn = store.connect(Path(tmp) / "t.db")
            store.save(
                conn,
                "list",
                "L",
                [make_place(menu_json=json.dumps([item]))],
                "2026-11-06",
            )
            out = Path(tmp) / "menus.jsonl"
            store.write_menus_jsonl(conn, "list", out)
            row = json.loads(out.read_text(encoding="utf-8").strip())
            conn.close()
        self.assertEqual(row["source"], "apparta")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["kind"], "dish")
        self.assertEqual(row["dietary_tags"], ["sin gluten"])
        self.assertEqual(row["price_display"], "$10.000")


def test_store_persists_website_source():
    with tempfile.TemporaryDirectory() as tmp:
        conn = store.connect(Path(tmp) / "t.db")
        place = Place(
            ftid="abc",
            name="X",
            address=None,
            category=None,
            rating=None,
            reviews=None,
            note=None,
            url="https://maps",
            saved_on="2020-01-01",
            website="https://ejemplo.cl/",
            website_source="search",
        )
        store.save(conn, "list", "L", [place], "2026-11-06")
        row = conn.execute(
            "SELECT website_source FROM places WHERE ftid='abc'"
        ).fetchone()
        out = Path(tmp) / "out.jsonl"
        store.write_jsonl(conn, "list", out)
        record = json.loads(out.read_text(encoding="utf-8").strip())
        conn.close()
    assert row[0] == "search"
    assert record["metadata"]["website_source"] == "search"


if __name__ == "__main__":
    unittest.main()

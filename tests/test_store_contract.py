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


def _chain_places():
    menu_json = json.dumps([
        {"name": "Alfajor", "price": "$1.000", "category": "Chocolate",
         "source": "apparta", "status": "ok", "kind": "dish", "dietary_tags": []},
    ])
    specs = [
        ("h1", "Av. Apoquindo 3001", "4.7", "210", "2026-11-12", "2026-11-13", None, "alfajores"),
        ("h2", "Av. Nueva Costanera 3900", "4.8", "150", "2026-11-10", "2026-11-15", "p/ regalo", "chocolates"),
        ("h3", "Parque Arauco 730", "4.5", "180", "2026-11-13", "2026-11-11", None, "galletas"),
        ("h4", "Vina del Mar 250", "4.9", "300", "2026-11-11", "2026-11-10", None, "mermelada"),
    ]
    out = []
    for ftid, address, rating, reviews, saved_on, last_seen, note, review_dishes in specs:
        out.append(Place(
            ftid=ftid,
            name="Havanna",
            address=address,
            category="Tienda de chocolates",
            rating=rating,
            reviews=reviews,
            note=note,
            url=f"https://maps/{ftid}",
            saved_on=saved_on,
            lat=-33.4 if ftid != "h4" else -33.0,
            lng=-70.6,
            website="https://havanna.cl/",
            website_source="maps",
            review_dishes=review_dishes,
            menu_json=menu_json,
        ))
    return out


class ChainSaveTest(unittest.TestCase):
    def _save(self, conn, places):
        store.save(conn, "list", "L", places, "2026-11-06")

    def test_chain_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = store.connect(Path(tmp) / "t.db")
            places = _chain_places()
            single = Place(
                ftid="x1", name="X Local", address="Calle X", category="Cafetería",
                rating="4.5", reviews="10", note=None, url="https://maps/x",
                saved_on="2020-01-01", url_lat_lng_ok=None,
            ) if False else Place(
                ftid="x1", name="X Local", address="Calle X", category="Cafetería",
                rating="4.5", reviews="10", note=None, url="https://maps/x",
                saved_on="2020-01-01",
            )
            self._save(conn, places + [single])
            jsonl = Path(tmp) / "out.jsonl"
            store.write_jsonl(conn, "list", jsonl)
            records = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines()]
            md = Path(tmp) / "out.md"
            store.write_markdown(conn, "list", md, "2026-11-15")
            md_text = md.read_text(encoding="utf-8")
            menus = Path(tmp) / "menus.jsonl"
            store.write_menus_jsonl(conn, "list", menus)
            menu_lines = menus.read_text(encoding="utf-8").splitlines()
            conn.close()

        by_id = {r["id"]: r for r in records}
        self.assertEqual(len(records), 2)
        chain = by_id["h1"]
        self.assertTrue(chain["metadata"]["chain"])
        branches = chain["metadata"]["branches"]
        self.assertEqual([b["ftid"] for b in branches], ["h1", "h2", "h3", "h4"])
        expected_keys = {"ftid", "address", "rating", "reviews", "url", "saved_on",
                         "lat", "lng", "note", "website_source", "first_observed_at",
                         "first_seen", "last_seen"}
        for b in branches:
            self.assertEqual(set(b), expected_keys)
        self.assertEqual(branches[1]["note"], "p/ regalo")
        self.assertEqual(chain["metadata"]["saved_on"], "2026-11-10")
        self.assertEqual(chain["metadata"]["last_seen"], max(b["last_seen"] for b in branches))
        self.assertEqual(chain["metadata"]["first_seen"], min(b["first_seen"] for b in branches))
        self.assertEqual(chain["metadata"]["lat"], -33.4)
        self.assertEqual(chain["metadata"]["address"], "Av. Apoquindo 3001")
        self.assertIn("Cadena: 4 sucursales", chain["text"])
        self.assertIn("Av. Apoquindo 3001 | Av. Nueva Costanera 3900", chain["text"])
        self.assertIn("Web:", chain["text"])
        self.assertEqual(by_id["x1"]["metadata"].get("chain"), None)
        self.assertNotIn("branches", by_id["x1"]["metadata"])

        self.assertEqual(md_text.count("## Havanna"), 1)
        self.assertIn("- **Cadena:** 4 sucursales", md_text)
        self.assertIn("### Sucursales", md_text)
        for b in branches:
            self.assertIn(b["address"], md_text)
        self.assertIn("*Nota: p/ regalo*", md_text)
        self.assertEqual(md_text.count("### Carta"), 1)
        self.assertIn("## X Local", md_text)
        self.assertNotIn("### Sucursales\n- Calle X", md_text)

        selva = [json.loads(l) for l in menu_lines]
        self.assertEqual(len(selva), 1)
        self.assertEqual(selva[0]["place_id"], "h1")
        self.assertEqual(selva[0]["place"], "Havanna")

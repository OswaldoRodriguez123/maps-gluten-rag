import unittest

from maps_gluten.render import document, is_store_place


def _record(id, name, category, menu):
    return {
        "id": id,
        "metadata": {
            "name": name,
            "address": "Calle X",
            "category": category,
            "rating": "4.5",
            "url": "https://maps",
            "dishes": "pizza, lasaña",
            "review_dishes": "pizza",
            "saved_on": "2026-11-06",
        },
        "text": name,
        "_menu_for_test": menu,
    }


class RenderStoreTest(unittest.TestCase):
    def test_store_only_mentions_no_carta(self):
        record = _record("a", "Biomercado", "Tienda de alimentación", [])
        menus = {
            "a": [
                {"name": "Aceite de Oliva 1L", "category": "Despensa", "price": "$9.000"},
                {"name": "Mermelada 500g", "category": "Despensa", "price": "$3.000"},
            ]
        }
        md = document([record], menus, "2026-11-06")
        self.assertIn("Menciona en su web", md)
        self.assertIn("Menciona en reseñas", md)
        self.assertNotIn("### Carta", md)
        self.assertNotIn("Aceite de Oliva", md)
        self.assertNotIn("Qué vende", md)

    def test_restaurant_keeps_carta(self):
        record = _record("b", "Pizza Lugar", "Restaurante", [])
        menus = {
            "b": [{"name": "Pizza Pepperoni", "category": "Pizzas", "price": "$10.000"}]
        }
        md = document([record], menus, "2026-11-06")
        self.assertIn("### Carta", md)
        self.assertIn("Pizza Pepperoni", md)

    def test_is_store_place(self):
        self.assertTrue(is_store_place({"category": "Tienda de alimentos naturales"}))
        self.assertTrue(is_store_place({"category": "Supermercado"}))
        self.assertTrue(is_store_place({"category": "Tienda de pasta"}))
        self.assertFalse(is_store_place({"category": "Pastelería"}))
        self.assertFalse(is_store_place({"category": "Restaurante"}))


if __name__ == "__main__":
    unittest.main()


def _chain_record(id, name, category, branches, **overrides):
    metadata = {
        "name": name,
        "address": branches[0]["address"],
        "category": category,
        "rating": "4.6",
        "reviews": "120",
        "url": branches[0]["url"],
        "website": "https://havanna.cl/",
        "dishes": "chocolate",
        "review_dishes": "alfajores",
        "saved_on": "2026-11-10",
        "chain": True,
        "branches": branches,
    }
    metadata.update(overrides)
    return {"id": id, "metadata": metadata, "text": name}


def _branches(n=4, notes_at=(1, 3)):
    out = []
    addrs = ["Av. Apoquindo 3001", "Av. Nueva Costanera 3900", "Parque Arauco 730", "Viña del Mar 250"]
    for i in range(n):
        out.append({
            "ftid": f"h{i + 1}",
            "address": addrs[i],
            "rating": f"4.{i}",
            "reviews": str(100 + i * 10),
            "url": f"https://maps/{i}",
            "saved_on": f"2026-11-1{i}",
            "lat": -33.4,
            "lng": -70.6,
            "note": f"nota {i}" if i in notes_at else None,
            "website_source": "maps",
            "first_observed_at": "2026-11-10",
            "first_seen": "2026-11-10",
            "last_seen": "2026-11-15",
        })
    return out


class ChainDocumentTest(unittest.TestCase):
    def test_chain_section_renders_sucursales_and_carta(self):
        branches = _branches()
        record = _chain_record("h1", "Havanna", "Pastelería", branches)
        menus = {"h1": [{"name": "Alfajor", "category": "Chocolate", "price": "$1.000"}]}
        md = document([record], menus, "2026-11-15")
        self.assertIn("## Havanna", md)
        self.assertIn("- **Cadena:** 4 sucursales", md)
        self.assertIn("### Sucursales", md)
        for b in branches:
            self.assertIn(b["address"], md)
            self.assertIn(f"[Maps]({b['url']})", md)
        self.assertEqual(md.count("*Nota:"), 2)
        self.assertIn("### Carta", md)
        self.assertEqual(md.count("## Havanna"), 1)

    def test_chain_store_keeps_sucursales_but_no_carta(self):
        branches = _branches()
        record = _chain_record("h1", "Havanna", "Tienda de chocolates", branches)
        menus = {"h1": [{"name": "Alfajor", "category": "Chocolate", "price": "$1.000"}]}
        md = document([record], menus, "2026-11-15")
        self.assertIn("### Sucursales", md)
        self.assertIn("- **Cadena:** 4 sucursales", md)
        self.assertNotIn("### Carta", md)

    def test_single_local_output_unchanged_by_chain_support(self):
        record = {
            "id": "b",
            "metadata": {
                "name": "Pizza Lugar",
                "address": "Calle X",
                "category": "Restaurante",
                "rating": "4.5",
                "url": "https://maps",
                "saved_on": "2026-11-06",
            },
            "text": "Pizza Lugar",
        }
        md = document([record], {"b": []}, "2026-11-15")
        self.assertIn("## Pizza Lugar", md)
        self.assertNotIn("Cadena:", md)
        self.assertNotIn("### Sucursales", md)

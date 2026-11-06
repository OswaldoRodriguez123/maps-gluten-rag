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

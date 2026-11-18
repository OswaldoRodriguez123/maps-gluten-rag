import unittest

from scripts.apply_normalization import _text


def chain_metadata():
    return {
        "name": "Havanna",
        "address": "Av. Apoquindo 3001",
        "category": "Tienda de chocolates",
        "rating": "4.7",
        "website": "https://havanna.cl/",
        "review_dishes": "alfajores",
        "saved_on": "2026-11-10",
        "chain": True,
        "branches": [
            {"ftid": "h1", "address": "Dir Uno"},
            {"ftid": "h2", "address": None},
        ],
    }


DISHES = [{"name": "Alfajor", "price_display": "$1.000", "dietary_tags": ["sin gluten"]}]


class ChainTextTest(unittest.TestCase):
    def test_chain_record_uses_branch_addresses(self):
        text = _text(chain_metadata(), DISHES, ["Chocolates"], {"gluten_free_items": 1})
        self.assertIn("Local: Havanna", text)
        self.assertIn("Cadena: 2 sucursales", text)
        self.assertIn("Ubicación: Dir Uno | No disponible", text)
        self.assertEqual(text.count("Ubicación:"), 1)
        self.assertIn("Categoría: Tienda de chocolates", text)
        self.assertIn("Valoración: 4.7 de 5", text)
        self.assertIn("Web: https://havanna.cl/", text)
        self.assertIn("Sus reseñas mencionan: alfajores", text)
        self.assertIn("Carta:", text)

    def test_single_record_unchanged(self):
        metadata = {
            "name": "Pizza Lugar",
            "address": "Calle X",
            "category": "Restaurante",
            "rating": "4.5",
            "website": "https://pizza.cl/",
        }
        text = _text(metadata, [], [], {})
        self.assertNotIn("Cadena:", text)
        self.assertIn("Ubicación: Calle X", text)


if __name__ == "__main__":
    unittest.main()

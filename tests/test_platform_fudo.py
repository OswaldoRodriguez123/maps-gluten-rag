import unittest
from unittest.mock import patch

from maps_gluten.platforms.base import PlaceContext
from maps_gluten.platforms.fudo import FudoAdapter


def ctx(menu_url="https://menu.fu.do/demo"):
    return PlaceContext(
        record={},
        place_id="1",
        name="Local",
        website=None,
        menu_url=menu_url,
        order_urls=[],
    )


class FudoAdapterTest(unittest.TestCase):
    def test_detect_only_fudo(self):
        adapter = FudoAdapter()
        self.assertTrue(adapter.detect(ctx()))
        self.assertFalse(adapter.detect(ctx("https://example.com")))

    @patch("maps_gluten.fudo.fetch_menu")
    def test_extract_maps_items(self, fetch_menu):
        fetch_menu.return_value = [
            {"name": "Torta", "price": "$10.000", "category": "Tortas", "description": "rica"}
        ]
        result = FudoAdapter().extract(ctx())
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.source, "fudo")
        self.assertEqual(result.items[0].name, "Torta")
        self.assertEqual(result.items[0].price, "$10.000")


if __name__ == "__main__":
    unittest.main()

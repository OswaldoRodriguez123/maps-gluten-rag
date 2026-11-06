import json
import unittest
from unittest.mock import MagicMock, patch

from maps_gluten.platforms.base import PlaceContext
from maps_gluten.platforms.jsonld import JsonLdAdapter, parse_products
from maps_gluten.platforms.render import RenderAdapter
from maps_gluten.platforms.woocommerce import WooCommerceAdapter


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return FakeResponse(self.data)


def ctx(session=None, browser=None, website="https://shop.cl"):
    return PlaceContext(
        record={},
        place_id="1",
        name="Local",
        website=website,
        menu_url=None,
        order_urls=[],
        session=session,
        browser=browser,
    )


class WooCommerceTest(unittest.TestCase):
    def test_extract_price_minor_units(self):
        product = {
            "name": "Galleta",
            "prices": {"price": "4990", "currency_minor_unit": 0},
            "categories": [{"name": "Sin gluten"}],
            "short_description": "rica",
            "is_in_stock": True,
        }
        session = FakeSession([product])
        result = WooCommerceAdapter().extract(ctx(session))
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.source, "woocommerce")
        self.assertEqual(result.items[0].price, "$4.990")
        self.assertEqual(result.items[0].category, "Sin gluten")


class JsonLdTest(unittest.TestCase):
    def test_parse_product_offer(self):
        html = """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Margarita",
         "offers":{"@type":"Offer","price":"15900","priceCurrency":"CLP"}}
        </script>
        """
        items = parse_products(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Margarita")
        self.assertEqual(items[0].price, "$15.900")
        self.assertEqual(items[0].source, "web-jsonld")


class RenderTest(unittest.TestCase):
    @patch("maps_gluten.enrich._render_site_products")
    def test_render_names_without_prices(self, render):
        render.return_value = ["Pizza Margarita"]
        browser = MagicMock()
        browser.new_page.return_value = MagicMock()
        result = RenderAdapter().extract(ctx(browser=browser))
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.items[0].name, "Pizza Margarita")
        self.assertIsNone(result.items[0].price)
        self.assertEqual(result.items[0].source, "web-render")


if __name__ == "__main__":
    unittest.main()

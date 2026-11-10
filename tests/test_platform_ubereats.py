import os
import unittest
from unittest.mock import patch

from maps_gluten.platforms.base import PlaceContext
from maps_gluten.platforms.ubereats import UberEatsAdapter


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return FakeResponse(self.data)


PLAIN_CONTEXT = dict(
    record={},
    place_id="1",
    name="Local",
    website=None,
    menu_url=None,
    order_urls=[
        {"provider": "UberEats",
         "url": "https://www.ubereats.com/cl/store/el-patio-juice-bar/hNBgrQ0SQ5aYqojqnCVydA?diningMode=PICKUP"},
    ],
    session=None,
    browser=None,
)


class UberEatsAdapterTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("UBER_EATS_API_URL", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["UBER_EATS_API_URL"] = self._saved

    def test_store_id_from_order_url(self):
        adapter = UberEatsAdapter()
        ctx = PlaceContext(**PLAIN_CONTEXT)
        self.assertEqual(adapter._store_id(ctx), "hNBgrQ0SQ5aYqojqnCVydA")
        self.assertTrue(adapter.detect(ctx))

    def test_extract_without_api_url_fails_with_clear_message(self):
        """Sin UBER_EATS_API_URL (o vacía): error explícito, no ConnectionError críptico."""
        adapter = UberEatsAdapter()

        # Caso 1: variable no definida.
        result = adapter.extract(PlaceContext(**PLAIN_CONTEXT))
        self.assertEqual(result.status, "error")
        self.assertIn("UBER_EATS_API_URL", result.error)

        # Caso 2: variable definida pero vacía (caso típico en CI sin el secret).
        os.environ["UBER_EATS_API_URL"] = ""
        result = adapter.extract(PlaceContext(**PLAIN_CONTEXT))
        self.assertEqual(result.status, "error")
        self.assertIn("UBER_EATS_API_URL", result.error)

    def test_extract_parses_menu_sections(self):
        os.environ["UBER_EATS_API_URL"] = "http://proxy.test"
        data = {
            "sections": [
                {"categories": [
                    {"title": "Postres", "items": [
                        {"name": "Mousse de chocolate", "price": 5990,
                         "description": "Con coulis de frambuesa", "link": "x"},
                    ]},
                ]},
            ]
        }
        session = FakeSession(data)
        ctx = PlaceContext(**{**PLAIN_CONTEXT, "session": session, "order_urls": PLAIN_CONTEXT["order_urls"]})
        result = UberEatsAdapter().extract(ctx)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.name, "Mousse de chocolate")
        self.assertEqual(item.price, "$5.990")
        self.assertEqual(item.category, "Postres")
        self.assertEqual(session.calls, ["http://proxy.test/stores/menu"])

    def test_extract_report_error_url_matches_proxy_base(self):
        """El mensaje de error conserva la URL del proxy configurado (útil para debuggear)."""
        os.environ["UBER_EATS_API_URL"] = "http://proxy.test"

        class BoomSession:
            def get(self, url, **kwargs):
                raise OSError("timeout")

        ctx = PlaceContext(**{**PLAIN_CONTEXT, "session": BoomSession()})
        result = UberEatsAdapter().extract(ctx)
        self.assertEqual(result.status, "error")
        self.assertNotIn("UBER_EATS_API_URL", result.error)


if __name__ == "__main__":
    unittest.main()

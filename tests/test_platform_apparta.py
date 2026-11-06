import json
import unittest
from pathlib import Path

from maps_gluten.platforms.apparta import AppartaAdapter
from maps_gluten.platforms.base import PlaceContext

FIXTURE = Path(__file__).parent / "fixtures" / "apparta_menu.json"


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.data)


def ctx(session):
    return PlaceContext(
        record={},
        place_id="1",
        name="Bar El Bajo",
        website="http://www.barelbajo.cl/",
        menu_url="https://menu.tu-mesa.com/bar-el-bajo/7689/menu?idLinktree=2727",
        order_urls=[],
        session=session,
    )


class AppartaAdapterTest(unittest.TestCase):
    def test_detect_only_apparta(self):
        adapter = AppartaAdapter()
        self.assertTrue(adapter.detect(ctx(None)))
        other = ctx(None)
        other.menu_url = "https://example.com/menu"
        self.assertFalse(adapter.detect(other))

    def test_extract_expands_price_variants_and_labels(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        session = FakeSession(data)
        result = AppartaAdapter().extract(ctx(session))
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.source, "apparta")
        names = [item.name for item in result.items]
        self.assertEqual(names, ["Schop Royal Guard - 350 cc", "Schop Royal Guard - 500 cc", "Mahou (Sin Gluten)"])
        self.assertEqual(result.items[0].price, "$4.500")
        self.assertEqual(result.items[1].price, "$5.500")
        self.assertEqual(result.items[2].price, "$6.200")
        self.assertIn("Sin Gluten", result.items[2].description)
        url, kwargs = session.calls[0]
        self.assertIn("establishment-menu-items", url)
        self.assertEqual(kwargs["params"]["$client[establishment_branch_id]"], "7689")


    def test_extract_accepts_native_lists_from_api(self):
        data = [
            {
                "menu_item_name": "Gin",
                "menu_item_category_name": "Destilados",
                "menu_item_description": "",
                "prices_list": [
                    {"description": "Hendrick's", "price": 8900},
                    {"description": "Bulldog", "price": 7800},
                ],
                "menu_item_labels": [{"label": "Sin Gluten"}],
                "price": 0,
            }
        ]
        result = AppartaAdapter().extract(ctx(FakeSession(data)))
        self.assertEqual(result.status, "ok")
        self.assertEqual([item.name for item in result.items], ["Gin - Hendrick's", "Gin - Bulldog"])
        self.assertIn("Sin Gluten", result.items[0].description)


if __name__ == "__main__":
    unittest.main()

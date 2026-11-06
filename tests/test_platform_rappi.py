import json
import unittest

from maps_gluten.platforms.base import PlaceContext
from maps_gluten.platforms.rappi import RappiAdapter, parse_rappi_menu


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class FakeSession:
    def __init__(self, text):
        self.text = text

    def get(self, url, **kwargs):
        return FakeResponse(self.text)


def ctx(session=None, order_urls=None):
    return PlaceContext(
        record={},
        place_id="1",
        name="Le Grenier",
        website=None,
        menu_url=None,
        order_urls=order_urls or [],
        session=session,
    )


class RappiAdapterTest(unittest.TestCase):
    def test_parse_menu_sections(self):
        menu = {
            "hasMenuSection": [
                {
                    "name": "Especialidades",
                    "hasMenuItem": [
                        {
                            "name": "Sandwich",
                            "description": "Rico",
                            "offers": {"price": 4000},
                        }
                    ],
                }
            ]
        }
        items = parse_rappi_menu(menu)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Sandwich")
        self.assertEqual(items[0].price, "$4.000")
        self.assertEqual(items[0].category, "Especialidades")
        self.assertEqual(items[0].source, "rappi")

    def test_detect_from_order_url(self):
        adapter = RappiAdapter()
        self.assertTrue(
            adapter.detect(
                ctx(order_urls=[{"provider": "Rappi", "url": "https://www.rappi.cl/restaurantes/1-demo"}])
            )
        )

    def test_extract_from_json_ld(self):
        data = {
            "@context": "https://schema.org",
            "@type": "Restaurant",
            "name": "Le Grenier",
            "hasMenu": {
                "hasMenuSection": [
                    {
                        "name": "Cafetería",
                        "hasMenuItem": [{"name": "Café", "offers": {"price": 2500}}],
                    }
                ]
            },
        }
        html = f'<script type="application/ld+json">{json.dumps(data)}</script>'
        result = RappiAdapter().extract(
            ctx(session=FakeSession(html), order_urls=[{"provider": "Rappi", "url": "https://www.rappi.cl/restaurantes/1-demo"}])
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.items[0].name, "Café")
        self.assertEqual(result.items[0].price, "$2.500")


if __name__ == "__main__":
    unittest.main()

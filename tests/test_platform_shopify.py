import json
import unittest
from pathlib import Path

from maps_gluten.platforms.base import PlaceContext
from maps_gluten.platforms.shopify import ShopifyAdapter

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status_code, data=None, text="", headers=None):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.requests = []
        self.ucp_calls = 0
        self.last_headers = {}

    def get(self, url, **kwargs):
        self.requests.append(("GET", url))
        if "products.json" in url:
            return FakeResponse(429, {"errors": [{"message": "too many"}]})
        if url.endswith("/.well-known/ucp"):
            return FakeResponse(
                200,
                {
                    "ucp": {
                        "services": {
                            "dev.ucp.shopping": {
                                "endpoint": "https://shop.myshopify.com/api/ucp/mcp"
                            }
                        }
                    }
                },
            )
        return FakeResponse(404, {})

    def post(self, url, payload=None, **kwargs):
        self.requests.append(("POST", url))
        body = payload or kwargs.get("json") or {}
        if body.get("method") == "initialize":
            return FakeResponse(
                200,
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                headers={"Mcp-Session-Id": "s1"},
            )
        if body.get("method") == "tools/call":
            self.last_headers = kwargs.get("headers") or {}
            self.ucp_calls += 1
            if self.ucp_calls == 1:
                data = json.loads((FIXTURES / "shopify_ucp.json").read_text(encoding="utf-8"))
                return FakeResponse(200, data)
            text = {
                "products": [
                    {
                        "title": "Alfajor",
                        "price_range": {"min": {"amount": 3500, "currency": "CLP"}},
                        "collections": [{"title": "Alfajores"}],
                        "description": {"html": ""},
                    }
                ],
                "pagination": {"has_next_page": False},
            }
            return FakeResponse(
                200,
                {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": json.dumps(text)}]}},
            )
        return FakeResponse(404, {})


def ctx(session):
    return PlaceContext(
        record={},
        place_id="1",
        name="Tienda",
        website="https://shop.myshopify.com",
        menu_url=None,
        order_urls=[],
        session=session,
        max_items=10,
    )


class ShopifyAdapterTest(unittest.TestCase):
    def test_extract_falls_back_to_ucp_after_429(self):
        session = FakeSession()
        result = ShopifyAdapter().extract(ctx(session))
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.source, "shopify")
        self.assertEqual([item.name for item in result.items], ["Torta de chocolate", "Galleta", "Alfajor"])
        self.assertEqual(result.items[0].price, "$12.000")
        self.assertEqual(result.items[2].price, "$3.500")
        self.assertEqual(result.items[0].category, "Tortas")
        self.assertEqual(session.ucp_calls, 2)
        self.assertEqual(session.last_headers.get("Mcp-Session-Id"), "s1")


if __name__ == "__main__":
    unittest.main()

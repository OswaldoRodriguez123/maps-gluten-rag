import unittest

from maps_gluten.platforms import MenuItem, MenuResult, extract
from maps_gluten.platforms.base import PlaceContext


class FakeAdapter:
    name = "fake"

    def detect(self, ctx):
        return True

    def extract(self, ctx):
        return MenuResult("ok", [MenuItem("Producto", "$1.000", source="fake")], "fake")


class FailingAdapter:
    name = "fail"

    def detect(self, ctx):
        return True

    def extract(self, ctx):
        raise RuntimeError("boom")


class PlatformsBaseTest(unittest.TestCase):
    def ctx(self):
        return PlaceContext(
            record={},
            place_id="1",
            name="Local",
            website=None,
            menu_url=None,
            order_urls=[],
        )

    def test_extract_returns_first_ok_adapter(self):
        result = extract(self.ctx(), adapters=[FakeAdapter()])
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.items[0].name, "Producto")
        self.assertEqual(result.source, "fake")

    def test_extract_returns_needs_manual_without_adapters(self):
        result = extract(self.ctx(), adapters=[])
        self.assertEqual(result.status, "needs_manual")
        self.assertEqual(result.items, [])

    def test_extract_continues_after_adapter_error(self):
        result = extract(self.ctx(), adapters=[FailingAdapter(), FakeAdapter()])
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.items[0].name, "Producto")


if __name__ == "__main__":
    unittest.main()

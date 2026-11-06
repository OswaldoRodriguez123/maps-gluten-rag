import unittest

from maps_gluten.platforms.base import PlaceContext
from maps_gluten.platforms.maps_links import links_from_anchors
from maps_gluten.platforms.photos import PhotosAdapter


def ctx(allow_photos=True, dry_run=False):
    return PlaceContext(
        record={"id": "1", "metadata": {"name": "Local", "url": "https://maps"}},
        place_id="1",
        name="Local",
        website=None,
        menu_url=None,
        order_urls=[],
        allow_photos=allow_photos,
        dry_run=dry_run,
    )


class PhotosAdapterTest(unittest.TestCase):
    def test_without_photos_returns_needs_manual(self):
        result = PhotosAdapter().extract(ctx(allow_photos=False))
        self.assertEqual(result.status, "needs_manual")

    def test_dry_run_returns_needs_manual(self):
        result = PhotosAdapter().extract(ctx(dry_run=True))
        self.assertEqual(result.status, "needs_manual")


class MapsLinksTest(unittest.TestCase):
    def test_links_from_anchors(self):
        anchors = [
            {"text": "Carta", "href": "https://menu.fu.do/demo"},
            {"text": "Pedir en línea", "href": "https://www.rappi.cl/restaurantes/123"},
            {"text": "Instagram", "href": "https://instagram.com/demo"},
        ]
        links = links_from_anchors(anchors, website="https://demo.cl")
        self.assertEqual(links["website"], "https://demo.cl")
        self.assertEqual(links["menu"], "https://menu.fu.do/demo")
        self.assertEqual(links["order"][0]["provider"], "Rappi")


if __name__ == "__main__":
    unittest.main()

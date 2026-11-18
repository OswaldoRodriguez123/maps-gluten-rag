import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from maps_gluten import enrich

TODAY = date(2026, 11, 18)
SPA_URL = "https://menu.fu.do/havanna"


class FakePage:
    def __init__(self, websites=None):
        self.current_website = None
        self.websites = websites or {}

    def goto(self, url, **kwargs):
        self.current_website = self.websites.get(url)


def make_place(ftid, name="Havanna", category="Tienda de chocolates", url=None):
    return SimpleNamespace(
        ftid=ftid,
        name=name,
        address=f"Dir {ftid}",
        category=category,
        url=url or f"https://maps/{ftid}",
        website=None,
        website_source=None,
        review_dishes=None,
        dishes=None,
        enriched_at=None,
        enrich_version=None,
    )


def fresh_cache(website, dishes, review_dishes=None, website_source="maps"):
    return {
        "enriched_at": TODAY.isoformat(),
        "enrich_version": enrich.ENRICH_VERSION,
        "website": website,
        "website_source": website_source,
        "dishes": dishes,
        "review_dishes": review_dishes,
    }


def run_with_fakes(places, page, cache, site_dishes_spy):
    with mock.patch.multiple(
        enrich,
        _extract_website=lambda page: getattr(page, "current_website", None),
        _extract_reviews=lambda page: ["own-review"],
        _site_dishes=site_dishes_spy,
        _render_site_products=lambda page, url: [],
    ):
        return enrich.enrich_places(page, places, cache=cache, today=TODAY)


class EnrichGroupsTest(unittest.TestCase):
    def test_case_a_all_stale_fetches_site_once_per_domain(self):
        calls = []

        def fake_site_dishes(url, ocr=False):
            calls.append(url)
            return ["chocolate"]

        places = [make_place(f"h{i}") for i in range(1, 5)]
        page = FakePage({p.url: "https://havanna.cl/" for p in places})
        run_with_fakes(places, page, cache={}, site_dishes_spy=fake_site_dishes)

        self.assertEqual(calls, ["https://havanna.cl/"])
        for place in places:
            self.assertEqual(place.dishes, "chocolate")
            self.assertEqual(place.enriched_at, TODAY.isoformat())
            self.assertEqual(place.review_dishes, "own-review")

    def test_case_b_stale_member_copies_from_fresh_group_brother(self):
        calls = []

        def fake_site_dishes(url, ocr=False):
            calls.append(url)
            return ["chocolate"]

        fresh = {
            p.ftid: p.url for p in [make_place("h2")]
        }
        places = [make_place(f"h{i}") for i in (1, 2, 3, 4)]
        page = FakePage({p.url: "https://havanna.cl/" for p in places})
        cache = {"h2": fresh_cache("https://havanna.cl/", "cache-chocolate", "h2-review")}
        run_with_fakes(places, page, cache=cache, site_dishes_spy=fake_site_dishes)

        self.assertEqual(calls, [])
        for place in places:
            if place.ftid == "h2":
                continue  # fresh: no stale, no touch
            self.assertEqual(place.website, "https://havanna.cl/")
            self.assertEqual(place.website_source, "maps")
            self.assertEqual(place.dishes, "cache-chocolate")
            self.assertEqual(place.enriched_at, TODAY.isoformat())
            self.assertEqual(place.review_dishes, "own-review")

    def test_case_b2_fresh_brother_website_only_no_fetch(self):
        calls = []

        def fake_site_dishes(url, ocr=False):
            calls.append(url)
            return ["chocolate"]

        places = [make_place(f"h{i}") for i in (1, 2, 3, 4)]
        page = FakePage({p.url: "https://havanna.cl/" for p in places})
        cache = {"h2": fresh_cache("https://havanna.cl/", None, None)}
        run_with_fakes(places, page, cache=cache, site_dishes_spy=fake_site_dishes)

        self.assertEqual(calls, [])
        for place in places:
            if place.ftid == "h2":
                continue
            self.assertIsNone(place.dishes)
            self.assertEqual(place.website, "https://havanna.cl/")

    def test_case_c_same_name_distinct_domains_veto_no_sharing(self):
        calls = []

        def fake_site_dishes(url, ocr=False):
            calls.append(url)
            return ["dish-a" if "cafe-a" in url else "dish-b"]

        places = [
            make_place("c1", name="Cafe X", category="Cafetería", url="https://maps/c1"),
            make_place("c2", name="Cafe X", category="Cafetería", url="https://maps/c2"),
        ]
        page = FakePage({"https://maps/c1": "https://cafe-a.cl/", "https://maps/c2": "https://cafe-b.cl/"})
        run_with_fakes(places, page, cache={}, site_dishes_spy=fake_site_dishes)

        self.assertEqual(sorted(calls), ["https://cafe-a.cl/", "https://cafe-b.cl/"])
        dishes = {p.ftid: p.dishes for p in places}
        self.assertEqual(dishes, {"c1": "dish-a", "c2": "dish-b"})


if __name__ == "__main__":
    unittest.main()


class ProvenanceCopyTest(unittest.TestCase):
    def test_fresh_brother_website_source_is_copied_unchanged(self):
        calls = []

        def fake_site_dishes(url, ocr=False):
            calls.append(url)
            return ["chocolate"]

        places = [make_place(f"h{i}") for i in (1, 2, 3, 4)]
        page = FakePage({p.url: "https://havanna.cl/" for p in places})
        cache = {"h2": fresh_cache("https://havanna.cl/", "cache-chocolate", None, website_source="search")}
        run_with_fakes(places, page, cache=cache, site_dishes_spy=fake_site_dishes)

        for place in places:
            if place.ftid == "h2":
                continue
            self.assertEqual(place.website_source, "search")
        self.assertEqual(calls, [])

    def test_enrichment_cache_persists_website_source(self):
        import tempfile
        from pathlib import Path

        from maps_gluten import store
        from maps_gluten.extract import Place

        with tempfile.TemporaryDirectory() as tmp:
            conn = store.connect(Path(tmp) / "t.db")
            place = Place(
                ftid="a", name="X", address=None, category=None, rating=None,
                reviews=None, note=None, url="https://maps", saved_on="2026-11-01",
                website="https://x.cl/", website_source="search",
                dishes="alfajores", enriched_at=TODAY.isoformat(),
                enrich_version=enrich.ENRICH_VERSION,
            )
            store.save(conn, "list", "L", [place], "2026-11-18")
            cache = store.enrichment_cache(conn)
            conn.close()
        self.assertEqual(cache["a"].get("website_source"), "search")

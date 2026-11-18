import unittest
from types import SimpleNamespace

from maps_gluten import cli


def make_place(ftid, name="Havanna", category="Tienda de chocolates", website="https://havanna.cl/"):
    return SimpleNamespace(
        ftid=ftid, name=name, address=f"Dir {ftid}", category=category,
        rating=None, reviews=None, note=None, url=f"https://maps/{ftid}",
        saved_on="2026-11-10", website=website, website_source="maps",
        menu_dishes=None, menu_json=None, menu_at=None,
    )


class CollapseToCanonicalTest(unittest.TestCase):
    def test_targets_collapse_to_group_canonical(self):
        places = [make_place(f"h{i}") for i in (1, 2, 3, 4)]
        collapsed = cli._collapse_to_canonical(places, list(places))
        self.assertEqual([p.ftid for p in collapsed], ["h1"])

    def test_singles_are_kept(self):
        places = [make_place(f"h{i}") for i in (1, 2)] + [
            make_place("x1", name="X Local", category="Cafetería", website="https://x.cl/"),
        ]
        collapsed = cli._collapse_to_canonical(places, list(places))
        self.assertEqual([p.ftid for p in collapsed], ["h1", "x1"])

    def test_unrelated_same_name_places_not_merged(self):
        places = [
            make_place("c1", name="Cafe X", category="Cafetería", website="https://cafe-a.cl/"),
            make_place("c2", name="Cafe X", category="Cafetería", website="https://cafe-b.cl/"),
        ]
        collapsed = cli._collapse_to_canonical(places, list(places))
        self.assertEqual(len(collapsed), 2)


class ChainFanoutTest(unittest.TestCase):
    def test_share_menu_and_photos_from_canonical(self):
        places = [make_place(f"h{i}") for i in (1, 2, 3, 4)]
        canon = places[0]
        canon.menu_dishes = "alfajores"
        canon.menu_json = '[{"name": "Alfajor"}]'
        canon.menu_at = "2026-11-18"
        photo_cache = {"h1": ["https://photo/1", "https://photo/2"]}

        covered = cli._chain_fanout(places, [canon], photo_cache)

        self.assertEqual(covered, {"h1", "h2", "h3", "h4"})
        for place in places:
            self.assertEqual(place.menu_dishes, "alfajores")
            self.assertEqual(place.menu_json, '[{"name": "Alfajor"}]')
            self.assertEqual(place.menu_at, "2026-11-18")
        for ftid in ("h2", "h3", "h4"):
            self.assertEqual(photo_cache[ftid], ["https://photo/1", "https://photo/2"])

    def test_fanout_skips_groups_without_targets(self):
        places = [make_place(f"h{i}") for i in (1, 2, 3, 4)]
        covered = cli._chain_fanout(places, [], photo_cache=None)
        self.assertEqual(covered, set())
        for place in places:
            self.assertIsNone(place.menu_json)


if __name__ == "__main__":
    unittest.main()

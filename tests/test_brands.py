import unittest

from maps_gluten import brands


class Place:
    def __init__(self, ftid, name, category=None, website=None):
        self.ftid = ftid
        self.name = name
        self.category = category
        self.website = website


def places(specs):
    out = []
    for spec in specs:
        ftid, name = spec[0], spec[1]
        cat = spec[2] if len(spec) > 2 else None
        web = spec[3] if len(spec) > 3 else None
        out.append(Place(ftid, name, cat, web))
    return out


class NormalizeTest(unittest.TestCase):
    def test_strips_accents_case_and_punctuation(self):
        self.assertEqual(brands.normalize("Havaná!  Deluxe —"), "havana deluxe")
        self.assertEqual(brands.normalize("  Caf\u00e9   MUJER "), "cafe mujer")

    def test_empty_inputs(self):
        self.assertEqual(brands.normalize(None), "")
        self.assertEqual(brands.normalize("---"), "")


class DomainTest(unittest.TestCase):
    def test_strips_www_and_scheme(self):
        self.assertEqual(brands.domain("https://www.havanna.cl/x"), "havanna.cl")
        self.assertEqual(brands.domain("http://Havanna.cl/"), "havanna.cl")

    def test_invalid_and_none(self):
        self.assertIsNone(brands.domain("no-url"))
        self.assertIsNone(brands.domain(None))
        self.assertIsNone(brands.domain(""))
        self.assertIsNone(brands.domain("ftp://havanna.cl/"))


class FindGroupsTest(unittest.TestCase):
    def test_four_branches_same_category_group_with_min_ftid_canonical(self):
        ps = places([
            ("h3", "Havanna", "Tienda de chocolates", None),
            ("h1", "HAVANNA", "Tienda de Chocolates", None),
            ("h4", "Hâvanna", "Tienda de  chocolates", None),
            ("h2", "Havanna", "tienda de chocolates", None),
        ])
        groups = brands.find_groups(ps)
        self.assertEqual(list(groups), ["h1"])
        self.assertEqual([p.ftid for p in groups["h1"]], ["h1", "h2", "h3", "h4"])

    def test_no_confirmation_no_group(self):
        ps = places([
            ("a", "Havanna", None, None),
            ("b", "Havanna", None, None),
        ])
        self.assertEqual(brands.find_groups(ps), {})

    def test_two_confirm_third_without_data_left_out(self):
        ps = places([
            ("a", "Havanna", "Tienda de chocolates", None),
            ("b", "Havanna", "Tienda de chocolates", None),
            ("c", "Havanna", None, None),
        ])
        groups = brands.find_groups(ps)
        self.assertEqual(list(groups), ["a"])
        self.assertEqual([p.ftid for p in groups["a"]], ["a", "b"])

    def test_distinct_known_domains_veto_bucket_even_with_same_category(self):
        ps = places([
            ("a", "Cafe X", "Cafetería", "https://cafe-a.cl/"),
            ("b", "Cafe X", "Cafetería", "https://cafe-b.cl/"),
        ])
        self.assertEqual(brands.find_groups(ps), {})

    def test_same_domain_without_category_groups(self):
        ps = places([
            ("a", "Havanna", None, "https://www.havanna.cl/"),
            ("b", "Havanna", None, "https://havanna.cl/tienda"),
        ])
        groups = brands.find_groups(ps)
        self.assertEqual([p.ftid for p in groups["a"]], ["a", "b"])

    def test_no_groups_for_distinct_locals(self):
        ps = places([
            ("a", "Alma Chilanga", "Restaurante mexicano", None),
            ("b", "Rakko", "Tienda de alimentos naturales", None),
        ])
        self.assertEqual(brands.find_groups(ps), {})

    def test_share_with_group_copies_only_given_fields(self):
        ps = places([("a", "Havanna"), ("b", "Havanna"), ("c", "Havanna")])
        can = brands.canonical(ps)
        can.menu_json = '[{"name":"x"}]'
        can.dishes = "chocolate"
        brands.share_with_group(ps, can, ("menu_json", "dishes"))
        self.assertEqual([p.menu_json for p in ps], [can.menu_json] * 3)
        self.assertEqual([p.dishes for p in ps], ["chocolate"] * 3)

    def test_canonical_is_lowest_ftid(self):
        ps = places([("z", "Havanna"), ("a", "Havanna"), ("m", "Havanna")])
        self.assertEqual(brands.canonical(ps).ftid, "a")


if __name__ == "__main__":
    unittest.main()

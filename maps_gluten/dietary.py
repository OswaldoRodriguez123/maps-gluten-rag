from __future__ import annotations

import re

DIET_PATTERNS = {
    "sin gluten": re.compile(
        r"\b(sin gluten|libre de gluten|libres de gluten|gluten free|celiac|celíac|celiaco|apto para celiacos?)\b",
        re.I,
    ),
    "vegano": re.compile(r"\b(vegan[oa]?s?|plant based|100% vegetal)\b", re.I),
    "sin lactosa": re.compile(
        r"\b(sin lactosa|libre de lactosa|lactose free|aplv)\b", re.I
    ),
    "sin azúcar": re.compile(r"\b(sin az[uú]car(es)?|sin azucar(es)?)\b", re.I),
}
PLACE_GF_RE = re.compile(r"\b(sin gluten|gluten free|celiac|celíac|celiaco)\b", re.I)


def place_is_gluten_free(name: str, category: str | None) -> bool:
    return bool(PLACE_GF_RE.search(f"{name} {category or ''}"))


def dietary_tags(
    name: str,
    description: str | None,
    category: str | None,
    place_gluten_free: bool,
) -> list[str]:
    text = f"{name} {description or ''}"
    tags: set[str] = set()
    category_upper = (category or "").upper()
    if (
        place_gluten_free
        or DIET_PATTERNS["sin gluten"].search(text)
        or "LIBRES DE GLUTEN" in category_upper
        or "SIN GLUTEN" in category_upper
    ):
        tags.add("sin gluten")
    category_is_vegan = "VEGAN" in category_upper and "GLUTEN" not in category_upper
    if DIET_PATTERNS["vegano"].search(text) or category_is_vegan:
        tags.add("vegano")
    if DIET_PATTERNS["sin lactosa"].search(text) or "SIN LACTOSA" in category_upper:
        tags.add("sin lactosa")
    if (
        DIET_PATTERNS["sin azúcar"].search(text)
        or "SIN AZUCAR" in category_upper
        or "SIN AZÚCAR" in category_upper
    ):
        tags.add("sin azúcar")
    return sorted(tags)

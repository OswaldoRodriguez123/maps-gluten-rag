"""Detección de cadenas/marcas: agrupa sucursales de una misma empresa.

Los grupos se derivan de los datos (nombre normalizado con prefijo de marca
+ categoría o dominio), sin cambios de schema. Sin señal de confirmación no
hay grupo; dos dominios conocidos distintos nunca se conectan directamente
(ver design doc).
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

_NON_ALNUM = re.compile(r"[^a-z0-9 ]")
_SPACES = re.compile(r"\s+")


def _field(obj, key):
    value = getattr(obj, key, None)
    if value is not None:
        return value
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return None


def normalize(text: str | None) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = _NON_ALNUM.sub(" ", value.lower())
    return _SPACES.sub(" ", value).strip()


def domain(url: str | None) -> str | None:
    if not url or "://" not in url:
        return None
    try:
        parsed = urlparse(url.strip().lower())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def canonical(members):
    return min(members, key=lambda p: _field(p, "ftid") or "")


def _tokens(text: str | None) -> list[str]:
    normal = normalize(text)
    return normal.split() if normal else []


GENERIC_TOKENS: frozenset[str] = frozenset({
    "cafe", "coffeeshop", "coffee", "pizza", "pizzeria", "restaurante", "restaurant",
    "burger", "hamburgueseria", "sushi", "heladeria", "pasteleria", "panaderia",
    "sandwicheria", "bar", "comida", "food", "tienda", "local", "casa", "mercado",
    "almacen", "donut", "donuts", "cafeteria", "confiteria", "chocolateria",
    "de", "del", "la", "las", "los", "el", "y", "e", "en", "con",
})


def _prefix_distinctive(t1: list[str], t2: list[str]) -> bool:
    """Prefijo inicial compartido no vacío con al menos un token distintivo."""
    shared = 0
    for a, b in zip(t1, t2):
        if a != b:
            break
        shared += 1
    if shared == 0:
        return False
    return any(tok not in GENERIC_TOKENS for tok in t1[:shared])


def find_groups(places) -> dict:
    items = []
    for place in places:
        tokens = _tokens(_field(place, "name"))
        if not tokens:
            continue
        items.append((
            place,
            tokens,
            normalize(_field(place, "category")),
            domain(_field(place, "website")),
        ))
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            _, t1, cat1, dom1 = items[i]
            _, t2, cat2, dom2 = items[j]
            same_cat = cat1 and cat1 == cat2
            same_dom = dom1 and dom1 == dom2
            if not (same_cat or same_dom):
                continue
            if dom1 and dom2 and dom1 != dom2:
                continue  # veto por arista: dominios conocidos distintos
            if t1 == t2 or _prefix_distinctive(t1, t2):
                union(i, j)

    components: dict[int, list] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(items[i][0])
    groups: dict[str, list] = {}
    for members in components.values():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda p: _field(p, "ftid") or "")
        groups[_field(canonical(ordered), "ftid")] = ordered
    return groups


def share_with_group(members, canon, fields) -> None:
    canon_ftid = _field(canon, "ftid")
    for member in members:
        if _field(member, "ftid") == canon_ftid:
            continue
        for field in fields:
            try:
                setattr(member, field, getattr(canon, field))
            except (AttributeError, TypeError):
                pass

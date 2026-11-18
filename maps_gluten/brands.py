"""Detección de cadenas/marcas: agrupa sucursales de una misma empresa.

Los grupos se derivan de los datos (nombre normalizado + categoría o dominio),
sin cambios de schema. Sin señal de confirmación no hay grupo; dominios
conocidos y distintos vetan al nombre completo (ver design doc).
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


def find_groups(places) -> dict:
    buckets: dict[str, list] = {}
    for place in places:
        name = normalize(_field(place, "name"))
        if name:
            buckets.setdefault(name, []).append(place)
    groups: dict[str, list] = {}
    for members in buckets.values():
        if len(members) < 2:
            continue
        domains = [domain(_field(m, "website")) for m in members]
        known = {d for d in domains if d}
        if len(known) > 1:
            continue  # veto: dominios distintos conocidos → no hay grupo
        cats = [normalize(_field(m, "category")) for m in members]
        n = len(members)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        for i in range(n):
            for j in range(i + 1, n):
                same_cat = cats[i] and cats[i] == cats[j]
                same_dom = domains[i] and domains[i] == domains[j]
                if same_cat or same_dom:
                    union(i, j)
        components: dict[int, list] = {}
        for i in range(n):
            components.setdefault(find(i), []).append(members[i])
        for component in components.values():
            if len(component) < 2:
                continue
            ordered = sorted(component, key=lambda p: _field(p, "ftid") or "")
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

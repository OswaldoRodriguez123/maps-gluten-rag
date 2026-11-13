from __future__ import annotations

import html
import json
import re

from ..net import fetch_capped, guarded_session

from .base import MenuItem, MenuResult, PlaceContext

RAPPI_HOST = "rappi.cl/restaurantes/"


def _clean(value) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _clp(value) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return f"${int(round(number)):,}".replace(",", ".")


def _items(node, category: str | None, out: list[MenuItem]) -> None:
    if isinstance(node, list):
        for value in node:
            _items(value, category, out)
        return
    if not isinstance(node, dict):
        return
    kind = node.get("@type")
    if kind == "MenuSection" or ("hasMenuItem" in node and not kind):
        _items(node.get("hasMenuItem"), _clean(node.get("name")) or category, out)
        return
    if kind == "MenuItem" or (node.get("name") and ("offers" in node or "price" in node)):
        offers = node.get("offers") or {}
        if offers is None and node.get("price") is not None:
            offers = {"price": node.get("price")}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if not isinstance(offers, dict):
            offers = {}
        name = _clean(node.get("name"))
        if name:
            out.append(
                MenuItem(
                    name=name,
                    price=_clp(offers.get("price")),
                    category=category,
                    description=_clean(node.get("description")) or None,
                    source="rappi",
                )
            )
        return
    for key in ("hasMenu", "hasMenuSection", "hasMenuItem"):
        if key in node:
            _items(node[key], category, out)


def parse_rappi_menu(menu) -> list[MenuItem]:
    out: list[MenuItem] = []
    _items(menu, None, out)
    return out


class RappiAdapter:
    name = "rappi"

    def _urls(self, ctx: PlaceContext) -> list[str]:
        urls = []
        for entry in ctx.order_urls or []:
            url = (entry or {}).get("url") or ""
            if RAPPI_HOST in url.lower() or (entry or {}).get("provider", "").lower() == "rappi":
                urls.append(url)
        for value in (ctx.menu_url, ctx.website):
            if value and RAPPI_HOST in value.lower():
                urls.append(value)
        return list(dict.fromkeys(url for url in urls if url))

    def detect(self, ctx: PlaceContext) -> bool:
        return bool(self._urls(ctx))

    def extract(self, ctx: PlaceContext) -> MenuResult:
        urls = self._urls(ctx)
        if not urls:
            return MenuResult("empty", [], "rappi")
        session = ctx.session or guarded_session()
        for url in urls:
            try:
                response = fetch_capped(session,
                    url,
                    headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "es-CL,es;q=0.9"},
                    timeout=60,
                )
            except Exception:
                continue
            if getattr(response, "status_code", 200) != 200:
                continue
            text = response.text or ""
            for raw in re.findall(
                r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
                text,
                re.S | re.I,
            ):
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                objects = data if isinstance(data, list) else [data]
                for obj in objects:
                    if not isinstance(obj, dict) or obj.get("@type") != "Restaurant":
                        continue
                    items = parse_rappi_menu(obj.get("hasMenu"))
                    if items:
                        for item in items:
                            item.url = url
                        return MenuResult("ok", items[: ctx.max_items], "rappi", url)
        return MenuResult("empty", [], "rappi", urls[0] if urls else None)

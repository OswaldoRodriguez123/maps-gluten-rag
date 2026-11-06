from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin, urlparse

import requests

from .base import MenuItem, MenuResult, PlaceContext

PRODUCT_PATH = re.compile(
    r"/(products?|productos?|p|item|catalogo|catalog)/", re.IGNORECASE
)
LISTING_PATHS = ("/shop", "/tienda", "/productos", "/catalogo", "/collections/all")


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


def _price_from_offers(offers):
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        return None
    for key in ("price", "lowPrice", "highPrice"):
        if offers.get(key) is not None:
            return offers[key]
    return None


def _products_from_json(data, found: list[MenuItem]) -> None:
    if isinstance(data, dict):
        types = data.get("@type")
        types = types if isinstance(types, list) else [types]
        if "Product" in types:
            name = _clean(data.get("name"))
            if name:
                found.append(
                    MenuItem(
                        name=name,
                        price=_clp(_price_from_offers(data.get("offers"))),
                        category=_clean(data.get("category")) or None,
                        description=_clean(data.get("description")) or None,
                        source="web-jsonld",
                    )
                )
        elif "ProductGroup" in types:
            name = _clean(data.get("name"))
            variants = data.get("hasVariant") or []
            if isinstance(variants, dict):
                variants = [variants]
            if name:
                price = _clp(_price_from_offers(data.get("offers")))
                if not price:
                    price = next(
                        (
                            _clp(_price_from_offers(variant.get("offers")))
                            for variant in variants
                            if isinstance(variant, dict)
                            and _price_from_offers(variant.get("offers"))
                        ),
                        None,
                    )
                found.append(
                    MenuItem(
                        name=name,
                        price=price,
                        category=_clean(data.get("category")) or None,
                        description=_clean(data.get("description")) or None,
                        source="web-jsonld",
                    )
                )
        for value in data.values():
            _products_from_json(value, found)
    elif isinstance(data, list):
        for value in data:
            _products_from_json(value, found)


def parse_products(html_text: str) -> list[MenuItem]:
    found: list[MenuItem] = []
    for raw in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        re.I | re.S,
    ):
        try:
            _products_from_json(json.loads(raw), found)
        except (json.JSONDecodeError, TypeError):
            continue
    return found


def _product_links(html_text: str, base: str) -> list[str]:
    links: list[str] = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html_text, re.I):
        full = urljoin(base, html.unescape(href))
        if urlparse(full).netloc != urlparse(base).netloc:
            continue
        if PRODUCT_PATH.search(urlparse(full).path) and full not in links:
            links.append(full)
    return links


class JsonLdAdapter:
    name = "jsonld"

    def detect(self, ctx: PlaceContext) -> bool:
        return bool(ctx.website)

    def extract(self, ctx: PlaceContext) -> MenuResult:
        if not ctx.website:
            return MenuResult("empty", [], "web-jsonld")
        session = ctx.session or requests.Session()
        headers = {"User-Agent": "Mozilla/5.0 (compatible; maps-gluten-rag/1.0)"}
        items: list[MenuItem] = []
        seen = set()

        def add(values: list[MenuItem]) -> None:
            for item in values:
                key = item.name.casefold()
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)

        urls = [ctx.website] + [urljoin(ctx.website, path) for path in LISTING_PATHS]
        product_links: list[str] = []
        for url in urls:
            if len(items) >= ctx.max_items:
                break
            try:
                response = session.get(url, headers=headers, timeout=25)
                if response.status_code != 200:
                    continue
            except Exception:
                continue
            add(parse_products(response.text))
            if len(product_links) < 40:
                for link in _product_links(response.text, response.url):
                    if link not in product_links:
                        product_links.append(link)

        for link in product_links[: min(40, ctx.max_items)]:
            if len(items) >= ctx.max_items:
                break
            try:
                response = session.get(link, headers=headers, timeout=25)
                if response.status_code != 200:
                    continue
            except Exception:
                continue
            add(parse_products(response.text))

        for item in items:
            item.url = ctx.website
        if not items:
            return MenuResult("empty", [], "web-jsonld", ctx.website)
        return MenuResult("ok", items[: ctx.max_items], "web-jsonld", ctx.website)

from __future__ import annotations

import html
import json
import re
from urllib.parse import urlparse

import requests

from .base import MenuItem, MenuResult, PlaceContext
from .jsonld import parse_products

GENERIC_COLLECTIONS = {
    "todos nuestros productos",
    "sin gluten",
    "novedades",
    "destacados",
    "ofertas",
    "todo",
}


class _RateLimited(Exception):
    pass


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


def _base(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _category(product: dict) -> str | None:
    collections = [
        _clean(collection.get("title"))
        for collection in product.get("collections") or []
        if isinstance(collection, dict) and collection.get("title")
    ]
    specific = [
        title for title in collections if title.casefold() not in GENERIC_COLLECTIONS
    ]
    if specific:
        return specific[-1].capitalize()
    if collections:
        return collections[0].capitalize()
    product_type = _clean(product.get("product_type"))
    return product_type or None


def _description(product: dict) -> str | None:
    description = product.get("description")
    if isinstance(description, dict):
        description = description.get("html")
    return _clean(description) or None


def _ucp_item(product: dict) -> MenuItem | None:
    title = _clean(product.get("title"))
    if not title:
        return None
    price_range = product.get("price_range") or {}
    amount = (price_range.get("min") or {}).get("amount")
    return MenuItem(
        name=title,
        price=_clp(amount),
        category=_category(product),
        description=_description(product),
        url=product.get("url"),
        source="shopify",
    )


class ShopifyAdapter:
    name = "shopify"

    def detect(self, ctx: PlaceContext) -> bool:
        if not ctx.website:
            return False
        session = ctx.session or requests.Session()
        base = _base(ctx.website)
        try:
            profile = session.get(f"{base}/.well-known/ucp", timeout=25)
            if profile.status_code == 200:
                return True
        except Exception:
            pass
        try:
            response = session.get(f"{base}/products.json?limit=1", timeout=25)
            if response.status_code in (200, 429):
                return True
        except Exception:
            pass
        try:
            home = session.get(ctx.website, timeout=25)
            text = (home.text or "").lower()
            return "shopify" in text or "cdn.shopify.com" in text
        except Exception:
            return False

    def _products_json(self, ctx: PlaceContext, base: str, session) -> list[MenuItem]:
        items: list[MenuItem] = []
        for page in range(1, 21):
            response = session.get(
                f"{base}/products.json",
                params={"limit": 250, "page": page},
                timeout=40,
            )
            if response.status_code in (403, 429):
                raise _RateLimited()
            if response.status_code != 200:
                break
            data = response.json()
            products = data.get("products") if isinstance(data, dict) else None
            if not isinstance(products, list) or not products:
                break
            for product in products:
                title = _clean(product.get("title"))
                if not title:
                    continue
                variants = product.get("variants") or []
                price = None
                for variant in variants:
                    if variant.get("available") and variant.get("price") is not None:
                        price = variant.get("price")
                        break
                if price is None and variants:
                    price = variants[0].get("price")
                tags = product.get("tags") or []
                category = _clean(product.get("product_type")) or (
                    _clean(tags[0]) if tags else None
                )
                items.append(
                    MenuItem(
                        name=title,
                        price=_clp(price),
                        category=category,
                        description=_clean(product.get("body_html")) or None,
                        url=ctx.website,
                        source="shopify",
                    )
                )
                if len(items) >= ctx.max_items:
                    return items
            if len(products) < 250:
                break
        return items

    def _ucp(self, ctx: PlaceContext, base: str, session) -> list[MenuItem]:
        profile_response = session.get(f"{base}/.well-known/ucp", timeout=30)
        if profile_response.status_code != 200:
            return []
        profile = profile_response.json()
        services = (profile.get("ucp") or {}).get("services") or {}
        endpoints = [
            service.get("endpoint")
            for service in services.get("dev.ucp.shopping") or []
            if isinstance(service, dict) and service.get("endpoint")
        ]
        if not endpoints:
            return []
        endpoint = endpoints[0]
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        session.post(
            endpoint,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "maps-gluten-rag", "version": "1.0"},
                },
            },
            headers=headers,
            timeout=60,
        )
        items: list[MenuItem] = []
        cursor = None
        for page in range(1, 51):
            catalog = {
                "filters": {"available": False},
                "pagination": {"limit": 100},
                "context": {
                    "address_country": "CL",
                    "language": "es-CL",
                    "currency": "CLP",
                },
            }
            if cursor:
                catalog["pagination"]["cursor"] = cursor
            response = session.post(
                endpoint,
                json={
                    "jsonrpc": "2.0",
                    "id": page + 1,
                    "method": "tools/call",
                    "params": {
                        "name": "search_catalog",
                        "arguments": {
                            "meta": {
                                "ucp-agent": {
                                    "profile": f"{base}/.well-known/ucp"
                                }
                            },
                            "catalog": catalog,
                        },
                    },
                },
                headers=headers,
                timeout=90,
            )
            if response.status_code != 200:
                break
            payload = response.json()
            content = ((payload.get("result") or {}).get("content") or [])
            text = next(
                (
                    item.get("text")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ),
                None,
            )
            if not text:
                break
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                break
            for product in data.get("products") or []:
                item = _ucp_item(product)
                if item:
                    items.append(item)
                if len(items) >= ctx.max_items:
                    return items
            pagination = data.get("pagination") or {}
            if not pagination.get("has_next_page"):
                break
            cursor = pagination.get("cursor")
            if not cursor:
                break
        return items

    def _sitemap(self, ctx: PlaceContext, base: str, session) -> list[MenuItem]:
        if not ctx.browser:
            return []
        try:
            index = session.get(f"{base}/sitemap.xml", timeout=30)
            if index.status_code != 200:
                return []
        except Exception:
            return []
        maps = [
            html.unescape(url)
            for url in re.findall(r"<loc>(.*?)</loc>", index.text)
            if "sitemap_products" in url
        ]
        product_urls: list[str] = []
        for url in maps:
            try:
                response = session.get(url, timeout=30)
                product_urls.extend(re.findall(r"<loc>(.*?)</loc>", response.text))
            except Exception:
                continue
        items: list[MenuItem] = []
        for url in dict.fromkeys(product_urls):
            if len(items) >= ctx.max_items:
                break
            page = ctx.browser.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60)
                page.wait_for_timeout(800)
                scripts = page.eval_on_selector_all(
                    'script[type="application/ld+json"]',
                    "els => els.map(e => e.textContent)",
                )
            except Exception:
                continue
            finally:
                page.close()
            for raw in scripts:
                for item in parse_products(f'<script type="application/ld+json">{raw}</script>'):
                    item.source = "shopify"
                    item.url = url
                    if item.name.casefold() not in {existing.name.casefold() for existing in items}:
                        items.append(item)
        return items

    def extract(self, ctx: PlaceContext) -> MenuResult:
        if not ctx.website:
            return MenuResult("empty", [], "shopify")
        session = ctx.session or requests.Session()
        base = _base(ctx.website)
        items: list[MenuItem] = []
        try:
            items = self._products_json(ctx, base, session)
        except _RateLimited:
            items = []
        except Exception:
            items = []
        if not items:
            try:
                items = self._ucp(ctx, base, session)
            except Exception:
                items = []
        if not items:
            try:
                items = self._sitemap(ctx, base, session)
            except Exception:
                items = []
        if not items:
            return MenuResult("empty", [], "shopify", ctx.website)
        return MenuResult("ok", items[: ctx.max_items], "shopify", ctx.website)

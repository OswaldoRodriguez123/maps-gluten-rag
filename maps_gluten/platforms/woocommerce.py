from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from ..net import fetch_capped, guarded_session

from .base import MenuItem, MenuResult, PlaceContext


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


class WooCommerceAdapter:
    name = "woocommerce"

    def detect(self, ctx: PlaceContext) -> bool:
        if not ctx.website:
            return False
        session = ctx.session or guarded_session()
        try:
            response = fetch_capped(session,
                f"{_base(ctx.website)}/wp-json/wc/store/products?per_page=1",
                timeout=25,
            )
            return response.status_code == 200 and isinstance(response.json(), list)
        except Exception:
            return False

    def extract(self, ctx: PlaceContext) -> MenuResult:
        if not ctx.website:
            return MenuResult("empty", [], "woocommerce")
        session = ctx.session or guarded_session()
        base = _base(ctx.website)
        items: list[MenuItem] = []
        seen = set()
        for page in range(1, 51):
            try:
                response = fetch_capped(session,
                    f"{base}/wp-json/wc/store/products",
                    params={"per_page": 100, "page": page},
                    timeout=40,
                )
                data = response.json()
            except Exception:
                break
            if not isinstance(data, list) or not data:
                break
            for product in data:
                name = _clean(product.get("name"))
                if not name:
                    continue
                prices = product.get("prices") or {}
                raw = prices.get("price")
                try:
                    minor = int(prices.get("currency_minor_unit") or 0)
                    price = _clp(float(raw) / (10**minor)) if raw is not None else None
                except (TypeError, ValueError):
                    price = None
                categories = [
                    _clean(category.get("name"))
                    for category in product.get("categories") or []
                    if category.get("name")
                ]
                key = name.casefold()
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    MenuItem(
                        name=name,
                        price=price,
                        category=categories[0] if categories else None,
                        description=_clean(
                            product.get("short_description") or product.get("description")
                        )
                        or None,
                        url=ctx.website,
                        source="woocommerce",
                    )
                )
                if len(items) >= ctx.max_items:
                    break
            if len(data) < 100 or len(items) >= ctx.max_items:
                break
        if not items:
            return MenuResult("empty", [], "woocommerce", ctx.website)
        return MenuResult("ok", items, "woocommerce", ctx.website)

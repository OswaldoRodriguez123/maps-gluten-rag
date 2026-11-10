from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import requests

from .base import MenuItem, MenuResult, PlaceContext


class UberEatsAdapter:
    name = "ubereats"

    def detect(self, ctx: PlaceContext) -> bool:
        for entry in ctx.order_urls or []:
            url = (entry.get("url") or "").lower()
            if "ubereats.com" in url:
                return True
        return False

    def _store_id(self, ctx: PlaceContext) -> str | None:
        for entry in ctx.order_urls or []:
            url = entry.get("url") or ""
            if "ubereats.com" not in url.lower():
                continue
            match = re.search(r"/store/[^/]+/([^/?]+)", url)
            if match:
                return match.group(1)
        return None

    def extract(self, ctx: PlaceContext) -> MenuResult:
        store_id = self._store_id(ctx)
        if not store_id:
            return MenuResult("empty", [], "ubereats", error="sin store id")
        base = os.getenv("UBER_EATS_API_URL", "").strip().rstrip("/")
        if not base:
            return MenuResult(
                "error", [], "ubereats",
                error="UBER_EATS_API_URL no configurado (requiere el proxy/scraper de Uber Eats)",
            )
        url = f"{base}/stores/menu"
        try:
            response = (ctx.session or requests).get(
                url, params={"store": store_id}, timeout=30
            )
            response.raise_for_status()
            data = response.json()
        except Exception as error:  # noqa: BLE001
            return MenuResult("error", [], "ubereats", error=f"{type(error).__name__}: {error}"[:180])
        items: list[MenuItem] = []
        for section in data.get("sections", []) or []:
            for category in section.get("categories", []) or []:
                cat_title = category.get("title")
                for item in category.get("items", []) or []:
                    name = (item.get("name") or "").strip()
                    if not name:
                        continue
                    price = item.get("price")
                    price_str = None
                    if price is not None:
                        try:
                            price_str = f"${int(round(float(price))):,}".replace(",", ".")
                        except (TypeError, ValueError):
                            price_str = str(price)
                    items.append(
                        MenuItem(
                            name=name,
                            price=price_str,
                            category=cat_title,
                            description=item.get("description"),
                            url=item.get("link"),
                            source="ubereats",
                        )
                    )
                    if len(items) >= ctx.max_items:
                        break
                if len(items) >= ctx.max_items:
                    break
            if len(items) >= ctx.max_items:
                break
        if not items:
            return MenuResult("empty", [], "ubereats", url=f"{base}/stores/menu?store={store_id}")
        return MenuResult("ok", items[:ctx.max_items], "ubereats", url=f"{base}/stores/menu?store={store_id}")

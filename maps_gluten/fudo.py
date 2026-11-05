from __future__ import annotations

import json
import re

from playwright.sync_api import sync_playwright

API_HOST = "integrations.fu.do"


def _price(value) -> str | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return f"${number:,}".replace(",", ".")


def fetch_menu(url: str, timeout: int = 90) -> list[dict]:
    """Lee el catálogo de una tienda Fudo (menu.fu.do) desde su API interna."""
    captured: dict[str, str] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="es-CL", viewport={"width": 1400, "height": 1000})

        def on_response(response):
            if API_HOST not in response.url:
                return
            try:
                body = response.text()
            except Exception:
                return
            if "/products/" in response.url:
                captured["products"] = body
            elif "/product-categories/" in response.url:
                captured["categories"] = body

        page.on("response", on_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            page.wait_for_timeout(3000)
        finally:
            browser.close()

    if "products" not in captured:
        return []
    try:
        products = json.loads(captured["products"]).get("products") or []
    except (json.JSONDecodeError, TypeError):
        return []
    categories: dict[int, str] = {}
    if "categories" in captured:
        try:
            for category in json.loads(captured["categories"]).get("productCategories") or []:
                categories[category.get("id")] = category.get("name")
        except (json.JSONDecodeError, TypeError):
            categories = {}

    items: list[dict] = []
    seen: set[str] = set()
    for product in products:
        name = str(product.get("name") or "").strip()
        if not name:
            continue
        key = re.sub(r"\s+", " ", name).lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "name": name,
                "price": _price(product.get("price")),
                "category": categories.get(product.get("productCategoryId")),
                "description": product.get("description") or None,
                "source": "fudo",
            }
        )
    return items

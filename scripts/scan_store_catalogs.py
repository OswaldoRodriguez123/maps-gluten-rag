from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


def clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def format_clp(value) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return f"${int(round(number)):,}".replace(",", ".")


def fetch(url: str, session: requests.Session, timeout: int = 25):
    response = session.get(url, headers={"User-Agent": UA}, timeout=timeout)
    response.raise_for_status()
    return response


def shopify_products(base: str, session: requests.Session) -> list[dict]:
    response = fetch(f"{base}/products.json?limit=250", session)
    payload = response.json()
    products = payload.get("products") or []
    items = []
    for product in products:
        name = html.unescape((product.get("title") or "").strip())
        if not name:
            continue
        variants = product.get("variants") or []
        price = None
        available = False
        for variant in variants:
            if variant.get("available"):
                available = True
                price = variant.get("price") or price
        if price is None and variants:
            price = variants[0].get("price")
        category = (product.get("product_type") or "").strip() or None
        tags = product.get("tags") or []
        if not category and tags:
            category = tags[0]
        items.append(
            {
                "name": name,
                "price": format_clp(price),
                "category": category,
                "description": clean_html(product.get("body_html") or "") or None,
                "source": "shopify",
                "available": available,
            }
        )
    return items


def woo_products(base: str, session: requests.Session) -> list[dict]:
    items = []
    for page in range(1, 4):
        response = fetch(
            f"{base}/wp-json/wc/store/products?per_page=100&page={page}", session
        )
        products = response.json()
        if not isinstance(products, list) or not products:
            break
        for product in products:
            name = html.unescape((product.get("name") or "").strip())
            if not name:
                continue
            prices = product.get("prices") or {}
            raw_price = prices.get("price")
            minor = int(prices.get("currency_minor_unit") or 0)
            price = None
            if raw_price is not None:
                try:
                    price = format_clp(float(raw_price) / (10**minor))
                except (TypeError, ValueError):
                    price = None
            categories = [
                html.unescape((category.get("name") or "").strip())
                for category in product.get("categories") or []
                if category.get("name")
            ]
            items.append(
                {
                    "name": name,
                    "price": price,
                    "category": categories[0] if categories else None,
                    "description": clean_html(
                        product.get("short_description") or product.get("description") or ""
                    )
                    or None,
                    "source": "woocommerce",
                    "available": product.get("is_in_stock", True),
                }
            )
        if len(products) < 100:
            break
    return items


def dedupe(items: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for item in items:
        key = re.sub(r"\s+", " ", item["name"].casefold()).strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Busca catálogos Shopify/WooCommerce.")
    parser.add_argument("--places", default="data/mis_lugares_sin_gluten.jsonl")
    parser.add_argument("--out", default="reports/store_catalog_scan.jsonl")
    args = parser.parse_args()

    places = [
        json.loads(line)
        for line in Path(args.places).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    targets = [
        place
        for place in places
        if (place["metadata"].get("menu_count") or 0) == 0
        and not (place["metadata"].get("place_categories") or [])
        and place["metadata"].get("website")
    ]
    session = requests.Session()
    results = []
    for place in targets:
        metadata = place["metadata"]
        url = metadata["website"]
        if "casaroque" in url:
            url = "https://www.casaroque.cl/"
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        result = {
            "place": metadata["name"],
            "url": url,
            "platform": "unknown",
            "items": [],
            "error": None,
        }
        try:
            woo = woo_products(base, session)
        except Exception:
            woo = []
        if woo:
            result["platform"] = "woocommerce"
            result["items"] = dedupe(woo)
        else:
            try:
                shopify = shopify_products(base, session)
            except Exception as error:
                shopify = []
                result["error"] = f"{type(error).__name__}: {error}"[:180]
            if shopify:
                result["platform"] = "shopify"
                result["items"] = dedupe(shopify)
        print(
            f"{metadata['name']}: {result['platform']} · {len(result['items'])} ítems",
            flush=True,
        )
        results.append(result)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in results) + "\n",
        encoding="utf-8",
    )
    print(f"\nResultados: {out}")
    for row in results:
        if row["items"]:
            print(f"- {row['place']} ({row['platform']}): {len(row['items'])}")
            for item in row["items"][:3]:
                print(f"    {item['name']} | {item['price']} | {item['category']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
PRODUCT_PATH = re.compile(
    r"/(products?|productos?|p|item|catalogo|catalog)/", re.IGNORECASE
)
LISTING_PATHS = (
    "/collections/all",
    "/collections",
    "/shop",
    "/tienda",
    "/productos",
    "/catalogo",
)


def clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def format_price(value) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return f"${int(round(number)):,}".replace(",", ".")


def price_from_offers(offers):
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        return None
    for key in ("price", "lowPrice", "highPrice"):
        if offers.get(key) is not None:
            return offers[key]
    return None


def products_from_json(data, found: list[dict]) -> None:
    if isinstance(data, dict):
        types = data.get("@type")
        types = types if isinstance(types, list) else [types]
        if "Product" in types:
            name = clean_html(str(data.get("name") or ""))
            if name:
                found.append(
                    {
                        "name": name,
                        "price": format_price(price_from_offers(data.get("offers"))),
                        "category": clean_html(str(data.get("category") or "")) or None,
                        "description": clean_html(str(data.get("description") or ""))
                        or None,
                        "source": "web-product",
                    }
                )
        elif "ProductGroup" in types:
            name = clean_html(str(data.get("name") or ""))
            variants = data.get("hasVariant") or []
            if isinstance(variants, dict):
                variants = [variants]
            if name and variants:
                found.append(
                    {
                        "name": name,
                        "price": format_price(price_from_offers(data.get("offers")))
                        or next(
                            (
                                format_price(price_from_offers(v.get("offers")))
                                for v in variants
                                if isinstance(v, dict)
                                and price_from_offers(v.get("offers"))
                            ),
                            None,
                        ),
                        "category": clean_html(str(data.get("category") or "")) or None,
                        "description": clean_html(str(data.get("description") or ""))
                        or None,
                        "source": "web-product",
                    }
                )
        for value in data.values():
            products_from_json(value, found)
    elif isinstance(data, list):
        for value in data:
            products_from_json(value, found)


def page_products(html_text: str) -> list[dict]:
    found: list[dict] = []
    for raw in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        re.I | re.S,
    ):
        try:
            products_from_json(json.loads(raw), found)
        except (json.JSONDecodeError, TypeError):
            continue
    if found:
        return found
    title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html_text, re.I)
    price = re.search(
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)',
        html_text,
        re.I,
    )
    desc = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
        html_text,
        re.I,
    )
    if title:
        found.append(
            {
                "name": html.unescape(title.group(1)).strip(),
                "price": format_price(price.group(1)) if price else None,
                "category": None,
                "description": html.unescape(desc.group(1)).strip() if desc else None,
                "source": "web-product",
            }
        )
    return found


def dedupe(items: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for item in items:
        key = re.sub(r"\s+", " ", (item.get("name") or "").casefold()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Rastrea fichas de producto por JSON-LD.")
    parser.add_argument("--places", default="data/mis_lugares_sin_gluten.jsonl")
    parser.add_argument("--out", default="reports/web_product_crawl.jsonl")
    parser.add_argument("--max-products", type=int, default=40)
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
    session.headers["User-Agent"] = UA
    results = []
    for place in targets:
        metadata = place["metadata"]
        url = metadata["website"]
        if "casaroque" in url:
            url = "https://www.casaroque.cl/"
        try:
            home = session.get(url, timeout=25)
            home.raise_for_status()
        except Exception as error:
            results.append(
                {
                    "place": metadata["name"],
                    "url": url,
                    "items": [],
                    "error": f"{type(error).__name__}: {error}"[:180],
                }
            )
            print(f"{metadata['name']}: ERROR {type(error).__name__}", flush=True)
            continue
        final = home.url
        parsed = urlparse(final)
        base = f"{parsed.scheme}://{parsed.netloc}"
        pages = [final] + [urljoin(final, path) for path in LISTING_PATHS]
        product_links: list[str] = []
        for page_url in pages:
            try:
                page = session.get(page_url, timeout=25)
            except Exception:
                continue
            for href in re.findall(r'href=["\']([^"\']+)["\']', page.text, re.I):
                full = urljoin(page.url, html.unescape(href))
                if urlparse(full).netloc != parsed.netloc:
                    continue
                if PRODUCT_PATH.search(urlparse(full).path) and full not in product_links:
                    product_links.append(full)
            if len(product_links) >= args.max_products:
                break
        items: list[dict] = []
        for link in product_links[: args.max_products]:
            try:
                response = session.get(link, timeout=25)
                items.extend(page_products(response.text))
            except Exception:
                continue
        items = dedupe(items)[: args.max_products]
        result = {
            "place": metadata["name"],
            "url": final,
            "items": items,
            "error": None,
        }
        print(f"{metadata['name']}: {len(items)} productos · {final}", flush=True)
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
            print(f"- {row['place']}: {len(row['items'])}")
            for item in row["items"][:3]:
                print(f"    {item['name']} | {item['price']} | {item['category']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from playwright.sync_api import sync_playwright  # noqa: E402

from maps_gluten import enrich  # noqa: E402
from normalize_menus import parse_price  # noqa: E402

URL_FIXES = {
    "Casa Roque Chocolates": [
        "https://www.casaroque.cl/",
        "https://casaroque.cl/",
    ],
}


def _items_from_names(names: list[str]) -> list[dict]:
    items = []
    seen = set()
    for name in names:
        clean = re.sub(r"\s+", " ", name or "").strip()
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        price_value, currency, _ = parse_price(clean)
        price = None
        if price_value is not None:
            price = (
                f"${int(price_value):,}".replace(",", ".")
                if currency == "CLP"
                else str(price_value)
            )
        items.append(
            {
                "name": clean,
                "price": price,
                "category": None,
                "description": None,
                "source": "web-render",
            }
        )
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Busca cartas en las webs sin menú.")
    parser.add_argument("--places", default="data/mis_lugares_sin_gluten.jsonl")
    parser.add_argument("--out", default="reports/web_menu_scan.jsonl")
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
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for place in targets:
            metadata = place["metadata"]
            name = metadata["name"]
            urls = [metadata["website"]] + URL_FIXES.get(name, [])
            result = {"place": name, "url": metadata["website"], "method": "none", "items": [], "error": None}
            method = "none"
            items: list[dict] = []
            error = None
            for url in urls:
                try:
                    structured = enrich._site_menu(url)
                except Exception as exc:
                    structured = []
                    error = f"{type(exc).__name__}: {exc}"[:180]
                if structured:
                    method = "json-ld"
                    items = structured
                    result["url"] = url
                    break
                page = browser.new_page(locale="es-CL", viewport={"width": 1400, "height": 1000})
                try:
                    names = enrich._render_site_products(page, url)
                except Exception as exc:
                    names = []
                    error = f"{type(exc).__name__}: {exc}"[:180]
                finally:
                    page.close()
                if names:
                    method = "render"
                    items = _items_from_names(names)
                    result["url"] = url
                    break
            result["method"] = method
            result["items"] = items
            result["error"] = error
            print(f"{name}: {method} · {len(items)} ítems · {result['url']}", flush=True)
            results.append(result)
        browser.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in results) + "\n",
        encoding="utf-8",
    )
    print(f"\nResultados: {out}")
    for row in results:
        if row["items"]:
            print(f"- {row['place']} ({row['method']}): {len(row['items'])}")
            for item in row["items"][:3]:
                print(f"    {item.get('name')} | {item.get('price')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

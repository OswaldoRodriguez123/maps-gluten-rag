from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def main() -> int:
    parser = argparse.ArgumentParser(description="Busca links de carta/pedido en Google Maps.")
    parser.add_argument("--places", default="data/mis_lugares_sin_gluten.jsonl")
    parser.add_argument("--out", default="reports/noweb_scan.jsonl")
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
        and not place["metadata"].get("website")
    ]
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for place in targets:
            metadata = place["metadata"]
            url = f"{metadata['url']}&hl=es&gl=CL"
            result = {
                "place": metadata["name"],
                "links": [],
                "buttons": [],
                "providers": [],
                "snippets": {},
                "error": None,
            }
            page = browser.new_page(locale="es-CL", viewport={"width": 1400, "height": 1000})
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                text = page.inner_text("body")
                for keyword in ("Carta", "Pedir en línea", "Sitio web", "Menú"):
                    index = text.find(keyword)
                    result["snippets"][keyword] = (
                        text[max(0, index - 100) : index + 220].replace("\n", " | ")
                        if index >= 0
                        else None
                    )
                anchors = page.eval_on_selector_all(
                    "a",
                    """els => els.map(e => ({text:(e.innerText||'').trim().slice(0,80), href:e.href}))
                        .filter(x => x.href && !x.href.includes('google.'))""",
                )
                seen = set()
                for anchor in anchors:
                    key = (anchor["text"], anchor["href"])
                    if key in seen:
                        continue
                    seen.add(key)
                    result["links"].append(anchor)
                controls = page.eval_on_selector_all(
                    "a,button",
                    """els => els.map(e => ({tag:e.tagName,text:(e.innerText||'').trim().slice(0,80),
                        href:e.href||null,aria:e.getAttribute('aria-label')}))
                        .filter(x => /carta|pedir/i.test(x.text) || /carta|pedir/i.test(x.aria||''))""",
                )
                result["buttons"] = controls[:10]
                order = page.get_by_text(re.compile("Pedir en línea", re.I))
                if order.count():
                    try:
                        with page.context.expect_page(timeout=12000) as popup_info:
                            order.first.click()
                        popup = popup_info.value
                        popup.wait_for_load_state("domcontentloaded", timeout=20000)
                        popup.wait_for_timeout(3000)
                        result["providers"].append(
                            {
                                "url": popup.url,
                                "text": popup.inner_text("body")[:800].replace("\n", " | "),
                            }
                        )
                        popup.close()
                    except PlaywrightTimeout:
                        result["providers"].append({"url": page.url, "text": "sin popup"})
                    except Exception as error:
                        result["providers"].append(
                            {"url": page.url, "text": f"{type(error).__name__}: {error}"[:200]}
                        )
            except Exception as error:
                result["error"] = f"{type(error).__name__}: {error}"[:200]
            finally:
                page.close()
            print(
                f"{metadata['name']}: {len(result['links'])} links · "
                f"{len(result['providers'])} proveedores",
                flush=True,
            )
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
        print(f"\n{row['place']}")
        for link in row["links"][:8]:
            print("  ", link)
        for provider in row["providers"]:
            print("  PEDIDO:", provider["text"][:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

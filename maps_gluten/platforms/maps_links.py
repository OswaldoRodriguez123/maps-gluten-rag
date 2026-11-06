from __future__ import annotations

import re
from urllib.parse import urlparse


def _provider(url: str) -> str:
    low = url.lower()
    if "rappi" in low:
        return "Rappi"
    if "pedidosya" in low:
        return "PedidosYa"
    if "ubereats" in low or "uber.com" in low:
        return "UberEats"
    if "fu.do" in low:
        return "Fudo"
    if "tu-mesa" in low or "apparta" in low:
        return "Apparta"
    return urlparse(url).netloc


def links_from_anchors(anchors: list[dict], website: str | None = None) -> dict:
    menu = None
    order: list[dict] = []
    for anchor in anchors:
        href = (anchor.get("href") or "").strip()
        text = (anchor.get("text") or "").lower()
        if not href.startswith("http"):
            continue
        low = href.lower()
        if any(host in low for host in ("menu.fu.do", "menu.tu-mesa.com")) or re.search(
            r"/(menu|carta)(/|$|\?)", low
        ):
            if menu is None or any(
                host in low for host in ("menu.fu.do", "menu.tu-mesa.com")
            ):
                menu = href
            if any(host in low for host in ("menu.fu.do", "menu.tu-mesa.com")):
                continue
        if any(
            provider in low
            for provider in ("rappi", "pedidosya", "ubereats", "uber.com", "fu.do", "tu-mesa", "apparta")
        ):
            entry = {"provider": _provider(href), "url": href}
            if entry not in order:
                order.append(entry)
        if ("carta" in text or "menú" in text or "menu" in text) and menu is None:
            menu = href
    return {"website": website, "menu": menu, "order": order}


def discover_links(record: dict, browser) -> dict:
    metadata = record.get("metadata") or {}
    url = metadata.get("url")
    website = metadata.get("website")
    if not url or not browser:
        return {"website": website, "menu": None, "order": []}
    separator = "&" if "?" in url else "?"
    page = browser.new_page()
    try:
        page.goto(
            f"{url}{separator}hl=es&gl=CL",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        page.wait_for_timeout(4_000)
        anchors = page.eval_on_selector_all(
            "a",
            """els => els.map(e => ({text: (e.innerText || '').trim().slice(0, 80),
                href: e.href})).filter(x => x.href && !x.href.includes('google.'))""",
        )
        links = links_from_anchors(anchors, website)
        try:
            order_button = page.get_by_text(re.compile("Pedir en línea", re.I))
            if order_button.count():
                with page.context.expect_page(timeout=12_000) as popup_info:
                    order_button.first.click()
                popup = popup_info.value
                popup.wait_for_load_state("domcontentloaded", timeout=20_000)
                popup.wait_for_timeout(2_000)
                popup_anchors = popup.eval_on_selector_all(
                    "a",
                    """els => els.map(e => ({text: (e.innerText || '').trim().slice(0, 80),
                        href: e.href})).filter(x => x.href && !x.href.includes('google.'))""",
                )
                extra = links_from_anchors(popup_anchors)
                if extra.get("menu") and not links.get("menu"):
                    links["menu"] = extra["menu"]
                for entry in extra.get("order") or []:
                    if entry not in links["order"]:
                        links["order"].append(entry)
                popup.close()
        except Exception:
            pass
        return links
    finally:
        page.close()

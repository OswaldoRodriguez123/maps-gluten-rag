from __future__ import annotations

import re
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin, urlparse

DISH_STEMS = {
    "hamburgues": "hamburguesa",
    "burger": "hamburguesa",
    "pizza": "pizza",
    "sushi": "sushi",
    "pasta": "pasta",
    "lasañ": "lasaña",
    "lasana": "lasaña",
    "taco": "tacos",
    "burrito": "burrito",
    "arepa": "arepa",
    "empanada": "empanada",
    "ceviche": "ceviche",
    "ramen": "ramen",
    "curry": "curry",
    "pollo": "pollo",
    "carne": "carne",
    "pescado": "pescado",
    "marisco": "mariscos",
    "ensalada": "ensalada",
    "sopa": "sopa",
    "sandwich": "sándwich",
    "sándwich": "sándwich",
    "wrap": "wrap",
    "poke": "poke",
    "bagel": "bagel",
    "waffle": "waffle",
    "panqueque": "panqueque",
    "tortilla": "tortilla",
    "paella": "paella",
    "risotto": "risotto",
    "milanesa": "milanesa",
    "choripan": "choripán",
    "choripán": "choripán",
    "hot dog": "hot dog",
    "shawarma": "shawarma",
    "kebab": "kebab",
    "falafel": "falafel",
    "hummus": "hummus",
    "gyosa": "gyosa",
    "gyoza": "gyosa",
    "tempura": "tempura",
    "costilla": "costilla",
    "parrilla": "parrilla",
    "asado": "asado",
    "churrasco": "churrasco",
    "quesadilla": "quesadilla",
    "nachos": "nachos",
    "alitas": "alitas",
}

MENU_RE = re.compile(r"(menu|menú|carta|order|pedir|productos|shop|tienda)", re.IGNORECASE)
BAD_LINK_RE = re.compile(
    r"google\.|gstatic|googleusercontent|ggpht|schema\.org|youtube\.|instagram\.|facebook\.|tiktok\.",
    re.IGNORECASE,
)
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

WEBSITE_JS = r"""
() => {
  const bad = /google\.|gstatic|googleusercontent|ggpht|schema\.org|youtube\.|instagram\.|facebook\.|tiktok\./i;
  const anchors = [...document.querySelectorAll('a[href^="http"]')]
    .filter(e => e.href && !bad.test(e.href));
  const preferred = anchors.find(e => {
    const label = (e.getAttribute('aria-label') || '') + ' ' + (e.innerText || '');
    return /sitio web|website|página web|pagina web/i.test(label);
  });
  return (preferred || anchors[0] || {}).href || null;
}
"""


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def detect_dishes(text: str) -> list[str]:
    normalized = _normalize(text)
    found: list[str] = []
    for stem, name in DISH_STEMS.items():
        if name in found:
            continue
        if re.search(r"\b" + re.escape(stem), normalized):
            found.append(name)
    return found


def _fetch(url: str, timeout: int = 12) -> tuple[str, str, list[tuple[str, str]]]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept-Language": "es-CL,es;q=0.9,en;q=0.8"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(5_000_000)
        final_url = response.geturl()
        content_type = (response.headers.get_content_type() or "").lower()
        charset = response.headers.get_content_charset() or "utf-8"

    is_pdf = content_type == "application/pdf" or final_url.lower().split("?")[0].endswith(".pdf")
    if is_pdf:
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw))
            text = " ".join((page.extract_text() or "") for page in reader.pages[:40])
            return final_url, text, []
        except Exception:
            return final_url, "", []
    if content_type and content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
        return final_url, "", []

    try:
        html = raw.decode(charset, "ignore")
    except LookupError:
        html = raw.decode("utf-8", "ignore")
    text_parser = _TextParser()
    text_parser.feed(html)
    link_parser = _LinkParser()
    link_parser.feed(html)
    return final_url, " ".join(text_parser.parts), link_parser.links


def _menu_links(base: str, links: list[tuple[str, str]]) -> list[str]:
    base_host = urlparse(base).netloc
    found: list[str] = []
    for href, text in links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base, href)
        if not full.startswith(("http://", "https://")):
            continue
        if full in found:
            continue
        if MENU_RE.search(href) or MENU_RE.search(text):
            if urlparse(full).netloc == base_host:
                found.insert(0, full)
            else:
                found.append(full)
    return found[:2]


def _site_dishes(url: str) -> list[str]:
    try:
        final_url, text, links = _fetch(url)
    except (urllib.error.URLError, ValueError, OSError):
        return []
    dishes = detect_dishes(text)
    if dishes:
        return dishes
    for menu_url in _menu_links(final_url, links):
        try:
            _, menu_text, _ = _fetch(menu_url)
        except (urllib.error.URLError, ValueError, OSError):
            continue
        dishes = detect_dishes(menu_text)
        if dishes:
            return dishes
    return []


def _is_stale(info: dict | None, max_age_days: int, today: date) -> bool:
    if not info or not info.get("enriched_at"):
        return True
    try:
        enriched = date.fromisoformat(info["enriched_at"])
    except ValueError:
        return True
    return (today - enriched).days >= max_age_days


def _extract_website(page) -> str | None:
    try:
        page.wait_for_selector("h1", timeout=5_000)
    except Exception:
        pass
    page.wait_for_timeout(500)
    try:
        return page.evaluate(WEBSITE_JS)
    except Exception:
        return None


def enrich_places(
    page,
    places,
    cache: dict | None = None,
    max_age_days: int = 30,
    force: bool = False,
    today: date | None = None,
) -> int:
    cache = cache or {}
    today = today or date.today()

    stale = [
        place
        for place in places
        if force or _is_stale(cache.get(place.ftid), max_age_days, today)
    ]
    if not stale:
        return 0

    with_web = []
    for place in stale:
        try:
            page.goto(place.url, wait_until="domcontentloaded", timeout=30_000)
            website = _extract_website(page)
        except Exception:
            website = None
        place.website = website
        if website:
            with_web.append(place)

    results: dict[str, list[str]] = {}
    if with_web:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_site_dishes, place.website): place.ftid for place in with_web}
            for future in as_completed(futures):
                ftid = futures[future]
                try:
                    results[ftid] = future.result()
                except Exception:
                    results[ftid] = []

    for place in stale:
        dishes = results.get(place.ftid) or []
        place.dishes = ", ".join(dishes) if dishes else None
        place.enriched_at = today.isoformat()
    return len(stale)

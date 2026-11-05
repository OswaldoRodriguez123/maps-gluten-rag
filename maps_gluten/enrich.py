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

ENRICH_VERSION = 3

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
    "completo": "completo",
    "mechada": "mechada",
    "pino": "pino",
    "barros luco": "barros luco",
    "chorrillana": "chorrillana",
    "pastel de choclo": "pastel de choclo",
    "cazuela": "cazuela",
    "humita": "humita",
    "torta": "torta",
    "pastel": "pastel",
    "gallet": "galleta",
    "alfajor": "alfajor",
    "brownie": "brownie",
    "cupcake": "cupcake",
    "muffin": "muffin",
    "donut": "donut",
    "dónut": "donut",
    "cheesecake": "cheesecake",
    "pie de": "pie",
    "tarta": "tarta",
    "helado": "helado",
    "chocolate": "chocolate",
    "churro": "churro",
    "flan": "flan",
    "budin": "budín",
    "budín": "budín",
    "pionono": "pionono",
    "merengue": "merengue",
    "macaron": "macaron",
    "tiramisu": "tiramisú",
    "tiramisú": "tiramisú",
    "manjar": "manjar",
    "dulce de leche": "dulce de leche",
    "chilenito": "chilenito",
    "medialuna": "medialuna",
    "factura": "factura",
    "croissant": "croissant",
    "crepe": "crepe",
    "gofre": "gofre",
    "gelato": "gelato",
    "sorbete": "sorbete",
    "postre": "postre",
    "dulce": "dulces",
    "jugo": "jugo",
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

REVIEW_TOPICS_JS = r"""
() => [...document.querySelectorAll('button[role="radio"]')]
  .map(e => e.getAttribute('aria-label') || '')
  .map(label => {
    const match = label.match(/Se menciona (.+?) en \d+/i);
    return match ? match[1].trim() : null;
  })
  .filter(Boolean)
"""

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


class _ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            data = dict(attrs)
            source = data.get("src") or data.get("data-src") or ""
            if source:
                self.images.append(source)


BAD_IMAGE_RE = re.compile(
    r"(logo|icon|favicon|sprite|avatar|social|facebook|instagram|whatsapp|pixel|tracking|banner)",
    re.IGNORECASE,
)


def _ocr_image(image) -> str:
    try:
        import pytesseract
    except Exception:
        return ""
    for language in ("spa+eng", "eng"):
        try:
            return pytesseract.image_to_string(image, lang=language)
        except Exception:
            continue
    return ""


def _ocr_bytes(raw: bytes) -> str:
    try:
        from PIL import Image
    except Exception:
        return ""
    try:
        image = Image.open(BytesIO(raw))
        if image.width < 300 or image.height < 200:
            return ""
        return _ocr_image(image)
    except Exception:
        return ""


def _ocr_pdf(raw: bytes) -> str:
    try:
        import pypdfium2 as pdfium
    except Exception:
        return ""
    try:
        document = pdfium.PdfDocument(raw)
        parts: list[str] = []
        for index in range(min(10, len(document))):
            page = document[index]
            bitmap = page.render(scale=2.0)
            parts.append(_ocr_image(bitmap.to_pil()))
        return " ".join(parts)
    except Exception:
        return ""


def _download_image(url: str, timeout: int = 10) -> bytes:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get_content_type() or "").lower()
            if not content_type.startswith("image/"):
                return b""
            return response.read(8_000_000)
    except Exception:
        return b""


def _candidate_images(images: list[str], base: str, limit: int = 3) -> list[str]:
    found: list[str] = []
    for source in images:
        if not source or source.startswith("data:"):
            continue
        if BAD_IMAGE_RE.search(source):
            continue
        full = urljoin(base, source)
        if not full.startswith(("http://", "https://")):
            continue
        if full in found:
            continue
        found.append(full)
        if len(found) >= limit:
            break
    return found


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


def _fetch(url: str, timeout: int = 12) -> tuple[str, str, list[tuple[str, str]], list[str]]:
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
        text = ""
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw))
            text = " ".join((page.extract_text() or "") for page in reader.pages[:40])
        except Exception:
            text = ""
        if len(text.strip()) < 100:
            text = _ocr_pdf(raw)
        return final_url, text, [], []
    if content_type and content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
        return final_url, "", [], []

    try:
        html = raw.decode(charset, "ignore")
    except LookupError:
        html = raw.decode("utf-8", "ignore")
    text_parser = _TextParser()
    text_parser.feed(html)
    link_parser = _LinkParser()
    link_parser.feed(html)
    image_parser = _ImageParser()
    image_parser.feed(html)
    return final_url, " ".join(text_parser.parts), link_parser.links, image_parser.images


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


def _site_dishes(url: str, ocr: bool = False) -> list[str]:
    try:
        final_url, text, links, images = _fetch(url)
    except (urllib.error.URLError, ValueError, OSError):
        return []
    dishes = detect_dishes(text)
    if dishes:
        return dishes
    menu_images: list[str] = []
    for menu_url in _menu_links(final_url, links):
        try:
            menu_final, menu_text, _, menu_imgs = _fetch(menu_url)
        except (urllib.error.URLError, ValueError, OSError):
            continue
        dishes = detect_dishes(menu_text)
        if dishes:
            return dishes
        menu_images.extend(urljoin(menu_final, source) for source in menu_imgs)
    if ocr:
        for image_url in _candidate_images(menu_images + images, final_url, limit=3):
            raw = _download_image(image_url)
            if not raw:
                continue
            dishes = detect_dishes(_ocr_bytes(raw))
            if dishes:
                return dishes
    return []


def _is_stale(info: dict | None, max_age_days: int, today: date) -> bool:
    if not info or not info.get("enriched_at"):
        return True
    if info.get("enrich_version") != ENRICH_VERSION:
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


def _extract_reviews(page) -> list[str]:
    try:
        page.wait_for_selector('button[role="radio"]', timeout=4_000)
    except Exception:
        pass
    topics: list[str] = []
    try:
        topics = page.evaluate(REVIEW_TOPICS_JS)
    except Exception:
        pass
    try:
        body = page.inner_text("body")
    except Exception:
        body = ""
    return detect_dishes(" ".join(topics) + " " + body)


def enrich_places(
    page,
    places,
    cache: dict | None = None,
    max_age_days: int = 30,
    force: bool = False,
    today: date | None = None,
    ocr: bool = False,
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
            review_dishes = _extract_reviews(page)
        except Exception:
            website = None
            review_dishes = []
        place.website = website
        place.review_dishes = ", ".join(review_dishes) if review_dishes else None
        if website:
            with_web.append(place)

    results: dict[str, list[str]] = {}
    if with_web:
        with ThreadPoolExecutor(max_workers=4 if ocr else 8) as pool:
            futures = {
                pool.submit(_site_dishes, place.website, ocr): place.ftid
                for place in with_web
            }
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
        place.enrich_version = ENRICH_VERSION
    return len(stale)

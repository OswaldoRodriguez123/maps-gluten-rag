from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

GETLIST_PATH = "/maps/preview/entitylist/getlist"
JSON_PREFIX = re.compile(r"^\)\]\}'\s*")
LIST_DATA_RE = re.compile(r"!11m2!2s([^!&/?]+)")
PLACE_LINK = 'a[href*="/maps/place/"]'
DOM_ROWS = 'a[href*="/maps/place/"], button.SMP2wb'
COUNT_JS = 'document.querySelectorAll(\'a[href*="/maps/place/"], button.SMP2wb\').length'
CONSENT_LABELS = (
    "Aceptar todo",
    "Accept all",
    "Alles akzeptieren",
    "Tout accepter",
    "Acepto",
    "I agree",
)

TITLE_JS = r"""
() => {
  const el = document.querySelector('.fontHeadlineLarge, h1, [role="heading"][aria-level="1"]');
  return el ? el.textContent.trim() : null;
}
"""

SCROLLER_JS = r"""
() => {
  const isScrollable = e => {
    const s = getComputedStyle(e);
    return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 50;
  };
  const rows = 'a[href*="/maps/place/"], button.SMP2wb';
  const candidates = [...document.querySelectorAll('div')].filter(isScrollable);
  candidates.sort((a, b) =>
    (b.querySelectorAll(rows).length - a.querySelectorAll(rows).length) ||
    (b.scrollHeight - a.scrollHeight)
  );
  window.__mapsScroller = candidates[0] || null;
  if (window.__mapsScroller) window.__mapsScroller.scrollTop = 0;
  else window.scrollTo(0, 0);
  return !!window.__mapsScroller;
}
"""

SCROLL_JS = r"""
() => {
  const s = window.__mapsScroller;
  if (s) s.scrollTop = s.scrollHeight;
  else window.scrollTo(0, document.body.scrollHeight);
}
"""

EXTRACT_JS = r"""
() => {
  const pick = (root, sels) => {
    for (const s of sels) {
      const el = root.querySelector(s);
      if (el) return el;
    }
    return null;
  };
  const nodes = [...document.querySelectorAll('a[href*="/maps/place/"], button.SMP2wb')];
  const out = [];
  const seenHref = new Set();

  for (const node of nodes) {
    const href = node.getAttribute('href') || '';
    if (href) {
      if (seenHref.has(href)) continue;
      seenHref.add(href);
    }

    const cardIsSingle = el => el.querySelectorAll('a[href*="/maps/place/"], button.SMP2wb').length <= 1;
    let card = node;
    if (!pick(node, ['.fontHeadlineSmall', '[role="heading"]'])) {
      for (let i = 0; i < 8 && card.parentElement; i++) {
        card = card.parentElement;
        if (pick(card, ['.fontHeadlineSmall', '[role="heading"]']) && cardIsSingle(card)) break;
        if ((card.innerText || '').trim().length > 400) { card = node; break; }
      }
      if (!cardIsSingle(card)) card = node;
    }

    const nameEl = pick(card, ['.fontHeadlineSmall', '[role="heading"]', '.qBF1td']);
    const aria = (node.getAttribute('aria-label') || '').trim();
    let name = nameEl ? nameEl.textContent.trim() : (aria ? aria.split('·')[0].trim() : '');
    const lines = (card.innerText || '')
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean);
    if (!name && lines.length) name = lines[0];
    if (!name) continue;

    const ratingEl = pick(card, [
      '.MW4etd',
      'span[aria-label*="estrellas"]',
      'span[aria-label*="stars"]',
    ]);
    const reviewsEl = pick(card, ['.UY7F9']);
    let rating = ratingEl ? ratingEl.textContent.trim() : null;
    if (!rating) {
      const m = aria.match(/([0-5][.,]\d)/);
      if (m) rating = m[1].replace(',', '.');
    }

    const leftovers = lines.filter(
      l => l !== name && !/^[0-5][.,]\d/.test(l) && !/^\(?\d[\d.,]*\)?$/.test(l)
    );
    let address = leftovers.find(l => /\b(calle|carrera|cra\.?|cl\.?|avenida|av\.?|transversal|diagonal|autopista|circular|manzana|mz\.?|local|centro comercial|cc\.?|plaza|paseo|pasaje|km\.?|#)\b/i.test(l))
      || (leftovers.length ? leftovers[leftovers.length - 1] : null);
    if (!address && aria.includes('·')) {
      const tail = aria.split('·').pop().trim();
      if (tail) address = tail;
    }
    const category = leftovers.find(
      l => l !== address && /restaurant|restaurante|caf[eé]|panader|tienda|supermercado|bar|comida|salud|mercado|reposter|helader|pizzer|sushi|parrilla|food/i.test(l)
    ) || null;

    out.push({
      href,
      name,
      address,
      category,
      rating,
      reviews: reviewsEl ? reviewsEl.textContent.trim() : null,
      aria: aria || null,
    });
  }
  return out;
}
"""


COLLECT_ROWS_JS = r"""
() => [...document.querySelectorAll('button.SMP2wb')].map(b => {
  const nameEl = b.querySelector('.fontHeadlineSmall');
  const name = nameEl ? nameEl.textContent.trim() : '';
  const ratingEl = b.querySelector('.MW4etd');
  const rating = ratingEl ? ratingEl.textContent.trim() : null;
  const block = b.querySelector('.yfRytc') || b.querySelector('.IIrLbb');
  let category = null;
  if (block) {
    const clone = block.cloneNode(true);
    clone.querySelectorAll('.MW4etd, [role="img"]').forEach(e => e.remove());
    const lines = (clone.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    category = lines[0] || null;
  }
  return {name, rating, category};
})
"""

SCROLL_SETUP_JS = r"""
() => {
  const sc = [...document.querySelectorAll('div')].filter(e => {
    const s = getComputedStyle(e);
    return /(auto|scroll)/.test(s.overflowY)
      && e.scrollHeight > e.clientHeight + 20
      && e.querySelectorAll('button.SMP2wb').length > 0;
  });
  sc.sort((a, b) => b.querySelectorAll('button.SMP2wb').length - a.querySelectorAll('button.SMP2wb').length);
  window.__mapsScroller = sc[0] || null;
  if (window.__mapsScroller) window.__mapsScroller.scrollTop = 0;
  return !!window.__mapsScroller;
}
"""

SCROLL_STEP_JS = (
    "window.__mapsScroller && (window.__mapsScroller.scrollTop = Math.min("
    "window.__mapsScroller.scrollTop + window.__mapsScroller.clientHeight * 0.65, "
    "window.__mapsScroller.scrollHeight))"
)
SCROLL_STATE_JS = (
    "window.__mapsScroller ? "
    "[window.__mapsScroller.scrollTop, window.__mapsScroller.scrollHeight] : null"
)

CATEGORY_STOPWORDS = {"abierto", "cerrado", "abre pronto", "cierra pronto", "abre hoy", "cierra hoy"}


@dataclass
class Place:
    ftid: str
    name: str
    address: str | None
    category: str | None
    rating: str | None
    reviews: str | None
    note: str | None
    url: str
    saved_on: str | None = None
    lat: float | None = None
    lng: float | None = None
    website: str | None = None
    dishes: str | None = None
    enriched_at: str | None = None


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().lower()


def hash_key(name: str, address: str | None) -> str:
    digest = hashlib.sha1(_normalize(f"{name}|{address or ''}").encode("utf-8")).hexdigest()
    return f"h:{digest[:16]}"


def place_key(url: str, name: str, address: str | None) -> str:
    match = re.search(r"!1s(0x[0-9a-fA-F]+)(?::|%3A)(0x[0-9a-fA-F]+)", url or "")
    if match:
        return f"{match.group(1)}:{match.group(2)}"
    match = re.search(r"[?&]cid=(\d+)", url or "")
    if match:
        return f"cid:{match.group(1)}"
    return hash_key(name, address)


def list_key(url: str) -> str:
    match = LIST_DATA_RE.search(url)
    if match:
        return match.group(1)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return f"url:{digest[:16]}"


def _at(value, index, kind):
    if not isinstance(value, list) or index >= len(value):
        return None
    item = value[index]
    return item if isinstance(item, kind) else None


def _ftid(ids) -> str | None:
    if not (isinstance(ids, list) and len(ids) >= 2):
        return None
    try:
        high = int(ids[0]) & 0xFFFFFFFFFFFFFFFF
        low = int(ids[1]) & 0xFFFFFFFFFFFFFFFF
    except (TypeError, ValueError):
        return None
    return f"0x{high:x}:0x{low:x}"


def _saved_on(record) -> str | None:
    for index in (9, 10):
        block = record[index] if isinstance(record, list) and index < len(record) else None
        if isinstance(block, list) and block and isinstance(block[0], int):
            try:
                return datetime.fromtimestamp(block[0], tz=timezone.utc).date().isoformat()
            except (OverflowError, OSError, ValueError):
                continue
    return None


def _place_url(ftid: str, name: str, address: str | None, lat, lng) -> str:
    if ftid.startswith("0x") and ":" in ftid:
        try:
            cid = int(ftid.split(":", 1)[1], 16)
            return f"https://www.google.com/maps?cid={cid}"
        except ValueError:
            pass
    if lat is not None and lng is not None:
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    query = quote_plus(f"{name} {address or ''}".strip())
    return f"https://www.google.com/maps/search/?api=1&query={query}"


def _record_to_place(record) -> Place | None:
    if not (isinstance(record, list) and len(record) > 2 and isinstance(record[2], str)):
        return None
    name = record[2].strip()
    if not name:
        return None

    meta = record[1] if isinstance(record[1], list) else []
    address = _at(meta, 4, str)
    if address:
        address = address.strip() or None
    coords = _at(meta, 5, list)
    lat = lng = None
    if coords and len(coords) >= 4:
        if isinstance(coords[2], (int, float)):
            lat = float(coords[2])
        if isinstance(coords[3], (int, float)):
            lng = float(coords[3])
    ftid = _ftid(_at(meta, 6, list))
    feature = _at(meta, 7, str)
    if not ftid and feature:
        ftid = f"g:{feature}"
    if not ftid:
        ftid = hash_key(name, address)

    note = (_at(record, 3, str) or _at(meta, 3, str) or _at(meta, 2, str) or "").strip()

    return Place(
        ftid=ftid,
        name=name,
        address=address,
        category=None,
        rating=None,
        reviews=None,
        note=note or None,
        url=_place_url(ftid, name, address, lat, lng),
        saved_on=_saved_on(record),
        lat=lat,
        lng=lng,
    )


def parse_getlist(body: str) -> tuple[str | None, list[Place]]:
    try:
        data = json.loads(JSON_PREFIX.sub("", body).strip())
    except (json.JSONDecodeError, TypeError):
        return None, []
    if not (isinstance(data, list) and data and isinstance(data[0], list)):
        return None, []
    root = data[0]
    title = _at(root, 4, str)
    records = root[8] if len(root) > 8 and isinstance(root[8], list) else []
    places = [place for place in (_record_to_place(record) for record in records) if place]
    return title, places


def _clean_category(value: str | None, address: str | None) -> str | None:
    value = (value or "").strip()
    if not value or len(value) > 60:
        return None
    if re.search(r"\d", value):
        return None
    if value.lower() in CATEGORY_STOPWORDS:
        return None
    if address:
        if _normalize(value) in _normalize(address):
            return None
        value_tokens = _tokens(value)
        address_tokens = set(re.findall(r"[a-z0-9]+", _normalize(address)))
        if value_tokens and len(value_tokens & address_tokens) / len(value_tokens) >= 0.5:
            return None
    return value


def _collect_dom_rows(page: Page) -> list[dict]:
    try:
        page.wait_for_selector("button.SMP2wb", timeout=10_000)
    except PlaywrightTimeout:
        return []
    try:
        page.wait_for_selector(".MW4etd", timeout=12_000)
        page.wait_for_timeout(2000)
    except PlaywrightTimeout:
        pass
    try:
        page.evaluate(SCROLL_SETUP_JS)
    except Exception:
        pass

    seen: dict[str, dict] = {}

    def merge(rows: list[dict]) -> None:
        for row in rows:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            key = _normalize(name)
            old = seen.get(key)
            if old is None:
                seen[key] = {
                    "name": name,
                    "rating": row.get("rating"),
                    "category": row.get("category"),
                }
                continue
            if row.get("rating") and not old.get("rating"):
                old["rating"] = row["rating"]
            if row.get("category") and not old.get("category"):
                old["category"] = row["category"]

    previous = None
    stable = 0
    for _ in range(80):
        merge(page.evaluate(COLLECT_ROWS_JS))
        try:
            page.evaluate(SCROLL_STEP_JS)
            page.wait_for_timeout(850)
            state = page.evaluate(SCROLL_STATE_JS)
        except Exception:
            break
        if state == previous:
            stable += 1
            if stable >= 4:
                break
        else:
            stable = 0
        previous = state

    page.wait_for_timeout(500)
    try:
        merge(page.evaluate(COLLECT_ROWS_JS))
    except Exception:
        pass
    return list(seen.values())


MATCH_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "y", "e", "en", "con", "sin", "para", "por",
    "gluten", "free", "producto", "productos", "comida", "saludable", "natural",
    "bar", "cafe", "cafeteria", "restaurante", "tienda", "panaderia", "pasteleria",
    "patisserie", "bakery", "market", "spa", "sas", "ltda",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize(value))
        if len(token) > 1 and token not in MATCH_STOPWORDS
    }


def _match_score(candidate: str, name: str) -> float:
    left, right = _normalize(candidate), _normalize(name)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens, right_tokens = _tokens(candidate), _tokens(name)
    if left_tokens and right_tokens and (left_tokens <= right_tokens or right_tokens <= left_tokens):
        return 0.92
    if not left_tokens or not right_tokens:
        return 0.0
    return (2 * len(left_tokens & right_tokens)) / (len(left_tokens) + len(right_tokens))


def _enrich(places: list[Place], rows: list[dict]) -> int:
    remaining = list(places)
    enriched = 0
    for row in rows:
        best = None
        best_score = 0.0
        second_score = 0.0
        for place in remaining:
            score = _match_score(row.get("name") or "", place.name)
            if score > best_score:
                second_score = best_score
                best_score = score
                best = place
            elif score > second_score:
                second_score = score
        if best is None or best_score < 0.6 or best_score - second_score < 0.05:
            continue
        remaining.remove(best)
        rating = (row.get("rating") or "").strip() or None
        category = _clean_category(row.get("category"), best.address)
        changed = False
        if rating and not best.rating:
            best.rating = rating
            changed = True
        if category and not best.category:
            best.category = category
            changed = True
        if changed:
            enriched += 1
    return enriched


def _launch(p, profile: Path, headless: bool, channel: str | None, locale: str, timezone: str):
    profile.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        user_data_dir=str(profile),
        headless=headless,
        locale=locale,
        timezone_id=timezone,
        viewport={"width": 1400, "height": 950},
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
    )
    if channel:
        try:
            return p.chromium.launch_persistent_context(channel=channel, **kwargs)
        except Exception:
            pass
    return p.chromium.launch_persistent_context(**kwargs)


def _dismiss_consent(page: Page) -> None:
    for label in CONSENT_LABELS:
        try:
            button = page.get_by_role("button", name=re.compile(re.escape(label), re.IGNORECASE))
            if button.count() and button.first.is_visible():
                button.first.click(timeout=2000)
                page.wait_for_timeout(800)
                return
        except Exception:
            continue


def _autoscroll(page: Page) -> None:
    try:
        page.evaluate(SCROLLER_JS)
    except Exception:
        pass
    previous = -1
    stable = 0
    for _ in range(100):
        count = page.evaluate(COUNT_JS)
        if count == previous:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        previous = count
        try:
            page.evaluate(SCROLL_JS)
        except Exception:
            break
        page.wait_for_timeout(700)


def _dom_places(page: Page) -> list[Place]:
    places: list[Place] = []
    seen: set[str] = set()
    for item in page.evaluate(EXTRACT_JS):
        name = (item.get("name") or "").strip()
        if not name:
            continue
        href = (item.get("href") or "").strip()
        address = (item.get("address") or "").strip() or None
        ftid = place_key(href, name, address)
        if ftid in seen:
            continue
        seen.add(ftid)
        places.append(
            Place(
                ftid=ftid,
                name=name,
                address=address,
                category=(item.get("category") or "").strip() or None,
                rating=(item.get("rating") or "").strip() or None,
                reviews=(item.get("reviews") or "").strip() or None,
                note=None,
                url=href or _place_url(ftid, name, address, None, None),
            )
        )
    return places


def login(profile: Path, channel: str | None, locale: str, timezone: str) -> None:
    with sync_playwright() as p:
        context = _launch(p, profile, headless=False, channel=channel, locale=locale, timezone=timezone)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=60_000)
        print("Inicia sesión en la ventana que se abrió.")
        print("Cuando termines, vuelve aquí y pulsa Enter para guardar el perfil.")
        input()
        context.close()


def scrape_list(
    url: str,
    profile: Path,
    headless: bool,
    channel: str | None,
    locale: str,
    timezone: str,
    debug_dir: Path | None = None,
    enrich: bool = False,
    enrich_cache: dict | None = None,
    enrich_days: int = 30,
    enrich_force: bool = False,
    today: str | None = None,
) -> tuple[str, str | None, list[Place], bool]:
    captured: dict[str, str] = {}
    with sync_playwright() as p:
        context = _launch(p, profile, headless=headless, channel=channel, locale=locale, timezone=timezone)
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(response):
            if GETLIST_PATH in response.url and "body" not in captured:
                try:
                    captured["body"] = response.text()
                except Exception:
                    pass
            if debug_dir:
                debug_dir.mkdir(parents=True, exist_ok=True)
                if any(key in response.url for key in (GETLIST_PATH, "batchexecute", "GetList")):
                    try:
                        body = response.text()
                    except Exception:
                        return
                    stamp = int(time.time() * 1000)
                    (debug_dir / f"resp_{stamp}.txt").write_text(
                        f"{response.url}\n\n{body[:200_000]}", encoding="utf-8"
                    )

        page.on("response", on_response)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            _dismiss_consent(page)
            if "accounts.google.com" in page.url:
                raise RuntimeError(
                    "Google pidió iniciar sesión. Comparte la lista con un enlace público "
                    "o ejecuta `python -m maps_gluten login`."
                )

            deadline = time.time() + 45
            while "body" not in captured and time.time() < deadline:
                page.wait_for_timeout(500)

            title: str | None = None
            places: list[Place] = []
            complete = False
            if "body" in captured:
                title, places = parse_getlist(captured["body"])
                complete = bool(places)

            if not places:
                try:
                    page.wait_for_selector(DOM_ROWS, timeout=15_000)
                except PlaywrightTimeout:
                    if debug_dir:
                        (debug_dir / "page.html").write_text(page.content(), encoding="utf-8")
                    raise RuntimeError(
                        "No se encontraron lugares en la lista. Revisa que el enlace sea público "
                        "o que la sesión de Google siga activa. Usa --debug para guardar el HTML."
                    ) from None
                title = title or page.evaluate(TITLE_JS)
                _autoscroll(page)
                places = _dom_places(page)
            else:
                try:
                    rows = _collect_dom_rows(page)
                except Exception:
                    rows = []
                if rows:
                    _enrich(places, rows)

            final_url = page.url

            if enrich and places:
                try:
                    from . import enrich as enrich_module

                    enrich_module.enrich_places(
                        page,
                        places,
                        cache=enrich_cache,
                        max_age_days=enrich_days,
                        force=enrich_force,
                        today=datetime.fromisoformat(today).date() if today else None,
                    )
                except Exception:
                    pass
        finally:
            context.close()

    return list_key(final_url), title, places, complete

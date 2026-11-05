from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from urllib.parse import parse_qs, urlparse

from .enrich import detect_dishes

API = "https://api.apify.com/v2"
ACTOR = "unitbytes~google-maps-photos-scraper"
POLL_SECONDS = 10
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

PRICE_DOLLAR = re.compile(r"\$\s*(\d[\d.,]*)")
PRICE_THOUSANDS = re.compile(r"\b(\d{1,3}(?:[.,]\d{3})+)\b")
STOPWORDS = {
    "total", "subtotal", "iva", "propina", "delivery", "horario", "dirección",
    "direccion", "teléfono", "telefono", "instagram", "whatsapp", "www", "http",
    "menu", "menú", "carta", "precio", "valor", "promoción", "promocion",
    "salado", "dulce", "helados", "pasteles", "tortas", "cafeteria",
    "cafetería", "bebidas", "jugos", "postres",
}


def _request(url: str, *, data: dict | None = None, timeout: int = 60):
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    request = urllib.request.Request(
        url, data=payload, headers=headers, method="POST" if payload else "GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _start_run(token: str, urls: list[str], max_photos: int, max_charge: float, timeout: int) -> dict:
    query = urllib.parse.urlencode(
        {"token": token, "timeout": timeout, "maxTotalChargeUsd": max_charge}
    )
    payload = {
        "placeUrls": urls,
        "category": "menu",
        "maxPhotos": max_photos,
        "highResOnly": False,
        "scrapePhotos": True,
    }
    response = _request(f"{API}/acts/{ACTOR}/runs?{query}", data=payload)
    return response["data"]


def _wait_run(token: str, run_id: str, timeout: int) -> dict:
    query = urllib.parse.urlencode({"token": token})
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = _request(f"{API}/actor-runs/{run_id}?{query}")["data"]
        if run.get("status") in {"SUCCEEDED", "TIMED-OUT", "FAILED", "ABORTED"}:
            return run
        time.sleep(POLL_SECONDS)
    raise TimeoutError("Apify no terminó dentro del tiempo esperado")


def _fetch_items(token: str, dataset_id: str) -> list[dict]:
    query = urllib.parse.urlencode(
        {"token": token, "format": "json", "clean": "true", "limit": 10000}
    )
    response = _request(f"{API}/datasets/{dataset_id}/items?{query}", timeout=120)
    return response if isinstance(response, list) else response.get("items", [])


def _cid(url: str) -> str:
    try:
        return parse_qs(urlparse(url or "").query).get("cid", [""])[0]
    except ValueError:
        return ""


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().lower()


def _download(url: str, timeout: int = 15) -> bytes:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(20_000_000)
    except Exception:
        return b""


def _ocr_menu_bytes(raw: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except Exception:
        return ""
    try:
        image = Image.open(BytesIO(raw)).convert("L")
    except Exception:
        return ""
    if image.width < 1800:
        ratio = 1800 / max(image.width, 1)
        image = image.resize(
            (int(image.width * ratio), int(image.height * ratio)), Image.LANCZOS
        )
    elif image.width > 2600:
        ratio = 2600 / image.width
        image = image.resize(
            (int(image.width * ratio), int(image.height * ratio)), Image.LANCZOS
        )
    image = ImageOps.autocontrast(image)
    texts: list[str] = []
    for psm in (6, 11):
        try:
            texts.append(
                pytesseract.image_to_string(
                    image, lang="spa+eng", config=f"--psm {psm}"
                )
            )
        except Exception:
            continue
    return "\n".join(texts)


def _clean_name(value: str) -> str:
    value = re.sub(r"^[\s•\-–—\d.)]+", "", value)
    value = PRICE_DOLLAR.sub("", value)
    value = PRICE_THOUSANDS.sub("", value)
    value = re.sub(r"\s+", " ", value).strip(" -–—:;|")
    return value


def _parse_menu_text(text: str) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if len(line) < 3 or len(line) > 120:
            continue
        normalized = _normalize(line)
        if any(stop in normalized for stop in STOPWORDS):
            continue
        price = None
        match = PRICE_DOLLAR.search(line) or PRICE_THOUSANDS.search(line)
        if match:
            price = match.group(0).strip()
        name = _clean_name(line)
        if len(name) < 3 or not re.search(r"[a-zA-ZÁÉÍÓÚÑáéíóúñ]", name):
            continue
        detected = detect_dishes(line)
        if not detected and not price:
            continue
        key = _normalize(name)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {
                "name": name,
                "price": price,
                "category": None,
                "description": line,
                "source": "ocr",
            }
        )
    return found


def _summary(dishes: list[dict]) -> str | None:
    parts: list[str] = []
    for dish in dishes:
        name = (dish.get("name") or "").strip()
        if not name:
            continue
        label = name
        if dish.get("price"):
            label += f" ({dish['price']})"
        parts.append(label)
    return "; ".join(parts) if parts else None


def _match_place(item: dict, by_url: dict, by_cid: dict, by_name: dict):
    cid = str(item.get("placeCid") or "")
    if cid and cid in by_cid:
        return by_cid[cid]
    url = item.get("placeMapsUrl") or ""
    if url in by_url:
        return by_url[url]
    if cid or _cid(url):
        record = by_cid.get(cid or _cid(url))
        if record:
            return record
    name = _normalize(item.get("placeName") or "")
    if name:
        for key, record in by_name.items():
            if key and name and (key in name or name in key):
                return record
    return None


def enrich_menus_photos(
    places,
    token: str,
    *,
    max_photos: int = 8,
    max_charge_usd: float = 2.0,
    timeout: int = 1200,
    today: str | None = None,
) -> int:
    targets = [place for place in places if getattr(place, "url", None)]
    if not targets:
        return 0

    today = today or date.today().isoformat()
    by_url = {place.url: place for place in targets}
    by_cid = {_cid(place.url): place for place in targets if _cid(place.url)}
    by_name = {_normalize(place.name): place for place in targets}

    try:
        run = _start_run(token, list(by_url), max_photos, max_charge_usd, timeout)
        completed = _wait_run(token, run["id"], timeout + 300)
        status = completed.get("status")
        dataset_id = completed.get("defaultDatasetId") or run.get("defaultDatasetId")
        items = _fetch_items(token, dataset_id) if dataset_id else []
        print(f"Apify UnitBytes: {status}, {len(items)} fotos de menú")
    except Exception as error:
        print(f"Apify UnitBytes: fallo: {error}", file=sys.stderr)
        return 0
    if status in {"FAILED", "ABORTED"}:
        return 0

    photos: dict[str, list[str]] = {}
    for item in items:
        if item.get("photoCategory") not in {"menu", None, ""}:
            continue
        place = _match_place(item, by_url, by_cid, by_name)
        if place is None:
            continue
        url = (
            item.get("photoUrlHighRes")
            or item.get("photoUrl")
            or item.get("thumbnailUrl")
        )
        if not url:
            continue
        photos.setdefault(place.ftid, []).append(url)

    print(
        f"Apify UnitBytes: {len(items)} fotos, "
        f"{len(photos)} locales con fotos, "
        f"{sum(len(urls[:max_photos]) for urls in photos.values())} por OCR"
    )

    ocr_results: dict[str, list[dict]] = {}
    tasks = [
        (place.ftid, url)
        for place in targets
        for url in photos.get(place.ftid, [])[:max_photos]
    ]
    with_text = 0
    if tasks:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_download, url): ftid for ftid, url in tasks}
            for future in as_completed(futures):
                ftid = futures[future]
                raw = future.result()
                if not raw:
                    continue
                text = _ocr_menu_bytes(raw)
                if not text:
                    continue
                with_text += 1
                ocr_results.setdefault(ftid, []).extend(_parse_menu_text(text))
    print(f"Apify UnitBytes: {with_text} fotos con texto OCR")

    total = 0
    for place in targets:
        dishes = ocr_results.get(place.ftid) or []
        place.menu_dishes = _summary(dishes)
        place.menu_json = json.dumps(dishes, ensure_ascii=False) if dishes else None
        place.menu_at = today
        total += len(dishes)

    return total

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from .enrich import detect_dishes

API = "https://api.apify.com/v2"
ACTOR = "unitbytes~google-maps-photos-scraper"
POLL_SECONDS = 10
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

DEFAULT_VISION_MODELS = (
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
)
VISION_MODELS = tuple(
    model.strip()
    for model in os.getenv("GEMINI_VISION_MODEL", "").split(",")
    if model.strip()
) or DEFAULT_VISION_MODELS
VISION_PROMPT = (
    "Eres un experto en cartas de restaurantes. Analiza la imagen y devuelve "
    "SOLO un JSON array de objetos con las claves name, price y category. "
    "Incluye todos los platos y precios legibles, con el texto exacto. "
    "Usa como category el título o sección visible (por ejemplo Helados, "
    "Cafetería, Desayunos). Si un ítem se llama solo 'simple', 'doble', "
    "'individual', 'grande' o similar, antepón la categoría al name "
    "(por ejemplo 'Helado simple'). "
    "Si la imagen no es una carta o no se lee, devuelve []. No inventes nada."
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


def _vision_menu(raw: bytes, api_key: str, model: str) -> list[dict]:
    import base64

    mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    body = {
        "contents": [
            {
                "parts": [
                    {"text": VISION_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime,
                            "data": base64.b64encode(raw).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))
    text = "".join(
        part.get("text", "")
        for candidate in result.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
    )
    return _parse_vision_json(text)


def _parse_vision_json(text: str) -> list[dict]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    dishes: list[dict] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        name = _clean_name(str(item.get("name") or ""))
        if len(name) < 3 or not re.search(r"[a-zA-ZÁÉÍÓÚÑáéíóúñ]", name):
            continue
        key = _normalize(name)
        if key in seen:
            continue
        seen.add(key)
        price = item.get("price")
        if isinstance(price, (int, float)):
            price = f"${int(price)}"
        price = str(price).strip() if price not in (None, "", 0) else None
        category = item.get("category")
        category = str(category).strip() if category else None
        dishes.append(
            {
                "name": name,
                "price": price,
                "category": category,
                "description": None,
                "source": "vision",
            }
        )
    return dishes


def _vision_with_fallback(raw: bytes, api_key: str) -> list[dict] | None:
    """Devuelve platos, [] si no hay, o None si se agotó la cuota (detener).

    Usa primero el modelo más barato (flash-lite) y, si está saturado (503),
    pasa al siguiente sin esperar.
    """
    quota_models = 0
    for model in VISION_MODELS:
        try:
            return _vision_menu(raw, api_key, model)
        except Exception as error:
            code = getattr(error, "code", None)
            if code == 429:
                quota_models += 1
                print(
                    f"Visión Gemini {model}: cuota agotada, pruebo el siguiente",
                    file=sys.stderr,
                )
                continue
            if code in {500, 502, 503, 504}:
                print(
                    f"Visión Gemini {model}: {code} saturado, pruebo el siguiente",
                    file=sys.stderr,
                )
                continue
            print(f"Visión Gemini {model}: {error}", file=sys.stderr)
            continue
    if quota_models == len(VISION_MODELS):
        print("Visión Gemini: cuota agotada en todos los modelos", file=sys.stderr)
        return None
    return []


def _vision_place(place, urls: list[str], api_key: str, max_photos: int):
    found: list[dict] = []
    for url in urls[:max_photos]:
        raw = _download(url, timeout=30)
        if not raw:
            continue
        items = _vision_with_fallback(raw, api_key)
        if items is None:
            return place, found, True
        found.extend(items)
    return place, found, False


def _ocr_menu_bytes(raw: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except Exception:
        return ""
    try:
        image = Image.open(BytesIO(raw)).convert("L")
    except Exception as error:
        print("OCR: no se pudo abrir imagen:", error, file=sys.stderr)
        return ""
    print("OCR: imagen", image.width, "x", image.height, "bytes", len(raw), file=sys.stderr)
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
        except Exception as error:
            print(f"OCR: psm{psm} error:", error, file=sys.stderr)
            continue
        print(f"OCR: psm{psm} len", len(texts[-1].strip()), file=sys.stderr)
    return "\n".join(texts)


def _clean_name(value: str) -> str:
    value = re.sub(r"^[\s•\-–—\d.)'‘’\"|]+", "", value)
    value = re.sub(r"^(?:[a-z€$'‘’\"|:;.,\-–—]|I)\s+(?=[A-ZÁÉÍÓÚÑ])", "", value)
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
        if line.startswith("("):
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
        if not price and len(name) > 40:
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


def _price_key(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _same_dish(first: str, second: str) -> bool:
    if not first or not second:
        return False
    if first == second:
        return True
    short, long = (first, second) if len(first) <= len(second) else (second, first)
    return len(short) >= 15 and short in long


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


GENERIC_NAME_TOKENS = {
    "cafeteria", "panaderia", "restaurante", "restaurant", "bakery", "food",
    "market", "tienda", "de", "del", "la", "el", "los", "las", "y", "and",
    "the", "gluten", "free", "sin",
}


def _name_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", _normalize(value))
        if len(token) > 1 and token not in GENERIC_NAME_TOKENS
    }


def _match_place(item: dict, by_url: dict, by_cid: dict, by_name: dict, by_ftid: dict | None = None):
    ftid = str(item.get("placeCid") or "").strip().lower()
    if by_ftid and ftid and ftid in by_ftid:
        return by_ftid[ftid]
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
    item_tokens = _name_tokens(item.get("placeName") or "")
    if item_tokens:
        for record in by_name.values():
            key_tokens = _name_tokens(record.name)
            if not key_tokens:
                continue
            common = item_tokens & key_tokens
            if len(common) / min(len(item_tokens), len(key_tokens)) >= 0.75:
                return record
    return None


def _collect_photos(
    items: list[dict],
    by_url: dict,
    by_cid: dict,
    by_name: dict,
    photos: dict[str, list[str]],
    only: set[str] | None = None,
    by_ftid: dict | None = None,
) -> None:
    for item in items:
        if item.get("photoCategory") not in {"menu", None, ""}:
            continue
        place = _match_place(item, by_url, by_cid, by_name, by_ftid)
        if place is None:
            continue
        if only is not None and place.ftid not in only:
            continue
        url = (
            item.get("photoUrlHighRes")
            or item.get("photoUrl")
            or item.get("thumbnailUrl")
        )
        if not url:
            continue
        photos.setdefault(place.ftid, []).append(url)


def _recent_run_items(token: str, limit: int) -> list[list[dict]]:
    """Datasets de las últimas corridas exitosas de UnitBytes, para reutilizar fotos."""
    query = urllib.parse.urlencode({"token": token, "limit": limit, "desc": "1"})
    try:
        response = _request(f"{API}/acts/{ACTOR}/runs?{query}")
    except Exception as error:
        print(f"Apify UnitBytes: no pude leer corridas recientes: {error}", file=sys.stderr)
        return []
    runs = (response.get("data") or {}).get("items") or []
    dataset_ids = [
        run.get("defaultDatasetId")
        for run in runs
        if run.get("status") == "SUCCEEDED" and run.get("defaultDatasetId")
    ]

    def fetch(dataset_id: str) -> list[dict]:
        try:
            return _fetch_items(token, dataset_id)
        except Exception:
            return []

    datasets: list[list[dict]] = []
    if dataset_ids:
        with ThreadPoolExecutor(max_workers=min(4, len(dataset_ids))) as pool:
            datasets = [items for items in pool.map(fetch, dataset_ids) if items]
    print(
        f"Apify UnitBytes: {len(runs)} corridas recientes, "
        f"{len(datasets)} datasets con fotos"
    )
    return datasets


def enrich_menus_photos(
    places,
    token: str,
    *,
    max_photos: int = 8,
    max_charge_usd: float = 2.0,
    timeout: int = 1200,
    today: str | None = None,
    vision_key: str | None = None,
    vision_max_photos: int = 3,
    vision_max_places: int = 12,
    vision_concurrency: int = 2,
    photo_cache: dict[str, list[str]] | None = None,
    refresh_photos: bool = False,
    reuse_recent_runs: int = 5,
    ocr: bool = True,
) -> int:
    targets = [place for place in places if getattr(place, "url", None)]
    if not targets:
        return 0

    today = today or date.today().isoformat()
    by_url = {place.url: place for place in targets}
    by_cid = {_cid(place.url): place for place in targets if _cid(place.url)}
    by_name = {_normalize(place.name): place for place in targets}
    by_ftid = {
        place.ftid.strip().lower(): place
        for place in targets
        if getattr(place, "ftid", None)
    }

    photos: dict[str, list[str]] = {}
    if photo_cache and not refresh_photos:
        for place in targets:
            urls = photo_cache.get(place.ftid) or []
            if urls:
                photos[place.ftid] = urls[:max_photos]
        print(
            f"Apify UnitBytes: caché con fotos para {len(photos)} locales, "
            f"se evita volver a raspar"
        )

    missing = [place for place in targets if not photos.get(place.ftid)]
    if missing and reuse_recent_runs > 0:
        missing_ids = {place.ftid for place in missing}
        for items in _recent_run_items(token, reuse_recent_runs):
            _collect_photos(items, by_url, by_cid, by_name, photos, only=missing_ids, by_ftid=by_ftid)
            missing_ids = {
                place.ftid for place in missing if not photos.get(place.ftid)
            }
            if not missing_ids:
                break
        if photos:
            print(
                f"Apify UnitBytes: fotos reutilizadas de corridas recientes "
                f"para {len(photos)} locales"
            )
        missing = [place for place in missing if not photos.get(place.ftid)]

    if missing:
        try:
            run = _start_run(
                token, [place.url for place in missing], max_photos, max_charge_usd, timeout
            )
            completed = _wait_run(token, run["id"], timeout + 300)
            status = completed.get("status")
            dataset_id = completed.get("defaultDatasetId") or run.get("defaultDatasetId")
            items = _fetch_items(token, dataset_id) if dataset_id else []
            print(f"Apify UnitBytes: {status}, {len(items)} fotos de menú")
        except Exception as error:
            print(f"Apify UnitBytes: fallo: {error}", file=sys.stderr)
            items = []
            status = "FAILED"
        if status in {"FAILED", "ABORTED"} and not photos:
            return 0

        _collect_photos(
            items,
            by_url,
            by_cid,
            by_name,
            photos,
            only={place.ftid for place in missing},
            by_ftid=by_ftid,
        )

    if photo_cache is not None:
        photo_cache.update({ftid: urls for ftid, urls in photos.items() if urls})

    print(
        f"Apify UnitBytes: {len(photos)} locales con fotos, "
        f"{sum(len(urls[:max_photos]) for urls in photos.values())} por OCR"
    )

    ocr_results: dict[str, list[dict]] = {}
    tasks = [
        (place.ftid, url)
        for place in targets
        for url in photos.get(place.ftid, [])[:max_photos]
    ]
    with_text = 0
    if tasks and not ocr:
        print("OCR: desactivado, se usará solo visión Gemini")
    if tasks and ocr:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_download, url): ftid for ftid, url in tasks}
            for future in as_completed(futures):
                ftid = futures[future]
                raw = future.result()
                if not raw:
                    print("OCR: descarga vacía", futures[future], file=sys.stderr)
                    continue
                text = _ocr_menu_bytes(raw)
                if not text:
                    continue
                with_text += 1
                ocr_results.setdefault(ftid, []).extend(_parse_menu_text(text))
    print(f"Apify UnitBytes: {with_text} fotos con texto OCR")

    vision_places = 0
    vision_dishes = 0
    if vision_key:
        pending = [
            place
            for place in targets
            if photos.get(place.ftid) and len(ocr_results.get(place.ftid) or []) < 2
        ]
        selected = pending[:vision_max_places]
        print(
            f"Visión Gemini: {len(pending)} locales con OCR insuficiente, "
            f"hasta {vision_max_places} por corrida, "
            f"concurrencia {vision_concurrency}"
        )
        if selected:
            with ThreadPoolExecutor(max_workers=max(1, vision_concurrency)) as pool:
                futures = {
                    pool.submit(
                        _vision_place,
                        place,
                        photos.get(place.ftid, []),
                        vision_key,
                        vision_max_photos,
                    ): place
                    for place in selected
                }
                for future in as_completed(futures):
                    place, found, quota_exhausted = future.result()
                    if quota_exhausted:
                        print("Visión Gemini: detenida por cuota", file=sys.stderr)
                        for pending_future in futures:
                            pending_future.cancel()
                        break
                    if not found:
                        continue
                    existing = ocr_results.setdefault(place.ftid, [])
                    added = 0
                    for dish in found:
                        key = _normalize(dish.get("name") or "")
                        if not key:
                            continue
                        match = next(
                            (
                                current
                                for current in existing
                                if _same_dish(key, _normalize(current.get("name") or ""))
                                and _price_key(current.get("price"))
                                == _price_key(dish.get("price"))
                            ),
                            None,
                        )
                        if match is not None:
                            if len(dish.get("name") or "") > len(match.get("name") or ""):
                                match["name"] = dish["name"]
                            continue
                        existing.append(dish)
                        added += 1
                    if added:
                        if added >= 2:
                            existing[:] = [
                                dish
                                for dish in existing
                                if dish.get("source") != "ocr" or dish.get("price")
                            ]
                        vision_places += 1
                        vision_dishes += added
                        print(
                            f"Visión Gemini: {place.name} -> {added} platos",
                            file=sys.stderr,
                        )
        print(
            f"Visión Gemini: {vision_dishes} platos nuevos en {vision_places} locales"
        )

    total = 0
    for place in targets:
        dishes = ocr_results.get(place.ftid) or []
        place.menu_dishes = _summary(dishes)
        place.menu_json = json.dumps(dishes, ensure_ascii=False) if dishes else None
        place.menu_at = today
        total += len(dishes)

    return total

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date
from urllib.parse import parse_qs, unquote, urlparse

API = "https://api.apify.com/v2"
ACTOR = "nomad-agent~google-maps-menu-scraper-managed"
POLL_SECONDS = 15


def _request(url: str, *, data: dict | None = None, timeout: int = 60):
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    request = urllib.request.Request(
        url, data=payload, headers=headers, method="POST" if payload else "GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _start_run(
    token: str,
    urls: list[str],
    language: str,
    max_photos: int,
    max_charge: float,
    timeout: int,
) -> dict:
    query = urllib.parse.urlencode(
        {
            "token": token,
            "timeout": timeout,
            "maxTotalChargeUsd": max_charge,
        }
    )
    payload = {
        "placeUrls": urls,
        "language": language,
        "maxMenuPhotos": max_photos,
    }
    response = _request(f"{API}/acts/{ACTOR}/runs?{query}", data=payload)
    return response["data"]


def _wait_run(token: str, run_id: str, timeout: int) -> dict:
    query = urllib.parse.urlencode({"token": token})
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = _request(f"{API}/actor-runs/{run_id}?{query}")
        run = response["data"]
        status = run.get("status")
        if status == "SUCCEEDED":
            return run
        if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
            raise RuntimeError(f"Apify terminó con estado {status}")
        time.sleep(POLL_SECONDS)
    raise TimeoutError("Apify no terminó dentro del tiempo esperado")


def _fetch_items(token: str, dataset_id: str) -> list[dict]:
    query = urllib.parse.urlencode(
        {"token": token, "format": "json", "clean": "true", "limit": 10000}
    )
    response = _request(f"{API}/datasets/{dataset_id}/items?{query}", timeout=120)
    if isinstance(response, list):
        return response
    return response.get("items", [])


def _clean_dish(item: dict) -> dict:
    ingredients = []
    for ingredient in item.get("ingredients") or []:
        if isinstance(ingredient, dict):
            name = ingredient.get("display_name") or ingredient.get("name")
        else:
            name = ingredient
        if name and name not in ingredients:
            ingredients.append(name)
    return {
        "name": item.get("name"),
        "original_name": item.get("originalName"),
        "category": item.get("category"),
        "price": item.get("price"),
        "description": item.get("description") or item.get("composition"),
        "ingredients": ingredients,
        "allergens": item.get("allergens"),
        "dietary_type": item.get("dietaryType"),
        "is_alcoholic": item.get("isAlcoholic"),
        "nutrition": item.get("nutritionInfo"),
    }


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip().lower()


def _cid(url: str) -> str:
    try:
        return parse_qs(urlparse(url).query).get("cid", [""])[0]
    except ValueError:
        return ""


def _match_place(item: dict, by_url: dict, by_ftid: dict, by_cid: dict, by_name: dict):
    url = item.get("place") or ""
    if url in by_url:
        return by_url[url]
    resolved = item.get("resolvedPlaceUrl") or ""
    match = re.search(r"!1s(0x[0-9a-fA-F]+):(0x[0-9a-fA-F]+)", resolved)
    if match:
        place = by_ftid.get(f"{match.group(1)}:{match.group(2)}")
        if place:
            return place
    cid = _cid(url) or _cid(resolved)
    if cid and cid in by_cid:
        return by_cid[cid]
    match = re.search(r"/maps/place/([^/@?]+)", resolved)
    if match:
        name = _normalize(unquote(match.group(1)).replace("+", " "))
        for key, place in by_name.items():
            if key and name and (key in name or name in key):
                return place
    return None


def _summary(dishes: list[dict]) -> str | None:
    parts: list[str] = []
    for dish in dishes:
        name = dish.get("name") or dish.get("original_name")
        if not name:
            continue
        label = name
        if dish.get("price"):
            label += f" ({dish['price']})"
        if dish.get("category"):
            label += f" · {dish['category']}"
        parts.append(label)
    return "; ".join(parts) if parts else None


def enrich_menus(
    places,
    token: str,
    *,
    language: str = "es",
    max_photos: int = 8,
    max_charge_usd: float = 2.0,
    chunk_size: int = 50,
    timeout: int = 1200,
    today: str | None = None,
) -> int:
    targets = [place for place in places if getattr(place, "url", None)]
    if not targets:
        return 0

    today = today or date.today().isoformat()
    chunks = [targets[index : index + chunk_size] for index in range(0, len(targets), chunk_size)]
    per_run_cap = max(0.05, round(max_charge_usd / max(1, len(chunks)), 4))
    total = 0

    for chunk in chunks:
        by_url = {place.url: place for place in chunk}
        by_ftid = {place.ftid: place for place in chunk}
        by_cid = {_cid(place.url): place for place in chunk if _cid(place.url)}
        by_name = {_normalize(place.name): place for place in chunk}
        try:
            run = _start_run(
                token,
                list(by_url),
                language,
                max_photos,
                per_run_cap,
                timeout,
            )
            completed = _wait_run(token, run["id"], timeout + 300)
            items = _fetch_items(token, completed.get("defaultDatasetId") or run["defaultDatasetId"])
        except Exception as error:
            print(f"Apify: fallo en un lote: {error}", file=sys.stderr)
            continue

        grouped: dict[str, list[dict]] = {}
        seen: dict[str, set[tuple]] = {}
        for item in items:
            if item.get("recordType") != "DISH":
                continue
            place = _match_place(item, by_url, by_ftid, by_cid, by_name)
            if place is None:
                continue
            dish = _clean_dish(item)
            key = (dish.get("name"), dish.get("price"), dish.get("category"))
            if key in seen.setdefault(place.ftid, set()):
                continue
            seen[place.ftid].add(key)
            grouped.setdefault(place.ftid, []).append(dish)

        for place in chunk:
            dishes = grouped.get(place.ftid) or []
            place.menu_dishes = _summary(dishes)
            place.menu_json = json.dumps(dishes, ensure_ascii=False) if dishes else None
            place.menu_at = today
            total += len(dishes)

    return total

from __future__ import annotations

import html
import json
import re

import requests

from .base import MenuItem, MenuResult, PlaceContext

API = "https://api.apparta.co/establishment-menu-items"
URL_RE = re.compile(r"menu\.tu-mesa\.com/([^/]+)/(\d+)/menu", re.I)


def _clean(value) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _clp(value) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return f"${int(round(number)):,}".replace(",", ".")


def _labels(raw) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [_clean(item.get("label")) for item in data if isinstance(item, dict) and item.get("label")]


def _prices(raw, fallback):
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        data = []
    result = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                value = float(item.get("price"))
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.append((_clean(item.get("description")), value))
    if not result:
        try:
            value = float(fallback or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            result.append((None, value))
    return result


def _variant(description: str | None) -> str | None:
    if not description:
        return None
    value = re.sub(r"^Schop(?:\s+de)?\s+", "", description, flags=re.I).strip()
    return value or None


class AppartaAdapter:
    name = "apparta"

    def detect(self, ctx: PlaceContext) -> bool:
        url = (ctx.menu_url or ctx.website or "").lower()
        return "menu.tu-mesa.com" in url or "api.apparta.co" in url

    def _fetch(self, ctx: PlaceContext, branch_id: str, slug: str):
        session = ctx.session or requests.Session()
        response = session.get(
            API,
            params={
                "$client[source]": "menuWeb",
                "$client[establishment_branch_id]": branch_id,
                "$client[establishment_slug]": slug,
            },
            timeout=60,
        )
        return response.json()

    def _target(self, ctx: PlaceContext) -> tuple[str, str] | None:
        url = ctx.menu_url or ctx.website or ""
        match = URL_RE.search(url)
        if match:
            return match.group(2), match.group(1)
        if "api.apparta.co" in url:
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(url).query)
            branch_id = (query.get("$client[establishment_branch_id]") or query.get("establishment_branch_id") or [None])[0]
            slug = (query.get("$client[establishment_slug]") or query.get("establishment_slug") or [""])[0]
            if branch_id:
                return str(branch_id), str(slug)
        return None

    def extract(self, ctx: PlaceContext) -> MenuResult:
        target = self._target(ctx)
        if not target:
            return MenuResult("empty", [], "apparta")
        branch_id, slug = target
        data = self._fetch(ctx, branch_id, slug)
        if not isinstance(data, list):
            return MenuResult("empty", [], "apparta", ctx.menu_url)
        items: list[MenuItem] = []
        seen = set()
        for row in data:
            if not isinstance(row, dict):
                continue
            base = _clean(row.get("menu_item_name"))
            if not base:
                continue
            category = _clean(row.get("menu_item_category_name")) or None
            labels = _labels(row.get("menu_item_labels"))
            description = " · ".join(
                part for part in [" · ".join(labels), _clean(row.get("menu_item_description"))] if part
            ) or None
            for variant, value in _prices(row.get("prices_list"), row.get("price")):
                name = base
                clean_variant = _variant(variant)
                if clean_variant and clean_variant.casefold() not in base.casefold():
                    name = f"{base} - {clean_variant}"
                key = name.casefold()
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    MenuItem(
                        name=name,
                        price=_clp(value),
                        category=category,
                        description=description,
                        url=ctx.menu_url,
                        source="apparta",
                    )
                )
        if not items:
            return MenuResult("empty", [], "apparta", ctx.menu_url)
        return MenuResult("ok", items, "apparta", ctx.menu_url)

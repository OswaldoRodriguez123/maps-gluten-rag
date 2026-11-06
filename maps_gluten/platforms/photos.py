from __future__ import annotations

import json
import os
from datetime import date

from maps_gluten import photos
from maps_gluten.extract import Place

from .base import MenuItem, MenuResult, PlaceContext


class PhotosAdapter:
    name = "photos"

    def detect(self, ctx: PlaceContext) -> bool:
        return bool(ctx.allow_photos and not ctx.dry_run)

    def extract(self, ctx: PlaceContext) -> MenuResult:
        if not ctx.allow_photos or ctx.dry_run:
            return MenuResult(
                "needs_manual",
                [],
                "photo",
                error="fotos desactivadas en esta corrida",
            )
        token = os.getenv("APIFY_TOKEN", "").strip()
        if not token:
            return MenuResult(
                "needs_manual",
                [],
                "photo",
                error="falta APIFY_TOKEN para leer fotos de menú",
            )
        metadata = (ctx.record or {}).get("metadata") or {}
        place = Place(
            ftid=ctx.place_id,
            name=ctx.name,
            address=metadata.get("address"),
            category=metadata.get("category"),
            rating=metadata.get("rating"),
            reviews=metadata.get("reviews"),
            note=None,
            url=metadata.get("url") or "",
            website=ctx.website,
            dishes=metadata.get("dishes"),
            review_dishes=metadata.get("review_dishes"),
        )
        try:
            photos.enrich_menus_photos(
                [place],
                token,
                max_photos=8,
                max_charge_usd=0.5,
                today=date.today().isoformat(),
                vision_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
                vision_max_photos=3,
                vision_max_places=1,
                ocr=False,
            )
        except Exception as error:  # noqa: BLE001
            return MenuResult(
                "error",
                [],
                "photo",
                error=f"{type(error).__name__}: {error}"[:180],
            )
        if not place.menu_json:
            return MenuResult("empty", [], "photo", ctx.website)
        try:
            dishes = json.loads(place.menu_json)
        except (json.JSONDecodeError, TypeError):
            return MenuResult("empty", [], "photo", ctx.website)
        items = [
            MenuItem(
                name=dish.get("name") or "",
                price=dish.get("price"),
                category=dish.get("category"),
                description=dish.get("description"),
                url=ctx.website,
                source="photo",
            )
            for dish in dishes
            if isinstance(dish, dict) and dish.get("name")
        ]
        if not items:
            return MenuResult("empty", [], "photo", ctx.website)
        return MenuResult("ok", items[: ctx.max_items], "photo", ctx.website)

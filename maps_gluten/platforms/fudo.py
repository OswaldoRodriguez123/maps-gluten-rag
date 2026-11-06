from __future__ import annotations

from maps_gluten import fudo

from .base import MenuItem, MenuResult, PlaceContext


class FudoAdapter:
    name = "fudo"

    def detect(self, ctx: PlaceContext) -> bool:
        url = (ctx.menu_url or ctx.website or "").lower()
        return "menu.fu.do" in url

    def extract(self, ctx: PlaceContext) -> MenuResult:
        url = ctx.menu_url or ctx.website
        if not url:
            return MenuResult("empty", [], "fudo")
        items = [
            MenuItem(
                name=dish.get("name") or "",
                price=dish.get("price"),
                category=dish.get("category"),
                description=dish.get("description"),
                url=url,
                source="fudo",
            )
            for dish in fudo.fetch_menu(url)
            if dish.get("name")
        ]
        if not items:
            return MenuResult("empty", [], "fudo", url)
        return MenuResult("ok", items, "fudo", url)

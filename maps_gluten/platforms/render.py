from __future__ import annotations

from maps_gluten import enrich

from .base import MenuItem, MenuResult, PlaceContext


class RenderAdapter:
    name = "render"

    def detect(self, ctx: PlaceContext) -> bool:
        return bool(ctx.website and ctx.browser)

    def extract(self, ctx: PlaceContext) -> MenuResult:
        if not ctx.website or not ctx.browser:
            return MenuResult("empty", [], "web-render")
        page = ctx.browser.new_page()
        try:
            names = enrich._render_site_products(page, ctx.website)
        finally:
            page.close()
        items = [
            MenuItem(name=name, price=None, source="web-render", url=ctx.website)
            for name in names
            if name
        ]
        if not items:
            return MenuResult("empty", [], "web-render", ctx.website)
        return MenuResult("ok", items[: ctx.max_items], "web-render", ctx.website)

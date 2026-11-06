from __future__ import annotations

from .base import Adapter, MenuItem, MenuResult, PlaceContext

__all__ = ["Adapter", "MenuItem", "MenuResult", "PlaceContext", "extract", "default_adapters"]


def default_adapters() -> list[Adapter]:
    """Adaptadores en orden de prioridad.

    Se importan dentro de la función para evitar imports circulares y para
    que los tests puedan inyectar adaptadores falsos.
    """
    try:
        from .apparta import AppartaAdapter
        from .fudo import FudoAdapter
        from .jsonld import JsonLdAdapter
        from .photos import PhotosAdapter
        from .rappi import RappiAdapter
        from .render import RenderAdapter
        from .shopify import ShopifyAdapter
        from .woocommerce import WooCommerceAdapter
    except ImportError:
        return []
    return [
        FudoAdapter(),
        AppartaAdapter(),
        RappiAdapter(),
        WooCommerceAdapter(),
        ShopifyAdapter(),
        JsonLdAdapter(),
        RenderAdapter(),
        PhotosAdapter(),
    ]


def extract(ctx: PlaceContext, adapters: list[Adapter] | None = None) -> MenuResult:
    """Prueba adaptadores y devuelve el primer resultado con ítems."""
    last: MenuResult | None = None
    for adapter in adapters if adapters is not None else default_adapters():
        try:
            if not adapter.detect(ctx):
                continue
            result = adapter.extract(ctx)
        except Exception as error:  # noqa: BLE001 - un adaptador no debe cortar el flujo
            last = MenuResult(
                "error",
                [],
                getattr(adapter, "name", "unknown"),
                error=f"{type(error).__name__}: {error}"[:180],
            )
            continue
        if result.status == "ok" and result.items:
            return result
        if result.status in {"needs_manual", "error"}:
            last = result
    return last or MenuResult("needs_manual", [], "none")

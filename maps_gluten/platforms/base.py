from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class MenuItem:
    name: str
    price: str | None = None
    category: str | None = None
    description: str | None = None
    url: str | None = None
    source: str = "web"


@dataclass
class MenuResult:
    status: str
    items: list[MenuItem] = field(default_factory=list)
    source: str = "web"
    url: str | None = None
    error: str | None = None


@dataclass
class PlaceContext:
    record: dict
    place_id: str
    name: str
    website: str | None = None
    menu_url: str | None = None
    order_urls: list[dict] = field(default_factory=list)
    session: Any = None
    browser: Any = None
    allow_photos: bool = True
    dry_run: bool = False
    max_items: int = 500


class Adapter(Protocol):
    name: str

    def detect(self, ctx: PlaceContext) -> bool: ...

    def extract(self, ctx: PlaceContext) -> MenuResult: ...

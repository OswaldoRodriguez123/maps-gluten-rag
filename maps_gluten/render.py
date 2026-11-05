from __future__ import annotations

from collections import Counter

from .dietary import dietary_tags, place_is_gluten_free


def _is_dish(item: dict) -> bool:
    return item.get("kind") in (None, "dish") and item.get("status") in (None, "ok")


def _is_category(item: dict) -> bool:
    return item.get("kind") == "category" and item.get("status") in (None, "ok")


def _item_price(item: dict) -> str | None:
    return item.get("price_display") or item.get("price")


def _item_tags(item: dict, place_gluten_free: bool) -> list[str]:
    tags = set(item.get("dietary_tags") or [])
    tags.update(
        dietary_tags(
            item.get("name") or "",
            item.get("description"),
            item.get("category"),
            place_gluten_free,
        )
    )
    if place_gluten_free:
        tags.discard("sin gluten")
    return sorted(tags)


def _item_line(item: dict, place_gluten_free: bool) -> str | None:
    name = (item.get("name") or "").strip()
    if not name:
        return None
    price = _item_price(item)
    line = f"- {name} — {price}" if price else f"- {name}"
    tags = _item_tags(item, place_gluten_free)
    if tags:
        line += f" [{', '.join(tags)}]"
    return line


def menu_lines(items: list[dict], place_gluten_free: bool = False) -> list[str]:
    """Una carta en Markdown: ### Carta, #### Categoría y un plato por línea."""
    dishes = [item for item in items if _is_dish(item)]
    if not dishes:
        return []
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    uncategorized: list[dict] = []
    for item in dishes:
        category = (item.get("category") or "").strip()
        if not category:
            uncategorized.append(item)
            continue
        if category not in groups:
            groups[category] = []
            order.append(category)
        groups[category].append(item)

    lines = ["", "### Carta", ""]
    for category in order:
        lines.append(f"#### {category}")
        lines.append("")
        for item in groups[category]:
            line = _item_line(item, place_gluten_free)
            if line:
                lines.append(line)
        lines.append("")
    if uncategorized:
        if order:
            lines.append("#### Otros")
            lines.append("")
        for item in uncategorized:
            line = _item_line(item, place_gluten_free)
            if line:
                lines.append(line)
        lines.append("")
    return lines


def categories_from_items(items: list[dict]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        label = (value or "").strip()
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            labels.append(label)

    for item in items:
        if not _is_dish(item) and not _is_category(item):
            continue
        if _is_category(item):
            add(item.get("name"))
        else:
            add(item.get("category"))
    return labels


def dietary_summary(items: list[dict], place_name: str, place_category: str | None) -> dict:
    place_gluten_free = place_is_gluten_free(place_name, place_category)
    dishes = [item for item in items if _is_dish(item)]
    gluten_free = vegan = lactose_free = 0
    for item in dishes:
        tags = _item_tags(item, place_gluten_free)
        if "sin gluten" in tags:
            gluten_free += 1
        if "vegano" in tags:
            vegan += 1
        if "sin lactosa" in tags:
            lactose_free += 1
    return {
        "gluten_free": place_gluten_free,
        "total": len(dishes),
        "gluten_free_items": gluten_free,
        "vegan_items": vegan,
        "lactose_free_items": lactose_free,
    }


def dietary_line(summary: dict) -> str | None:
    parts: list[str] = []
    if summary["gluten_free"]:
        parts.append("local 100% sin gluten")
    elif summary["gluten_free_items"]:
        parts.append(f"{summary['gluten_free_items']} platos sin gluten")
    if summary["vegan_items"]:
        parts.append(f"{summary['vegan_items']} veganos")
    if summary["lactose_free_items"]:
        parts.append(f"{summary['lactose_free_items']} sin lactosa")
    return f"- **Dietético:** {', '.join(parts)}" if parts else None


def categories_lines(categories: list[str]) -> list[str]:
    if not categories:
        return []
    lines = ["", "### Qué vende", ""]
    lines.extend(f"- {category}" for category in categories)
    lines.append("")
    return lines


def _titles(records: list[dict]) -> dict[str, str]:
    counts = Counter(record["metadata"]["name"] for record in records)
    titles: dict[str, str] = {}
    for record in records:
        metadata = record["metadata"]
        title = metadata["name"]
        if counts[title] > 1:
            extra = metadata.get("address") or metadata.get("category")
            if extra:
                title = f"{title} ({extra.split(',')[0].strip()})"
        titles[record["id"]] = title
    return titles


def document(records: list[dict], menus: dict[str, list[dict]], today: str) -> str:
    titles = _titles(records)
    lines = [
        "# Base de Datos: Locales Sin Gluten Guardados en Google Maps",
        "",
        f"_Actualizado: {today} · {len(records)} lugares · Fuente: lista de Google Maps_",
        "",
        "Cada sección corresponde a un local guardado por el usuario en Google Maps.",
        "",
    ]
    for record in records:
        metadata = record["metadata"]
        lines.append(f"## {titles[record['id']]}")
        lines.append(f"- **Ubicación:** {metadata.get('address') or 'No disponible'}")
        if metadata.get("category"):
            lines.append(f"- **Categoría:** {metadata['category']}")
        if metadata.get("rating"):
            value = f"- **Valoración:** {metadata['rating']} / 5"
            if metadata.get("reviews"):
                value += f" ({metadata['reviews']} reseñas)"
            lines.append(value)
        lines.append(f"- **Enlace:** {metadata['url']}")
        if metadata.get("website"):
            lines.append(f"- **Web:** {metadata['website']}")
        if metadata.get("dishes"):
            lines.append(f"- **Menciona en su web:** {metadata['dishes']}")
        if metadata.get("review_dishes"):
            lines.append(f"- **Menciona en reseñas:** {metadata['review_dishes']}")
        lines.append(
            f"- **Fecha de registro:** {metadata.get('saved_on') or metadata.get('first_seen')}"
        )
        items = menus.get(record["id"]) or [
            {"name": dish.get("name"), "price": dish.get("price")}
            for dish in metadata.get("menu") or []
            if dish.get("name")
        ]
        summary = dietary_summary(items, metadata["name"], metadata.get("category"))
        diet = dietary_line(summary)
        if diet:
            lines.append(diet)
        lines.extend(categories_lines(categories_from_items(items)))
        lines.extend(menu_lines(items, summary["gluten_free"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

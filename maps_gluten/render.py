from __future__ import annotations

from collections import Counter


def _item_line(item: dict) -> str | None:
    name = (item.get("name") or "").strip()
    if not name:
        return None
    price = item.get("price")
    return f"- {name} — {price}" if price else f"- {name}"


def menu_lines(items: list[dict]) -> list[str]:
    """Una carta en Markdown: ### Carta, #### Categoría y un plato por línea."""
    if not items:
        return []
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    uncategorized: list[dict] = []
    for item in items:
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
            line = _item_line(item)
            if line:
                lines.append(line)
        lines.append("")
    if uncategorized:
        if order:
            lines.append("#### Otros")
            lines.append("")
        for item in uncategorized:
            line = _item_line(item)
            if line:
                lines.append(line)
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
        lines.extend(menu_lines(items))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

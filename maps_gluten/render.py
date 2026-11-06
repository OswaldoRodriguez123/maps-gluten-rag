from __future__ import annotations

import re
import unicodedata
from collections import Counter

from .dietary import dietary_tags, place_is_gluten_free


def _norm(text: object) -> str:
    """Minusculas sin acentos ni puntuacion, para comparar categorias/nombres."""
    decomposed = unicodedata.normalize("NFKD", str(text or "").lower())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    spaced = re.sub(r"[^a-z0-9% ]", " ", plain)
    return re.sub(r"\s+", " ", spaced).strip()


# Categorias (normalizadas) que son unicamente liquidos para beber.
DRINK_CATEGORIES = frozenset(
    {
        "bebidas",
        "bebidas frias",
        "bebidas calientes",
        "bebidas vegetales",
        "bebidas con lacteos",
        "bebidas y jugos frios",
        "bebidas y aguas",
        "aguas jugos y bebidas",
        "bebidas y jugos",
        "otras bebidas",
        "variedad de bebidas",
        "bebida",
        "bebida en lata",
        "bebestibles",
        "bebestibles drinks",
        "para tomar",
        "to drink",
        "jugos",
        "jugos naturales",
        "refrescos y jugos naturales",
        "bebidas de cafe especiales",
        "cafe",
        "cafes",
        "cafe con leche",
        "cafe especialidad",
        "cafe de especialidad",
        "cafeteria",
        "cafeteria tradicional",
        "cafeteria de especialidad",
        "cafeteria italiana",
        "cafe helado",
        "cafes frios",
        "cafe sin lactosa",
        "cafe e infusiones",
        "cafe te y hierbas",
        "cafe te y chocolate",
        "cafe filtrado",
        "te",
        "te caliente",
        "te helado",
        "te e infusiones",
        "te infusiones y cafe",
        "te infusiones",
        "infusiones",
        "lattes y te",
        "latte caliente",
        "iced coffee",
        "caliente",
        "frio",
        "recomendados frios",
        "te de origen",
        "teteria",
        "chocolate caliente",
        "cervezas",
        "cerveza artesanal",
        "cerveza de barril",
        "cerveza de especialidad",
        "cerveza internacional",
        "cerveza nacional",
        "destilados y licores",
        "vinos y espumantes",
        "mocktails",
        "mocktails sin alcohol",
        "cocteles clasicos",
        "cocteles de la casa",
        "cocktails",
        "sour",
        "spritz",
        "pisco sour",
        "pisco bebida",
        "jarra de coctel",
        "jarras y copas",
        "botellas",
        "vodka",
        "whisky",
        "schop",
        "smoothies",
        "smoothies y milkshakes",
        "smoothie",
        "batidos proteicos",
        "frappe",
        "frappe shake",
        "matcha jugos",
        "matcha",
        "liquido para smoothie",
        "syrups y leches",
        "modificador de bebida",
        "metodos de filtrado",
        "haz tu bebida unica",
    }
)

# Categorias no comestibles (limpieza, higiene, hogar, regalo).
NO_EDIBLE_CATEGORIES = frozenset(
    {"aseo y limpieza", "aseo y cuidado", "higiene bucal", "hogar", "regalo packaging"}
)

_DRINK_NAME_PATTERNS = (
    r"\bcafe\b",
    r"\bcafes\b",
    r"\bespresso\b",
    r"\bexpreso\b",
    r"\bexpresso\b",
    r"\bespressini\b",
    r"\blatte\b",
    r"\bcappuccino\b",
    r"\bcapuccino\b",
    r"\bcappuchino\b",
    r"\bcapuchino\b",
    r"\bbarista\b",
    r"\bmacchiato\b",
    r"\bmacchiatto\b",
    r"\bmachiato\b",
    r"\bcortado\b",
    r"\blungo\b",
    r"\bristretto\b",
    r"\bflat white\b",
    r"\bcold brew\b",
    r"\bfrappuccino\b",
    r"\bfrapuccino\b",
    r"\bfrappe\b",
    r"\bfrappa\b",
    r"\baffogato\b",
    r"\bmocha\b",
    r"\bmocaccino\b",
    r"\bmocachino\b",
    r"\bmochaccino\b",
    r"\bte\b",
    r"\btea\b",
    r"\binfusion\b",
    r"\binfusiones\b",
    r"\btetera\b",
    r"\bjugo\b",
    r"\bjugos\b",
    r"\bzumo\b",
    r"\bbebida\b",
    r"\bbebidas\b",
    r"\bbebestible\b",
    r"\brefresco\b",
    r"\bgaseosa\b",
    r"\blimonada\b",
    r"\bnaranjada\b",
    r"\bcoca cola\b",
    r"\bcola\b",
    r"\bsprite\b",
    r"\bfanta\b",
    r"\bagua\b",
    r"\bkombucha\b",
    r"\bsmoothie\b",
    r"\bmilkshake\b",
    r"\bmalteada\b",
    r"\bbatido\b",
    r"\bcerveza\b",
    r"\bcervezas\b",
    r"\bvino\b",
    r"\bvinos\b",
    r"\bespumante\b",
    r"\bpisco\b",
    r"\bvodka\b",
    r"\bwhiskey\b",
    r"\bwhisky\b",
    r"\btequila\b",
    r"\bbrandy\b",
    r"\blicor\b",
    r"\bdestilado\b",
    r"\bron\b",
    r"\bchampagne\b",
    r"\bcocktail\b",
    r"\bcocktails\b",
    r"\bcoctel\b",
    r"\bcocteles\b",
    r"\bmocktail\b",
    r"\bmojito\b",
    r"\bmargarita\b",
    r"\bspritz\b",
    r"\bpisco sour\b",
    r"\bmatcha\b",
    r"\bchai\b",
    r"\bchocolate caliente\b",
    r"\bleche\b",
    r"\bleches\b",
    r"\bgolden milk\b",
    r"\bhot chocolate\b",
    r"\biced coffee\b",
    r"\bice coffee\b",
    r"\bice tea\b",
    r"\btonic\b",
    r"\btonica\b",
)

_DRINK_NAME_RE = re.compile("|".join(_DRINK_NAME_PATTERNS))

_NO_EDIBLE_NAME_RE = re.compile(
    r"\bperfume\b|\bedp\b|\bedt\b|\bdetergente\b|\blavalozas\b|\bbolsa de basura\b|"
    r"\bpasta dental\b|\benjuague bucal\b|\bdesodorante\b|\bsuero\b|\bcotonitos\b|"
    r"\btarjeta de regalo\b|\btote bag\b|\bbombilla\b|\bmortero\b"
)

# Marcas de comida (normalizadas) que, si aparecen antes que la bebida,
# indican un solido: "torta de cafe", "chocolate negro con cafe".
_FOOD_MARKERS = (
    "torta",
    "queque",
    "tarta",
    "pie de",
    "brownie",
    "muffin",
    "galleta",
    "galletita",
    "alfajor",
    "pizza",
    "sandwich",
    "sanguch",
    "croissant",
    "medialuna",
    "panqueque",
    "pancake",
    "waffle",
    "crepe",
    "profiterol",
    "pastel",
    "helado",
    "gelato",
    "bites",
    "bite",
    "chocolate negro",
    "chocolate blanco",
    "chocolate con leche",
    "cobertura de chocolate",
    "bombon",
    "barra",
    "yogurt",
    "yoghurt",
    "desayuno",
    "paila",
    "macarron",
    "macaroni",
    "pasta",
    "dulce",
    "crema",
    "completo",
    "hamburguesa",
    "empanada",
    "papas",
    "pepino",
)


def is_edible(item: dict) -> bool:
    """True si el item es comestible (no liquido ni no comestible).

    Solo filtra en el documento: no borra datos crudos (JSONL/SQLite).
    """
    category = _norm(item.get("category"))
    if category in NO_EDIBLE_CATEGORIES:
        return False
    name = _norm(item.get("name"))
    if _NO_EDIBLE_NAME_RE.search(name):
        # "suero" puede ser parte de un nombre de comida en teoria,
        # pero en este dataset es cosmetico; se filtra igual.
        return False
    # Tortas dulces "3 leches" siempre son comestibles (bizcocho),
    # aunque el nombre contenga "leches".
    if re.search(r"\b(?:tres|cuatro|3|4)\s+leches\b", name):
        return True
    drink = _DRINK_NAME_RE.search(name)
    # "para el cafe/te" describe comida de acompanamiento, no bebida.
    if drink and "para el cafe" in name:
        return True
    food_index = None
    for marker in _FOOD_MARKERS:
        pos = name.find(marker)
        if pos != -1 and (food_index is None or pos < food_index):
            food_index = pos
    if drink:
        # Si la comida aparece antes que la bebida ("torta de cafe"),
        # es un solido; si la bebida va primero ("cafe helado"), es liquido.
        if food_index is not None and food_index < drink.start():
            return True
        return False
    if category in DRINK_CATEGORIES:
        # Categoria de bebidas sin marca de comida ni palabra de bebida
        # (ej. "Hoegaarden", "Alto del Carmen"): igual es liquido.
        # Con marca de comida (ej. galletas mal ubicadas en
        # "Cafe e infusiones") se mantiene como comestible.
        if food_index is not None:
            return True
        return False
    return True


def _is_dish(item: dict) -> bool:
    return item.get("kind") in (None, "dish") and item.get("status") in (None, "ok")


def _is_category(item: dict) -> bool:
    return item.get("kind") == "category" and item.get("status") in (None, "ok")


def _edible_dishes(items: list[dict]) -> list[dict]:
    return [item for item in items if _is_dish(item) and is_edible(item)]


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
    dishes = _edible_dishes(items)
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
            normalized = _norm(item.get("name"))
            if normalized in DRINK_CATEGORIES or normalized in NO_EDIBLE_CATEGORIES:
                continue
            add(item.get("name"))
        else:
            if not is_edible(item):
                continue
            add(item.get("category"))
    return labels


def dietary_summary(items: list[dict], place_name: str, place_category: str | None) -> dict:
    place_gluten_free = place_is_gluten_free(place_name, place_category)
    dishes = _edible_dishes(items)
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

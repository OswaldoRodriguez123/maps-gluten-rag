from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maps_gluten.dietary import dietary_tags, place_is_gluten_free  # noqa: E402

CATEGORY_WORDS = {
    "sandwich", "sandwiches", "sándwich", "sándwiches", "empanada",
    "empanadas", "sopaipilla", "sopaipillas", "pizza", "pizzas",
    "pasteleria", "pastelería", "jugo", "jugos", "jugos naturales",
    "bebida", "bebidas", "postre", "postres", "cafeteria", "cafetería",
    "helado", "helados", "ensalada", "ensaladas", "torta", "tortas",
    "galleta", "galletas", "panaderia", "panadería", "desayuno",
    "desayunos", "almuerzo", "almuerzos", "menu", "menú", "carta",
    "otros", "promocion", "promociones", "vegano", "veganos",
    "vegana", "veganas", "tostadas", "tostadas francesas",
    "pailas de huevo", "wraps", "smoothies", "milkshakes",
    "iced coffee", "masas dulces", "chocolate caliente",
    "te infusiones", "té infusiones", "bebidas y jugos frios",
    "sandwiches y pizzas", "wraps y ensaladas",
    "smoothies y milkshakes",
}
FOOD_STEMS = {
    "pizza", "empanad", "sopaipill", "sandwich", "sándwich", "tort",
    "gallet", "jug", "café", "cafe", "té", "te", "helad", "ensalad",
    "sopa", "ceviche", "past", "arroz", "carn", "poll", "pescad",
    "marisc", "complet", "churrasc", "hamburgues", "wrap", "quiche",
    "pan", "postre", "chocolat", "muffin", "croissant", "baguette",
    "focaccia", "waffle", "milkshake", "smoothie", "limonad", "cervez",
    "vino", "agua", "bebid",
}
SPLIT_WORDS = (
    " BASE DE ", " BASE ", " CON ", " RELLENO ", " ACOMPAÑAD",
    " INGREDIENTES", " INCLUYE",
)
SUSPICIOUS = re.compile(r"[;|\\_*?¿!¡«»]")
CONNECTOR_END = re.compile(r"\b(y|de|con|la|el|los|las|del|al|en|para|por)$", re.I)
STORE_SOURCES = {"woocommerce", "shopify", "web-product", "web-jsonld", "fudo", "apparta", "rappi"}
STORE_PLACES = {
    "Sin Culpa Market", "Patagonia Schokoland", "Productos El Pueblo",
    "Violeta Patisserie", "Dulces aplv", "Mercadito sano y natural",
    "Pastelería La Celeste", "Thani Gluten Free", "ALLFREE",
    "BuganVilla cafe & market", "COMERCIAL RAKKO", "Fain",
    "Pizzeria Latinoamericana",
}
UNIT_TAILS = {"ml", "l", "lt", "g", "gr", "grs", "kg", "cc", "cm", "mm", "un", "und", "uds", "u"}
def clean_text(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def name_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def is_category_name(name: str) -> bool:
    key = name_key(name)
    if key in CATEGORY_WORDS:
        return True
    return bool(
        re.search(
            r"\b(sin gluten|libre de gluten|libres de gluten|vegan|vegetarian|celiac)\b",
            key,
        )
    )


def clean_name(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"\$\s*\d[\d.,]*", "", text)
    text = re.sub(r"^[\s•\-–—'\"“”|]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—:;|")
    return re.sub(r"[.,;:_\-–—]+$", "", text).strip()


def split_long_description(name: str, description: str | None) -> tuple[str, str | None]:
    if len(name) <= 60:
        return name, description
    upper = name.upper()
    for separator in SPLIT_WORDS:
        index = upper.find(separator)
        if index < 3:
            continue
        left = name[:index].strip(" -–—:,;")
        right = name[index + len(separator) :].strip(" -–—:,;")
        if len(left) >= 3 and len(right) >= 8:
            merged = right + (". " + description if description else "")
            return left, merged.strip()
    return name, description


def split_name_description(raw_name: str, raw_description) -> tuple[str, str | None]:
    name = clean_name(raw_name)
    description = clean_text(raw_description) or None
    if ":" in name:
        left, right = name.split(":", 1)
        left = left.strip(" -–—")
        right = right.strip(" -–—")
        if len(left) >= 3 and len(right) >= 8:
            name = left
            description = (right + (". " + description if description else "")).strip()
    name, description = split_long_description(name, description)
    if description and name_key(description) == name_key(name):
        description = None
    return name, description


def parse_price(raw) -> tuple[float | int | None, str, str | None]:
    if raw is None:
        return None, "CLP", None
    raw_text = clean_text(raw)
    if not raw_text:
        return None, "CLP", None
    upper = raw_text.upper()
    if "€" in raw_text:
        currency = "EUR"
    elif "US$" in upper or "USD" in upper:
        currency = "USD"
    else:
        currency = "CLP"
    text = re.sub(r"(?i)\b(clp|pesos?|usd)\b", " ", raw_text)
    text = text.replace("$", " ").replace("€", " ").replace(".-", " ")
    match = re.search(r"\d[\d.,]*", text)
    if not match:
        return None, currency, "precio no parseable"
    number = match.group(0).rstrip(".,")
    if not number:
        return None, currency, "precio no parseable"
    try:
        if "," in number and "." in number:
            last = max(number.rfind(","), number.rfind("."))
            integer = re.sub(r"[.,]", "", number[:last])
            decimal = number[last + 1 :]
            value = float(f"{integer}.{decimal}")
        elif "." in number:
            parts = number.split(".")
            if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
                value = float("".join(parts))
            else:
                value = float(number)
        elif "," in number:
            parts = number.split(",")
            if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
                value = float("".join(parts))
            else:
                value = float(number.replace(",", "."))
        else:
            value = float(number)
    except ValueError:
        return None, currency, "precio no parseable"
    if value <= 0:
        return None, currency, "precio no parseable"
    if currency == "CLP" and value < 100 and re.search(r"[.,]\d{1,2}$", number):
        return None, currency, "precio ambiguo"
    if currency == "CLP":
        return int(round(value)), currency, None
    return round(value, 2), currency, None


def format_price(value: float | int | None, currency: str) -> str | None:
    if value is None:
        return None
    if currency == "CLP":
        return f"${int(value):,}".replace(",", ".")
    if currency == "EUR":
        text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"€{text}"
    return f"US${value:,.2f}"


def food_types(name: str) -> set[str]:
    low = name.lower()
    return {
        stem
        for stem in FOOD_STEMS
        if re.search(rf"(?<![a-z]){re.escape(stem)}", low)
    }


def classify(
    name: str, price_value, category: str | None, source: str = "photo"
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    score = 100
    store = source in STORE_SOURCES
    if not name or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", name):
        return "rejected", ["sin letras"]
    if re.search(r"\b(producto de prueba|test|demo|ejemplo)\b", name, re.I):
        return "rejected", ["producto de prueba"]
    if name[0].islower() and not store:
        score -= 30
        reasons.append("empieza en minúscula")
    if "," in name and not store:
        score -= 45 if name.count(",") >= 2 else 30
        reasons.append("coma de descripción")
    if SUSPICIOUS.search(name) and not store:
        score -= 40
        reasons.append("caracteres de OCR")
    max_length = 120 if store else 60
    max_words = 18 if store else 6
    if len(name) > max_length:
        score -= 30
        reasons.append("nombre largo")
    if len(name.split()) > max_words:
        score -= 20
        reasons.append("muchas palabras")
    tail = name.rsplit(" ", 1)[-1].lower()
    if (
        not store
        and re.search(r"\b[a-zA-Z]{1,2}$", name)
        and not re.search(r"\d\s*$", name)
        and tail not in UNIT_TAILS
    ):
        score -= 30
        reasons.append("termina en fragmento")
    if (
        not store
        and len(re.findall(r"\b[A-ZÁÉÍÓÚÑ]{2,}\b", name)) >= 2
        and len(re.findall(r"\b[a-záéíóúñ]{2,}\b", name)) >= 2
        and len(name) > 25
    ):
        score -= 25
        reasons.append("mayúsculas y minúsculas mezcladas")
    if not store and len(food_types(name)) >= 2 and len(name) > 25:
        score -= 30
        reasons.append("varios platos mezclados")
    if name_key(name) in CATEGORY_WORDS and price_value is None:
        score -= 55
        reasons.append("parece categoría, no plato")
    if CONNECTOR_END.search(name):
        score -= 30
        reasons.append("termina en conector")
    if len(name) < 3:
        score -= 50
        reasons.append("muy corto")
    if price_value is None:
        reasons.append("sin precio")
    if score < 40:
        return "rejected", reasons
    if score < 75:
        return "review", reasons
    return "ok", reasons


def normalize_item(row: dict, source: str, place_gluten_free: bool = False) -> dict:
    name, description = split_name_description(row.get("name"), row.get("description"))
    raw_price = row.get("price_display") or row.get("price")
    price_value, currency, price_error = parse_price(raw_price)
    category = clean_text(row.get("category")) or None
    if category:
        category = re.sub(r"\s+", " ", category).strip()
    if category and name_key(name) in {"simple", "doble", "individual", "grande", "mediano", "mediana"}:
        name = f"{category} {name}"
    row_source = row.get("source")
    if row_source in STORE_SOURCES:
        source = row_source
    kind = "dish"
    if price_value is None and is_category_name(name):
        kind = "category"
        status, reasons = "ok", ["categoría"]
        confidence = "high" if source == "fudo" else "medium"
    else:
        status, reasons = classify(name, price_value, category, source)
        if price_error:
            reasons.append(price_error)
        confidence = "high" if source == "fudo" and status == "ok" else "medium"
        if status == "review":
            confidence = "low"
    return {
        "place_id": row.get("place_id"),
        "place": row.get("place"),
        "address": row.get("address"),
        "name": name,
        "description": description,
        "category": category,
        "kind": kind,
        "dietary_tags": dietary_tags(name, description, category, place_gluten_free),
        "price_value": price_value,
        "currency": currency,
        "price_display": format_price(price_value, currency),
        "price_clp": price_value if currency == "CLP" else None,
        "price_raw": clean_text(raw_price) or None,
        "source": source,
        "confidence": confidence,
        "status": status,
        "reasons": sorted(set(reasons)),
        "raw_name": clean_text(row.get("name")),
    }


def dedupe(items: list[dict]) -> tuple[list[dict], int]:
    result: list[dict] = []
    index: dict[tuple[str, str, str, str], dict] = {}
    duplicates = 0
    for item in items:
        key = (
            item["kind"],
            name_key(item["name"]),
            str(item["currency"]),
            str(item["price_value"] or ""),
        )
        existing = index.get(key)
        if existing is None:
            index[key] = item
            result.append(item)
            continue
        duplicates += 1
        if not existing["category"] and item["category"]:
            existing["category"] = item["category"]
        if len(item["description"] or "") > len(existing["description"] or ""):
            existing["description"] = item["description"]
        if existing["price_value"] is None and item["price_value"] is not None:
            existing["price_value"] = item["price_value"]
            existing["price_display"] = item["price_display"]
        existing["dietary_tags"] = sorted(
            set(existing["dietary_tags"]) | set(item["dietary_tags"])
        )
        existing["reasons"] = sorted(set(existing["reasons"]) | {"duplicado fusionado"})
    return result, duplicates


def markdown_table(rows: list[dict], columns: list[str]) -> str:
    def cell(value) -> str:
        return str(value or "").replace("|", "\\|")

    header = "| " + " | ".join(columns) + " |"
    separator = "|" + "|".join("---" for _ in columns) + "|"
    body = [
        "| " + " | ".join(cell(row.get(column)) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def main() -> int:
    parser = argparse.ArgumentParser(description="Normaliza y audita los platos extraídos.")
    parser.add_argument("--places", required=True)
    parser.add_argument("--menus", required=True)
    parser.add_argument("--menu-urls", default="data/menu_urls.json")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument(
        "--sample-places",
        default="Quinoa,NAOKI,Café Aquelarre,Yoko Sea Food,La Comarca Celiaca",
    )
    args = parser.parse_args()

    places = [
        json.loads(line)
        for line in Path(args.places).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    menus_path = Path(args.menus)
    rows = [
        json.loads(line)
        for line in menus_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for sibling in ("menus_review.jsonl", "menus_rejected.jsonl"):
        if args.no_history:
            break
        path = menus_path.parent / sibling
        if path.exists():
            rows.extend(
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
    menu_urls = {}
    if Path(args.menu_urls).exists():
        menu_urls = json.loads(Path(args.menu_urls).read_text(encoding="utf-8"))

    place_names = {place["id"]: place["metadata"]["name"] for place in places}
    place_category = {
        place["id"]: place["metadata"].get("category") for place in places
    }
    place_gluten_free = {
        place["id"]: place_is_gluten_free(
            place["metadata"]["name"], place["metadata"].get("category")
        )
        for place in places
    }
    by_place: dict[str, list[dict]] = {}
    for row in rows:
        place_id = row.get("place_id")
        place_name = row.get("place") or place_names.get(place_id, "")
        if place_name in menu_urls:
            source = "fudo"
        elif place_name in STORE_PLACES:
            source = "web-product"
        else:
            source = "photo"
        item = normalize_item(
            row,
            source,
            place_gluten_free=place_gluten_free.get(place_id, False),
        )
        if not item["place"]:
            item["place"] = place_name
        by_place.setdefault(item["place_id"], []).append(item)

    normalized: list[dict] = []
    rejected: list[dict] = []
    metrics: list[dict] = []
    place_category_rows: list[dict] = []
    place_dietary_rows: list[dict] = []
    total_duplicates = 0
    for place_id, items in by_place.items():
        before = len(items)
        before_price = sum(1 for item in items if item["price_raw"])
        before_long = sum(1 for item in items if len(item["raw_name"]) > 60)
        before_weird = sum(1 for item in items if re.search(r'[;|"“”\\]', item["raw_name"]))
        clean_items, duplicates = dedupe(items)
        total_duplicates += duplicates
        clean = [item for item in clean_items if item["status"] != "rejected"]
        rejected_items = [item for item in clean_items if item["status"] == "rejected"]
        normalized.extend(clean)
        rejected.extend(rejected_items)
        category_labels = list(
            dict.fromkeys(
                [item["category"] for item in clean if item["kind"] == "dish" and item["category"]]
                + [
                    item["name"]
                    for item in clean
                    if item["kind"] == "category" and item["status"] == "ok"
                ]
            )
        )
        dietary_items = [
            item
            for item in clean
            if item["status"] == "ok" and item["kind"] == "dish"
        ]
        gluten_free_items = sum(
            1 for item in dietary_items if "sin gluten" in item["dietary_tags"]
        )
        vegan_items = sum(
            1 for item in dietary_items if "vegano" in item["dietary_tags"]
        )
        lactose_free_items = sum(
            1 for item in dietary_items if "sin lactosa" in item["dietary_tags"]
        )
        place_category_rows.append(
            {
                "place_id": place_id,
                "place": place_names.get(place_id) or (items[0]["place"] if items else place_id),
                "categories": category_labels,
            }
        )
        place_dietary_rows.append(
            {
                "place_id": place_id,
                "place": place_names.get(place_id) or (items[0]["place"] if items else place_id),
                "gluten_free": place_gluten_free.get(place_id, False),
                "total_dishes": len(dietary_items),
                "gluten_free_items": gluten_free_items,
                "vegan_items": vegan_items,
                "lactose_free_items": lactose_free_items,
            }
        )
        metrics.append(
            {
                "place": place_names.get(place_id) or (items[0]["place"] if items else place_id),
                "before": before,
                "clean": len(clean),
                "dishes": sum(
                    1
                    for item in clean
                    if item["status"] == "ok" and item["kind"] == "dish"
                ),
                "categories": len(category_labels),
                "review": sum(1 for item in clean if item["status"] == "review"),
                "price_ok": sum(
                    1
                    for item in clean
                    if item["status"] == "ok"
                    and item["kind"] == "dish"
                    and item["price_value"] is not None
                ),
                "place_gluten_free": place_gluten_free.get(place_id, False),
                "gluten_free_items": gluten_free_items,
                "vegan_items": vegan_items,
                "lactose_free_items": lactose_free_items,
                "rejected": len(rejected_items),
                "duplicates": duplicates,
                "price_before": before_price,
                "price_after": sum(1 for item in clean if item["price_value"] is not None),
                "long_before": before_long,
                "long_after": sum(1 for item in clean if len(item["name"]) > 60),
                "weird_before": before_weird,
                "weird_after": sum(1 for item in clean if re.search(r'[;|"“”\\]', item["name"])),
            }
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    publishable = [item for item in normalized if item["status"] == "ok"]
    dishes = [item for item in publishable if item["kind"] == "dish"]
    category_items = [item for item in publishable if item["kind"] == "category"]
    review = [item for item in normalized if item["status"] == "review"]
    outputs = (
        ("menu_items.jsonl", dishes),
        ("category_items.jsonl", category_items),
        ("place_categories.jsonl", place_category_rows),
        ("place_dietary.jsonl", place_dietary_rows),
        ("menus_publishable.jsonl", publishable),
        ("menus_review.jsonl", review),
        ("menus_rejected.jsonl", rejected),
        ("menus_normalized.jsonl", normalized),
    )
    for name, values in outputs:
        (out_dir / name).write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in values)
            + ("\n" if values else ""),
            encoding="utf-8",
        )

    metrics.sort(key=lambda item: (item["rejected"] + item["duplicates"], item["before"]), reverse=True)
    sample_names = [name.strip() for name in args.sample_places.split(",") if name.strip()]
    by_name = {metric["place"]: metric for metric in metrics}

    summary = [
        "# Auditoría de normalización P0",
        "",
        f"- Lugares con carta: **{len(metrics)}**",
        f"- Platos antes: **{sum(item['before'] for item in metrics)}**",
        f"- Platos limpios: **{sum(item['clean'] for item in metrics)}**",
        f"- Platos publicables: **{sum(item['dishes'] for item in metrics)}**",
        f"- Etiquetas de categoría: **{sum(item['categories'] for item in metrics)}**",
        f"- En revisión: **{sum(item['review'] for item in metrics)}**",
        f"- Rechazados: **{sum(item['rejected'] for item in metrics)}**",
        f"- Duplicados fusionados: **{total_duplicates}**",
        f"- Con precio antes: **{sum(item['price_before'] for item in metrics)}**",
        f"- Con precio después: **{sum(item['price_after'] for item in metrics)}**",
        f"- Con precio en publicables: **{sum(item['price_ok'] for item in metrics)}**",
        f"- Platos con etiqueta sin gluten: **{sum(item['gluten_free_items'] for item in metrics)}**",
        f"- Platos con etiqueta vegano: **{sum(item['vegan_items'] for item in metrics)}**",
        f"- Platos con etiqueta sin lactosa: **{sum(item['lactose_free_items'] for item in metrics)}**",
        f"- Nombres >60 antes: **{sum(item['long_before'] for item in metrics)}**",
        f"- Nombres >60 después: **{sum(item['long_after'] for item in metrics)}**",
        f"- Nombres con separadores antes: **{sum(item['weird_before'] for item in metrics)}**",
        f"- Nombres con separadores después: **{sum(item['weird_after'] for item in metrics)}**",
        "",
        "## Los 5 locales de muestra",
        "",
        markdown_table(
            [by_name[name] for name in sample_names if name in by_name],
            [
                "place", "before", "dishes", "categories", "review", "rejected", "duplicates",
                "price_before", "price_ok", "long_before", "long_after",
            ],
        ),
        "",
        "## Los 10 locales con más ruido",
        "",
        markdown_table(
            metrics[:10],
            ["place", "before", "clean", "rejected", "duplicates", "price_before", "price_after"],
        ),
        "",
    ]
    (out_dir / "qa_report.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    samples = ["# Antes / después P0", ""]
    for name in sample_names:
        metric = by_name.get(name)
        if not metric:
            continue
        items = [item for item in normalized if item["place"] == name]
        raw_items = [item for item in rows if (item.get("place") or "") == name]
        samples.append(f"## {name}")
        samples.append("")
        samples.append(
            f"Antes: {metric['before']} · Platos: {metric['dishes']} · "
            f"Categorías: {metric['categories']} · Revisión: {metric['review']} · "
            f"Rechazados: {metric['rejected']} · Duplicados: {metric['duplicates']} · "
            f"Con precio: {metric['price_before']} → {metric['price_ok']} (platos)"
        )
        samples.append("")
        category_names = [
            item["name"]
            for item in items
            if item["kind"] == "category" and item["status"] == "ok"
        ]
        category_values = list(
            dict.fromkeys(
                item["category"]
                for item in items
                if item["kind"] == "dish" and item["category"]
            )
        )
        all_categories = list(dict.fromkeys(category_names + category_values))
        samples.append(
            "**Qué vende:** "
            + (", ".join(all_categories) if all_categories else "sin categorías detectadas")
        )
        samples.append("")
        diet_parts = []
        if metric["place_gluten_free"]:
            diet_parts.append("local 100% sin gluten")
        if metric["gluten_free_items"]:
            diet_parts.append(f"{metric['gluten_free_items']} platos sin gluten")
        if metric["vegan_items"]:
            diet_parts.append(f"{metric['vegan_items']} veganos")
        if metric["lactose_free_items"]:
            diet_parts.append(f"{metric['lactose_free_items']} sin lactosa")
        samples.append(
            "**Dietético:** " + (", ".join(diet_parts) if diet_parts else "sin etiquetas")
        )
        samples.append("")
        samples.append("**Antes (muestra):**")
        samples.append("")
        before_rows = [
            {"name": clean_text(item.get("name"))[:110], "price": item.get("price")}
            for item in raw_items[:5]
        ]
        samples.append(markdown_table(before_rows, ["name", "price"]))
        samples.append("")
        samples.append("**Carta (platos publicables):**")
        samples.append("")
        ok_items = [
            item
            for item in items
            if item["status"] == "ok" and item["kind"] == "dish"
        ]
        after_rows = [
            {
                "name": item["name"][:90],
                "price": item["price_display"],
                "category": item["category"],
                "tags": ", ".join(item["dietary_tags"]),
                "status": item["status"],
            }
            for item in ok_items[:7]
        ]
        samples.append(
            markdown_table(after_rows, ["name", "price", "category", "tags", "status"])
        )
        samples.append("")
        if not ok_items:
            samples.append("No hay platos específicos publicables; quedan las categorías de arriba.")
            samples.append("")
            review_items = [item for item in items if item["status"] == "review"]
            if review_items:
                review_rows = [
                    {
                        "name": item["name"][:90],
                        "reasons": ", ".join(item["reasons"])[:100],
                    }
                    for item in review_items[:6]
                ]
                samples.append("**En revisión (no se publican):**")
                samples.append("")
                samples.append(markdown_table(review_rows, ["name", "reasons"]))
                samples.append("")
        rejected_items = [item for item in rejected if item["place"] == name]
        if rejected_items:
            samples.append("**Rechazados (muestra):**")
            samples.append("")
            rejected_rows = [
                {
                    "name": item["name"][:80],
                    "reasons": ", ".join(item["reasons"])[:100],
                }
                for item in rejected_items[:5]
            ]
            samples.append(markdown_table(rejected_rows, ["name", "reasons"]))
            samples.append("")

    (out_dir / "sample_before_after.md").write_text("\n".join(samples) + "\n", encoding="utf-8")
    print(f"Salida: {out_dir}")
    print(f"Limpios: {len(normalized)} · Rechazados: {len(rejected)} · Duplicados: {total_duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

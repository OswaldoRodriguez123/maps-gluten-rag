from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from maps_gluten.platforms import PlaceContext, extract  # noqa: E402
from maps_gluten.platforms.maps_links import discover_links  # noqa: E402
from maps_gluten import store  # noqa: E402
from maps_gluten.website_search import search_website  # noqa: E402

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
BASENAME = "mis_lugares_sin_gluten"


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )


def load_places(data_dir: Path) -> list[dict]:
    return load_jsonl(data_dir / f"{BASENAME}.jsonl")


def select_targets(
    records: list[dict],
    baseline: dict | list | None,
    since: str | None,
    names: list[str] | None,
    refresh: bool,
) -> list[dict]:
    baseline_ids = set(baseline or [])
    since_date = date.fromisoformat(since) if since else None
    wanted = [normalize(name) for name in (names or []) if name.strip()]
    selected: list[dict] = []
    for record in records:
        metadata = record.get("metadata") or {}
        ftid = record.get("id")
        if not ftid:
            continue
        name = metadata.get("name") or ""
        if wanted:
            if not any(term in normalize(name) for term in wanted):
                continue
        else:
            first_observed = metadata.get("first_observed_at") or ""
            is_new = ftid not in baseline_ids if baseline_ids else False
            is_recent = bool(
                since_date and first_observed and first_observed >= since
            )
            if not (is_new or is_recent):
                continue
        if (metadata.get("menu_count") or 0) > 0 and not refresh:
            continue
        selected.append(record)
    return selected


def _target_ids(targets: list[dict]) -> set[str]:
    return {record.get("id") for record in targets if record.get("id")}


def _matches(row: dict, ids: set[str]) -> bool:
    # Solo por ftid: dos locales pueden compartir nombre y no deben pisarse.
    return row.get("place_id") in ids


def _row_files(data_dir: Path) -> dict[str, Path]:
    return {
        "menus": data_dir / f"{BASENAME}_menus.jsonl",
        "review": data_dir / "menus_review.jsonl",
        "rejected": data_dir / "menus_rejected.jsonl",
    }


def apply_extraction(
    data_dir: Path,
    targets: list[dict],
    items: list[dict],
    backup_path: Path,
    dry_run: bool = False,
) -> dict:
    ids = _target_ids(targets)
    files = _row_files(data_dir)
    backup: list[dict] = []
    for kind, path in files.items():
        for row in load_jsonl(path):
            if _matches(row, ids):
                backup.append({**row, "file": kind})
    if dry_run:
        return {"old": len(backup), "new": len(items), "backup": len(backup)}
    if backup:
        existing_backup = [
            row
            for row in load_jsonl(backup_path)
            if row.get("place_id") not in ids
        ]
        write_jsonl(backup_path, existing_backup + backup)
    for kind, path in files.items():
        rows = [row for row in load_jsonl(path) if not _matches(row, ids)]
        if kind == "menus":
            rows.extend(items)
        write_jsonl(path, rows)
    return {"old": len(backup), "new": len(items), "backup": len(backup)}


def _restore(data_dir: Path, ftid: str, backup_rows: list[dict]) -> int:
    files = _row_files(data_dir)
    restored = 0
    for kind, path in files.items():
        selected = [
            row
            for row in backup_rows
            if row.get("place_id") == ftid and row.get("file") == kind
        ]
        if not selected:
            continue
        rows = load_jsonl(path)
        existing = {
            (row.get("place_id"), row.get("name"), row.get("price"))
            for row in rows
        }
        for row in selected:
            clean = {key: value for key, value in row.items() if key != "file"}
            key = (clean.get("place_id"), clean.get("name"), clean.get("price"))
            if key not in existing:
                rows.append(clean)
                restored += 1
        write_jsonl(path, rows)
    return restored


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _apply_search_fallback(
    *,
    name: str,
    address: str | None,
    metadata: dict,
    links: dict,
    api_key: str | None,
    enabled: bool,
    search_fn=None,
) -> str | None:
    if not enabled or not api_key:
        return None
    if links.get("website") or metadata.get("website"):
        return None
    fn = search_fn if search_fn is not None else search_website
    try:
        url, score, _error = fn(name, address, api_key=api_key)
    except Exception:  # noqa: BLE001
        return None
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        return None
    if not url or score_f < 0.85:
        return None
    links["website"] = url
    links["website_source"] = "search"
    metadata["website"] = url
    metadata["website_source"] = "search"
    return "search"


def finalize_report(
    data_dir: Path,
    report_path: Path,
    backup_path: Path,
    db_path: str | Path | None = None,
) -> dict:
    places = {record.get("id"): record for record in load_places(data_dir)}
    report = load_jsonl(report_path)
    backup = load_jsonl(backup_path)
    counts = {"ok": 0, "needs_manual": 0, "restored": 0}
    changed_places = False
    connection = None
    if db_path and Path(db_path).exists():
        connection = store.connect(Path(db_path))
    try:
        for row in report:
            ftid = row.get("ftid")
            metadata = (places.get(ftid) or {}).get("metadata") or {}
            current = int(metadata.get("menu_count") or 0)
            old = int(row.get("old_count") or 0)
            row["publishable_count"] = current
            if old > 0 and current == 0:
                restored = _restore(data_dir, ftid, backup)
                row["restored_count"] = restored
                counts["restored"] += 1
                row["status"] = "needs_manual"
                row["error"] = (row.get("error") or "") + " | carta previa restaurada"
                restored_rows = [
                    item
                    for item in backup
                    if item.get("place_id") == ftid and item.get("file") == "menus"
                ]
                if restored_rows and places.get(ftid):
                    clean_rows = [
                        {key: value for key, value in item.items() if key != "file"}
                        for item in restored_rows
                    ]
                    metadata["menu"] = [
                        {
                            "name": item.get("name"),
                            "price": item.get("price_display") or item.get("price"),
                            "category": item.get("category"),
                            "tags": item.get("dietary_tags") or [],
                            "kind": item.get("kind") or "dish",
                        }
                        for item in clean_rows
                        if item.get("name")
                    ]
                    metadata["menu_count"] = len(metadata["menu"])
                    changed_places = True
                    if connection is not None:
                        summary = "; ".join(
                            f"{item.get('name')} ({item.get('price_display') or item.get('price')})"
                            if (item.get("price_display") or item.get("price"))
                            else str(item.get("name"))
                            for item in clean_rows
                            if item.get("name")
                        )
                        connection.execute(
                            "UPDATE places SET menu_json = ?, menu_dishes = ?, menu_at = ? "
                            "WHERE ftid = ?",
                            (
                                json.dumps(clean_rows, ensure_ascii=False),
                                summary or None,
                                date.today().isoformat(),
                                ftid,
                            ),
                        )
                        connection.commit()
            elif current == 0:
                row["status"] = "needs_manual"
            elif row.get("extraction_status") != "ok" or int(row.get("extracted_count") or 0) == 0:
                row["status"] = "needs_manual"
            elif old > 0 and current < old * 0.5 and current < 5:
                row["status"] = "needs_manual"
                row["error"] = (row.get("error") or "") + " | caída fuerte de ítems"
            else:
                row["status"] = "ok"
            counts[row["status"]] = counts.get(row["status"], 0) + 1
    finally:
        if connection is not None:
            connection.close()
    write_jsonl(report_path, report)
    if changed_places:
        write_jsonl(data_dir / f"{BASENAME}.jsonl", list(places.values()))
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrae solo los locales nuevos y detecta su plataforma."
    )
    parser.add_argument("--places", help="Nombres separados por coma (opcional).")
    parser.add_argument("--since", help="Fecha ISO; por defecto hace 7 días.")
    parser.add_argument("--baseline", help="JSON con ftid existentes antes de refrescar.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--db", help="SQLite opcional (no se usa para seleccionar).")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--photos", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-items", type=int, default=500)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--dump-baseline", help="Escribe los ftid actuales y termina.")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    report_dir = Path(args.report_dir)
    today = date.today().isoformat()
    report_path = report_dir / f"new_places_{today}.jsonl"
    backup_path = report_dir / f"new_places_backup_{today}.jsonl"

    if args.dump_baseline:
        records = load_places(data_dir)
        baseline = {
            record["id"]: (record.get("metadata") or {}).get("name")
            for record in records
            if record.get("id")
        }
        Path(args.dump_baseline).write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Baseline: {len(baseline)} lugares en {args.dump_baseline}")
        return 0

    if args.finalize:
        counts = finalize_report(
            data_dir, report_path, backup_path, db_path=args.db
        )
        print(
            f"Finalize: ok={counts.get('ok', 0)} "
            f"needs_manual={counts.get('needs_manual', 0)} "
            f"restored={counts.get('restored', 0)}"
        )
        return 0

    records = load_places(data_dir)
    baseline = None
    if args.baseline and Path(args.baseline).exists():
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    names = [part.strip() for part in (args.places or "").split(",") if part.strip()]
    since = args.since or (date.today() - timedelta(days=7)).isoformat()
    targets = select_targets(records, baseline, since, names or None, args.refresh)
    if not targets:
        print("No hay locales nuevos para procesar.")
        return 0

    links_path = data_dir / "place_links.json"
    menu_urls_path = data_dir / "menu_urls.json"
    try:
        stored_links = json.loads(links_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        stored_links = {}
    try:
        menu_urls = json.loads(menu_urls_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        menu_urls = {}

    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    report_rows: list[dict] = []
    all_items: list[dict] = []
    written_targets: list[dict] = []
    website_search_enabled = _env_bool("MAPS_WEBSITE_SEARCH", True)
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip() or None
    searched = False
    places_changed = False

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for record in targets:
                metadata = record.get("metadata") or {}
                record["metadata"] = metadata
                ftid = record.get("id")
                name = metadata.get("name") or ""
                links = stored_links.get(ftid) or {}
                if not links.get("menu") and not links.get("website") and not links.get("order"):
                    try:
                        links = discover_links(record, browser)
                    except Exception as error:  # noqa: BLE001
                        links = {
                            "website": metadata.get("website"),
                            "menu": None,
                            "order": [],
                            "error": f"{type(error).__name__}: {error}"[:180],
                        }
                    links["name"] = name
                    if not args.dry_run:
                        stored_links[ftid] = links
                if not links.get("website") and not metadata.get("website"):
                    if website_search_enabled and gemini_api_key:
                        if searched:
                            time.sleep(0.5)
                        searched = True
                        if _apply_search_fallback(
                            name=name,
                            address=metadata.get("address"),
                            metadata=metadata,
                            links=links,
                            api_key=gemini_api_key,
                            enabled=website_search_enabled,
                        ) == "search":
                            links["name"] = name
                            places_changed = True
                            if not args.dry_run:
                                stored_links[ftid] = links
                menu_url = links.get("menu") or menu_urls.get(name) or menu_urls.get(ftid)
                website = links.get("website") or metadata.get("website")
                ctx = PlaceContext(
                    record=record,
                    place_id=ftid,
                    name=name,
                    website=website,
                    menu_url=menu_url,
                    order_urls=links.get("order") or [],
                    session=session,
                    browser=browser,
                    allow_photos=args.photos,
                    dry_run=args.dry_run,
                    max_items=args.max_items,
                )
                result = extract(ctx)
                old_rows = [
                    row
                    for row in load_jsonl(data_dir / f"{BASENAME}_menus.jsonl")
                    if row.get("place_id") == ftid
                ]
                new_rows = [
                    {
                        "place_id": ftid,
                        "place": name,
                        "address": metadata.get("address"),
                        "name": item.name,
                        "price": item.price,
                        "category": item.category,
                        "description": item.description,
                        "source": item.source or result.source,
                        "url": item.url or menu_url or website,
                    }
                    for item in result.items
                    if item.name
                ]
                all_items.extend(new_rows)
                if new_rows:
                    written_targets.append(record)
                report_rows.append(
                    {
                        "place": name,
                        "ftid": ftid,
                        "platform": result.source,
                        "extraction_status": result.status,
                        "extracted_count": len(new_rows),
                        "old_count": len(old_rows),
                        "urls": {
                            "website": website,
                            "menu": menu_url,
                            "order": links.get("order") or [],
                        },
                        "error": result.error or links.get("error"),
                        "status": "ok" if new_rows else "needs_manual",
                    }
                )
                print(
                    f"{name}: {result.source} · {len(new_rows)} ítems · {result.status}",
                    flush=True,
                )
        finally:
            browser.close()

    if args.dry_run:
        for row in report_rows:
            print(json.dumps(row, ensure_ascii=False))
        return 0

    if stored_links:
        links_path.write_text(
            json.dumps(stored_links, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if places_changed:
        write_jsonl(data_dir / f"{BASENAME}.jsonl", records)
    apply_extraction(data_dir, written_targets, all_items, backup_path, dry_run=False)
    existing_report = {
        row.get("ftid"): row for row in load_jsonl(report_path) if row.get("ftid")
    }
    for row in report_rows:
        ftid = row.get("ftid")
        existing_report[ftid] = {**existing_report.get(ftid, {}), **row}
    write_jsonl(report_path, list(existing_report.values()))
    print(f"Reporte: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

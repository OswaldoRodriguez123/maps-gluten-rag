import json
import tempfile
import unittest
from pathlib import Path

from maps_gluten import store
from maps_gluten.extract import Place
from scripts.update_new_places import (
    apply_extraction,
    finalize_report,
    select_targets,
)


def record(ftid, name, first_observed="2026-11-01", menu_count=0):
    return {
        "id": ftid,
        "metadata": {
            "name": name,
            "address": "Dirección",
            "first_observed_at": first_observed,
            "first_seen": first_observed,
            "menu_count": menu_count,
        },
    }


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class SelectTargetsTest(unittest.TestCase):
    def test_selects_new_and_recent_but_not_existing_or_with_menu(self):
        records = [
            record("a", "Viejo", "2025-01-01"),
            record("b", "Nuevo", "2026-11-06"),
            record("c", "Reciente", "2026-11-05"),
            record("d", "Con carta", "2026-11-06", menu_count=4),
        ]
        selected = select_targets(
            records,
            baseline={"a": "Viejo", "c": "Reciente", "d": "Con carta"},
            since="2026-11-01",
            names=None,
            refresh=False,
        )
        self.assertEqual([row["id"] for row in selected], ["b", "c"])


class ApplyExtractionTest(unittest.TestCase):
    def test_dry_run_does_not_write_and_real_run_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            write_jsonl(
                data_dir / "mis_lugares_sin_gluten_menus.jsonl",
                [{"place_id": "a", "place": "A", "name": "Viejo", "price": "$1"}],
            )
            write_jsonl(data_dir / "menus_review.jsonl", [])
            write_jsonl(data_dir / "menus_rejected.jsonl", [])
            targets = [record("a", "A", menu_count=1)]
            items = [
                {
                    "place_id": "a",
                    "place": "A",
                    "address": "Dirección",
                    "name": "Nuevo",
                    "price": "$2",
                    "category": "Carta",
                    "description": None,
                    "source": "apparta",
                }
            ]
            backup = Path(tmp) / "backup.jsonl"
            apply_extraction(data_dir, targets, items, backup, dry_run=True)
            self.assertEqual(read_jsonl(data_dir / "mis_lugares_sin_gluten_menus.jsonl")[0]["name"], "Viejo")
            apply_extraction(data_dir, targets, items, backup, dry_run=False)
            rows = read_jsonl(data_dir / "mis_lugares_sin_gluten_menus.jsonl")
            self.assertEqual([row["name"] for row in rows], ["Nuevo"])
            self.assertTrue(backup.exists())

    def test_same_name_other_place_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            write_jsonl(
                data_dir / "mis_lugares_sin_gluten_menus.jsonl",
                [
                    {"place_id": "a", "place": "Mismo", "name": "A", "price": "$1"},
                    {"place_id": "b", "place": "Mismo", "name": "B", "price": "$2"},
                ],
            )
            write_jsonl(data_dir / "menus_review.jsonl", [])
            write_jsonl(data_dir / "menus_rejected.jsonl", [])
            apply_extraction(
                data_dir,
                [record("a", "Mismo", menu_count=1)],
                [],
                Path(tmp) / "backup.jsonl",
                dry_run=False,
            )
            rows = read_jsonl(data_dir / "mis_lugares_sin_gluten_menus.jsonl")
            self.assertEqual([row["place_id"] for row in rows], ["b"])


class FinalizeTest(unittest.TestCase):
    def test_restores_backup_when_nothing_is_publishable(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            write_jsonl(data_dir / "mis_lugares_sin_gluten.jsonl", [record("a", "A", menu_count=0)])
            backup = Path(tmp) / "backup.jsonl"
            write_jsonl(
                backup,
                [{"file": "menus", "place_id": "a", "place": "A", "name": "Viejo", "price": "$1"}],
            )
            report = Path(tmp) / "report.jsonl"
            write_jsonl(
                report,
                [{"place": "A", "ftid": "a", "old_count": 1, "extracted_count": 1, "status": "ok"}],
            )
            write_jsonl(data_dir / "mis_lugares_sin_gluten_menus.jsonl", [])
            write_jsonl(data_dir / "menus_review.jsonl", [])
            write_jsonl(data_dir / "menus_rejected.jsonl", [])
            finalize_report(data_dir, report, backup)
            restored = read_jsonl(data_dir / "mis_lugares_sin_gluten_menus.jsonl")
            final = read_jsonl(report)
            self.assertEqual(restored[0]["name"], "Viejo")
            self.assertEqual(final[0]["status"], "needs_manual")

    def test_restore_is_persisted_in_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            db_path = Path(tmp) / "historial.db"
            conn = store.connect(db_path)
            store.save(
                conn,
                "list",
                "L",
                [
                    Place(
                        ftid="a",
                        name="A",
                        address=None,
                        category=None,
                        rating=None,
                        reviews=None,
                        note=None,
                        url="https://maps",
                    )
                ],
                "2026-11-06",
            )
            conn.close()
            write_jsonl(data_dir / "mis_lugares_sin_gluten.jsonl", [record("a", "A", menu_count=0)])
            backup = Path(tmp) / "backup.jsonl"
            write_jsonl(
                backup,
                [{"file": "menus", "place_id": "a", "place": "A", "name": "Viejo", "price": "$1"}],
            )
            report = Path(tmp) / "report.jsonl"
            write_jsonl(
                report,
                [{"place": "A", "ftid": "a", "old_count": 1, "extracted_count": 1, "status": "ok"}],
            )
            write_jsonl(data_dir / "mis_lugares_sin_gluten_menus.jsonl", [])
            write_jsonl(data_dir / "menus_review.jsonl", [])
            write_jsonl(data_dir / "menus_rejected.jsonl", [])
            finalize_report(data_dir, report, backup, db_path=db_path)
            conn = store.connect(db_path)
            menu_json = conn.execute(
                "SELECT menu_json FROM places WHERE ftid='a'"
            ).fetchone()[0]
            conn.close()
            self.assertIn("Viejo", menu_json or "")


def test_update_new_places_uses_search_when_maps_empty(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    import scripts.update_new_places as unp

    data_dir = tmp_path / "data"
    report_dir = tmp_path / "reports"
    data_dir.mkdir(parents=True)
    rec = {
        "id": "nv1",
        "metadata": {
            "name": "Café Nuevo",
            "address": "Manuel Montt 123, Providencia",
            "first_observed_at": "2026-11-06",
            "menu_count": 0,
        },
    }
    (data_dir / "mis_lugares_sin_gluten.jsonl").write_text(
        json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (data_dir / "place_links.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setenv("MAPS_WEBSITE_SEARCH", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        unp, "discover_links", lambda record, browser: {"website": None, "menu": None, "order": []}
    )
    monkeypatch.setattr(
        unp,
        "search_website",
        lambda name, address, api_key=None, timeout=12: ("https://nuevo.cl/", 0.95, None),
        raising=False,
    )
    fake_item = SimpleNamespace(
        name="Pan sin gluten",
        price="$1",
        category="Carta",
        description=None,
        source="fake",
        url=None,
    )
    monkeypatch.setattr(
        unp,
        "extract",
        lambda ctx: SimpleNamespace(items=[fake_item], source="fake", status="ok", error=None),
    )

    fake_browser = SimpleNamespace(close=lambda: None)
    fake_chromium = SimpleNamespace(launch=lambda headless=True: fake_browser)
    fake_pw = SimpleNamespace(chromium=fake_chromium)

    class _Ctx:
        def __enter__(self):
            return fake_pw

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(unp, "sync_playwright", lambda: _Ctx())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "update_new_places.py",
            "--places",
            "Café Nuevo",
            "--data-dir",
            str(data_dir),
            "--report-dir",
            str(report_dir),
        ],
    )

    assert unp.main() == 0
    stored_links = json.loads((data_dir / "place_links.json").read_text(encoding="utf-8"))
    assert stored_links["nv1"]["website"] == "https://nuevo.cl/"
    places_after = read_jsonl(data_dir / "mis_lugares_sin_gluten.jsonl")
    meta = (places_after[0]["metadata"])
    assert meta["website"] == "https://nuevo.cl/"
    assert meta["website_source"] == "search"


if __name__ == "__main__":
    unittest.main()

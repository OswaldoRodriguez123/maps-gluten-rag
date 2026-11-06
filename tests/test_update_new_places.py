import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

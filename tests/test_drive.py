import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from maps_gluten import drive


class FakeFiles:
    def __init__(self, existing):
        self.existing = existing
        self.list_calls = []
        self.create_calls = []
        self.update_calls = []

    def list(self, q, fields, spaces):
        self.list_calls.append({"q": q, "fields": fields, "spaces": spaces})

        class _Req:
            def execute(self_inner):
                return {"files": self.existing}

        return _Req()

    def create(self, body, media_body, fields):
        self.create_calls.append({"body": body, "fields": fields})

        class _Req:
            def execute(self_inner):
                return {"id": "created-id"}

        return _Req()

    def update(self, fileId, media_body):
        self.update_calls.append({"fileId": fileId})

        class _Req:
            def execute(self_inner):
                return {"id": fileId}

        return _Req()


class FakeService:
    def __init__(self, existing):
        self._files = FakeFiles(existing)

    def files(self):
        return self._files


def make_markdown(tmp):
    path = Path(tmp) / "mis_lugares_sin_gluten.txt"
    path.write_text("# Base de Datos\n", encoding="utf-8")
    return path


class SyncMarkdownTest(unittest.TestCase):
    def test_skips_when_no_folder_id_anywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_markdown(tmp)
            buffer = io.StringIO()
            with mock.patch.object(drive, "_service", side_effect=AssertionError("no debería llamarse")):
                with mock.patch.dict("os.environ", {}, clear=True):
                    with redirect_stdout(buffer):
                        result = drive.sync_markdown(path, folder_id="")
            self.assertIsNone(result)
            self.assertIn("DRIVE_FOLDER_ID", buffer.getvalue())

    def test_reads_folder_id_from_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_markdown(tmp)
            service = FakeService(existing=[])
            with mock.patch.object(drive, "_service", return_value=service):
                with mock.patch.dict("os.environ", {"DRIVE_FOLDER_ID": "folder-123"}, clear=True):
                    result = drive.sync_markdown(path)
            self.assertEqual(result, "created-id")
            self.assertEqual(service._files.create_calls[0]["body"]["parents"], ["folder-123"])

    def test_creates_file_when_missing_in_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_markdown(tmp)
            service = FakeService(existing=[])
            with mock.patch.object(drive, "_service", return_value=service):
                result = drive.sync_markdown(path, folder_id="folder-123")
            self.assertEqual(result, "created-id")
            created = service._files.create_calls[0]
            self.assertEqual(created["body"]["name"], "mis_lugares_sin_gluten.txt")
            self.assertEqual(created["body"]["parents"], ["folder-123"])
            self.assertEqual(service._files.update_calls, [])

    def test_pinned_file_id_updates_that_file_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_markdown(tmp)
            service = FakeService(existing=[])
            with mock.patch.object(drive, "_service", return_value=service):
                result = drive.sync_markdown(path, file_id="pinned-id-123")
            self.assertEqual(result, "pinned-id-123")
            self.assertEqual(service._files.update_calls[0]["fileId"], "pinned-id-123")
            self.assertEqual(service._files.list_calls, [])
            self.assertEqual(service._files.create_calls, [])

    def test_file_id_from_env_takes_precedence_over_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_markdown(tmp)
            service = FakeService(existing=[])
            with mock.patch.object(drive, "_service", return_value=service):
                with mock.patch.dict("os.environ", {"DRIVE_FILE_ID": "env-pin", "DRIVE_FOLDER_ID": "folder-123"}, clear=True):
                    result = drive.sync_markdown(path)
            self.assertEqual(result, "env-pin")
            self.assertEqual(service._files.update_calls[0]["fileId"], "env-pin")
            self.assertEqual(service._files.list_calls, [])

    def test_updates_existing_file_in_folder_instead_of_duplicating(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_markdown(tmp)
            service = FakeService(existing=[{"id": "abc123", "name": "mis_lugares_sin_gluten.txt"}])
            with mock.patch.object(drive, "_service", return_value=service):
                result = drive.sync_markdown(path, folder_id="folder-123")
            self.assertEqual(result, "abc123")
            self.assertEqual(service._files.update_calls[0]["fileId"], "abc123")
            self.assertEqual(service._files.create_calls, [])
            query = service._files.list_calls[0]["q"]
            self.assertIn("mis_lugares_sin_gluten.txt", query)
            self.assertIn("folder-123", query)
            self.assertIn("application/vnd.google-apps", query)


if __name__ == "__main__":
    unittest.main()

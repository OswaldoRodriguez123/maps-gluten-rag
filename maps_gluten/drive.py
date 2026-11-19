from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
MARKDOWN_MIME = "text/markdown"
TEXT_MIME = "text/plain"


def _credentials():
    raw = os.getenv("GOOGLE_SA_JSON", "").strip()
    if raw and not raw.startswith("{"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:
            pass
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not path:
        raise RuntimeError("Falta GOOGLE_SA_JSON o GOOGLE_APPLICATION_CREDENTIALS.")
    return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)


def _service():
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_in_folder(service, name: str, folder_id: str) -> list[dict]:
    query = (
        f"trashed = false and name = '{_escape_query(name)}' "
        f"and '{_escape_query(folder_id)}' in parents "
        f"and not mimeType contains 'application/vnd.google-apps'"
    )
    result = (
        service.files()
        .list(q=query, fields="files(id, name)", spaces="drive")
        .execute()
    )
    return result.get("files", [])


def sync_markdown(
    path: Path | str,
    folder_id: str | None = None,
    name: str | None = None,
    file_id: str | None = None,
) -> str | None:
    """Sube (o actualiza) el Markdown en Drive.

    Si DRIVE_FILE_ID (o el argumento file_id) está definido, actualiza ese
    archivo exacto, sin importar nombre ni carpeta; el MIME queda text/plain,
    que es el tipo que NotebookLM acepta desde Drive. Si no, usa la carpeta
    DRIVE_FOLDER_ID y busca (o crea) un archivo por nombre.

    Devuelve el ID del archivo, o None si no hay DRIVE_FILE_ID ni
    DRIVE_FOLDER_ID configurados. Lanza excepción si la subida falla.
    """
    file_id = (file_id if file_id is not None else os.getenv("DRIVE_FILE_ID", "")).strip()
    folder_id = (folder_id if folder_id is not None else os.getenv("DRIVE_FOLDER_ID", "")).strip()
    path = Path(path)
    if file_id:
        media = MediaFileUpload(str(path), mimetype=TEXT_MIME, resumable=False)
        _service().files().update(fileId=file_id, media_body=media).execute()
        return file_id
    if not folder_id:
        print("DRIVE_FILE_ID ni DRIVE_FOLDER_ID definidos; se omite el sync del .md a Drive.")
        return None
    name = name or path.name
    media = MediaFileUpload(str(path), mimetype=MARKDOWN_MIME, resumable=False)

    service = _service()
    existing = _find_in_folder(service, name, folder_id)
    if existing:
        if len(existing) > 1:
            print(f"Aviso: {len(existing)} archivos llamados {name} en la carpeta; se actualiza el primero.")
        file_id = existing[0]["id"]
        service.files().update(fileId=file_id, media_body=media).execute()
        return file_id
    created = (
        service.files()
        .create(
            body={"name": name, "parents": [folder_id]},
            media_body=media,
            fields="id",
        )
        .execute()
    )
    return created["id"]

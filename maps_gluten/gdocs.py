from __future__ import annotations

import base64
import json
import os
import re

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .text import normalize_markdown

SCOPES = ["https://www.googleapis.com/auth/documents"]
BATCH_SIZE = 200


def _u16len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            blocks.append({"type": "h1", "text": line[2:].strip()})
        elif line.startswith("## "):
            blocks.append({"type": "h2", "text": line[3:].strip()})
        elif line.startswith("### "):
            blocks.append({"type": "h3", "text": line[4:].strip()})
        elif line.startswith("#### "):
            blocks.append({"type": "h4", "text": line[5:].strip()})
        elif line.startswith("- "):
            match = re.match(r"- \*\*(.+?):\*\*\s*(.*)", line)
            if match:
                label = f"{match.group(1)}:"
                blocks.append(
                    {
                        "type": "bullet",
                        "text": f"{label} {match.group(2)}".strip(),
                        "label": label,
                    }
                )
            else:
                blocks.append({"type": "bullet", "text": line[2:].strip()})
        elif not line.strip():
            blocks.append({"type": "blank", "text": ""})
        else:
            text = line.replace("**", "").strip()
            if text.startswith("_") and text.endswith("_"):
                text = text.strip("_")
            blocks.append({"type": "body", "text": text})
    return blocks


def _document_text(blocks: list[dict]) -> tuple[str, list[dict]]:
    positioned: list[dict] = []
    offset = 0
    for block in blocks:
        positioned.append({**block, "start": offset, "length": _u16len(block["text"])})
        offset += _u16len(block["text"]) + 1
    text = "\n".join(block["text"] for block in blocks) + "\n"
    return text, positioned


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
    return build("docs", "v1", credentials=_credentials(), cache_discovery=False)


def _style_requests(positioned: list[dict]) -> list[dict]:
    requests: list[dict] = []
    for block in positioned:
        start = 1 + block["start"]
        end = start + block["length"] + 1
        kind = block["type"]
        if kind in {"h1", "h2", "h3", "h4"}:
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "paragraphStyle": {
                            "namedStyleType": {
                                "h1": "HEADING_1",
                                "h2": "HEADING_2",
                                "h3": "HEADING_3",
                                "h4": "HEADING_4",
                            }[kind]
                        },
                        "fields": "namedStyleType",
                    }
                }
            )
        elif kind == "bullet":
            requests.append(
                {
                    "createParagraphBullets": {
                        "range": {"startIndex": start, "endIndex": end},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                }
            )
            label = block.get("label")
            if label:
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": {
                                "startIndex": start,
                                "endIndex": start + _u16len(label),
                            },
                            "textStyle": {"bold": True},
                            "fields": "bold",
                        }
                    }
                )
    return requests


def update_document(doc_id: str, markdown: str) -> int:
    service = _service()
    document = service.documents().get(documentId=doc_id).execute()
    body = document.get("body", {}).get("content", [])
    end = body[-1].get("endIndex", 2) - 1 if body else 1

    markdown = normalize_markdown(markdown)
    blocks = _blocks(markdown)
    text, positioned = _document_text(blocks)

    requests: list[dict] = []
    if end > 1:
        requests.append(
            {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end}}}
        )
    requests.append({"insertText": {"location": {"index": 1}, "text": text}})
    service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()

    style = _style_requests(positioned)
    for index in range(0, len(style), BATCH_SIZE):
        service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": style[index : index + BATCH_SIZE]},
        ).execute()
    return len(blocks)


def document_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"

"""Website search fallback: DuckDuckGo HTML + validación LLM.

Módulo standalone, solo stdlib + GEMINI_API_KEY. No acepta ninguna URL
sin validación LLM con nombre + overlap de dirección y score >= 0.85.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

DEFAULT_SEARCH_MODEL = "gemini-flash-lite-latest"
ACCEPT_THRESHOLD = 0.85
DDG_URL = "https://html.duckduckgo.com/html/"
LLM_TIMEOUT = 30

# Igual que photos.py para los GET a DuckDuckGo.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

BAD_HOST_RE = re.compile(
    r"instagram\.com|facebook\.com|tiktok\.com|tripadvisor|uber-?eats|rappi|pedidosya",
    re.IGNORECASE,
)


def _normalize(value: str | None) -> str:
    """Saca acentos, quita puntuación y colapsa espacios (preserva mayúsculas)."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^A-Za-z0-9 ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def build_search_query(name: str, address: str | None) -> str:
    clean_name = (name or "").strip()
    base = f'"{clean_name}" sin gluten' if clean_name else "sin gluten"
    if not address or not address.strip():
        return base
    addr = address.strip()
    comuna_raw = ""
    street_raw = addr
    if "," in addr:
        before, after = addr.rsplit(",", 1)
        comuna_raw = after.strip()
        street_raw = before.strip()
    comuna = _normalize(comuna_raw) if comuna_raw else ""
    street = _normalize(street_raw)
    parts = [base]
    if comuna:
        parts.append(comuna)
    if street:
        parts.append(street)
    return " ".join(parts)


def _decode_uddg(href: str | None) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query or "")
        if qs.get("uddg"):
            return urllib.parse.unquote(qs["uddg"][0])
        return href
    # Relativo tipo /l/?uddg=...
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query or "")
    if qs.get("uddg"):
        return urllib.parse.unquote(qs["uddg"][0])
    return ""


class _DDGParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[dict] = []
        self._capturing_title = False
        self._capturing_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._current_href = ""
        self._pending_url = ""
        self._pending_title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr = dict(attrs)
        cls = (attr.get("class") or "").lower()
        if "result__a" in cls:
            self._capturing_title = True
            self._title_parts = []
            self._current_href = attr.get("href") or ""
        elif "result__snippet" in cls:
            self._capturing_snippet = True
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._capturing_title:
            self._title_parts.append(data)
        elif self._capturing_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a":
            return
        if self._capturing_title:
            self._capturing_title = False
            title = " ".join("".join(self._title_parts).split())
            url = _decode_uddg(self._current_href)
            self._current_href = ""
            if url and title:
                self._pending_url = url
                self._pending_title = title
        elif self._capturing_snippet:
            self._capturing_snippet = False
            snippet = " ".join("".join(self._snippet_parts).split())
            if self._pending_url:
                self.candidates.append(
                    {
                        "url": self._pending_url,
                        "title": self._pending_title,
                        "snippet": snippet,
                    }
                )
                self._pending_url = ""
                self._pending_title = ""

    def close(self) -> None:
        super().close()
        if self._pending_url and self._pending_title:
            self.candidates.append(
                {
                    "url": self._pending_url,
                    "title": self._pending_title,
                    "snippet": "",
                }
            )
            self._pending_url = ""
            self._pending_title = ""


def fetch_candidates(query: str, *, timeout: int = 12) -> list[dict]:
    url = DDG_URL + "?q=" + urllib.parse.quote_plus(query or "")
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError:
        raise
    except Exception:
        return []
    try:
        html_text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw or "")
    except Exception:
        return []
    if not html_text:
        return []
    parser = _DDGParser()
    parser.feed(html_text)
    parser.close()
    return parser.candidates


def filter_candidates(candidates: list[dict]) -> list[dict]:
    filtered: list[dict] = []
    for cand in candidates or []:
        url = (cand.get("url") or "").strip() if isinstance(cand, dict) else ""
        if not url:
            continue
        if BAD_HOST_RE.search(url):
            continue
        filtered.append(cand)
    return filtered[:5]


def _parse_llm_json(text: str | None) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _http_code(exc: BaseException) -> int | None:
    code = getattr(exc, "code", None)
    if code is None:
        code = getattr(exc, "status", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def llm_validate(
    name: str, address: str | None, candidates: list[dict], api_key: str
) -> tuple[str | None, float]:
    if not candidates:
        return (None, 0.0)
    model = os.getenv("GEMINI_SEARCH_MODEL", DEFAULT_SEARCH_MODEL) or DEFAULT_SEARCH_MODEL
    lines = []
    for i, c in enumerate(candidates, start=1):
        lines.append(
            f"{i}. {c.get('url', '')} | {c.get('title', '')} | {c.get('snippet', '')}"
        )
    prompt = (
        "Devuelve SOLO JSON {url, score, reason}; acepta solo si nombre coincide y hay overlap de dirección; score<0.85 => url null. "
        f"Nombre: {name or ''}\nDirección: {address or ''}\nCandidatos:\n"
        + "\n".join(lines)
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512},
    }
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=LLM_TIMEOUT) as response:
            raw = response.read()
            result = (
                json.loads(raw.decode("utf-8"))
                if isinstance(raw, bytes)
                else json.loads(raw)
            )
    except urllib.error.HTTPError:
        raise
    except Exception:
        return (None, 0.0)
    text = "".join(
        part.get("text", "")
        for candidate in (result.get("candidates", []) if isinstance(result, dict) else [])
        for part in candidate.get("content", {}).get("parts", [])
    )
    data = _parse_llm_json(text)
    if data is None:
        return (None, 0.0)
    raw_url = data.get("url")
    raw_score = data.get("score", 0.0)
    try:
        score = float(raw_score) if raw_score is not None else 0.0
    except (TypeError, ValueError):
        return (None, 0.0)
    score = max(0.0, min(1.0, score))
    if raw_url is None or not isinstance(raw_url, str) or not raw_url.strip():
        return (None, score)
    returned = raw_url.strip()
    cand_urls = [
        (c.get("url") or "").strip().rstrip("/") if isinstance(c, dict) else ""
        for c in candidates
    ]
    cand_urls = [u for u in cand_urls if u]
    if returned.rstrip("/") not in cand_urls:
        # URL inventada por el LLM (homónimo / alucinación): no aceptar.
        return (None, score)
    if score < ACCEPT_THRESHOLD:
        return (None, score)
    return (returned, score)


def search_website(
    name: str, address: str | None, *, api_key: str | None, timeout: int = 12
) -> tuple[str | None, float, str | None]:
    if not api_key:
        return (None, 0.0, None)
    query = build_search_query(name, address)
    try:
        candidates = fetch_candidates(query, timeout=timeout)
    except urllib.error.HTTPError as exc:
        code = _http_code(exc)
        if code == 403:
            return (None, 0.0, "blocked")
        if code == 429:
            return (None, 0.0, "quota")
        return (None, 0.0, None)
    except Exception:
        return (None, 0.0, None)
    filtered = filter_candidates(candidates)
    if not filtered:
        return (None, 0.0, None)
    try:
        url, score = llm_validate(name, address, filtered, api_key)
    except urllib.error.HTTPError as exc:
        code = _http_code(exc)
        if code == 403:
            return (None, 0.0, "blocked")
        if code == 429:
            return (None, 0.0, "quota")
        return (None, 0.0, None)
    except Exception:
        return (None, 0.0, None)
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        score_f = 0.0
    if not url or score_f < ACCEPT_THRESHOLD:
        return (None, score_f, None)
    return (url, score_f, None)

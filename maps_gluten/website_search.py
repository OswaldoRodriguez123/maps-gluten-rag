"""Website search fallback: DuckDuckGo HTML (Playwright) + validación LLM.

No acepta ninguna URL sin validación LLM con nombre + overlap de
dirección y score >= 0.85. DuckDuckGo se navega con Playwright (evita el
anti-bot/anomaly que bloquea a urllib); Gemini sigue por urllib.
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
    r"instagram\.com|facebook\.com|tiktok\.com|tripadvisor|uber-?eats|rappi|pedidosya"
    r"|findmeglutenfree|wanderboat|yelp|zomato|doordash|grubhub|deliveroo|glovo"
    r"|google\.|gstatic|emprendo\.|todosnegocios|cybo\.|gfmapper|atly\.|justeat",
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


# --- helpers Playwright (DuckDuckGo) ---


def _launch_temp_browser():
    """Lanza un browser temporal para modo standalone (tests).

    Returns:
        tuple(pw, browser, page): `pw` es el objeto Playwright (usar
        ``pw.stop()`` al terminar), `browser` el Chromium y `page` una
        página nueva con el UA del proyecto.
    """
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
    )
    page = browser.new_page(user_agent=UA)
    return pw, browser, page


def _close_temp_browser(pw, browser, page) -> None:
    """Cierra page/browser/pw de _launch_temp_browser (best-effort)."""
    try:
        if page is not None:
            page.close()
    except Exception:
        pass
    try:
        if browser is not None:
            browser.close()
    except Exception:
        pass
    try:
        if pw is not None:
            pw.stop()
    except Exception:
        pass


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


def fetch_candidates(query: str, *, timeout: int = 12, page=None) -> list[dict]:
    """Busca en DuckDuckGo HTML con Playwright y devuelve candidatos.

    Args:
        query: texto de búsqueda.
        timeout: segundos para goto/wait (se convierte a ms para Playwright).
        page: página Playwright opcional. Si se pasa, se usa directamente
            (sin cerrarla). Si es None, se lanza un browser temporal que
            se cierra al terminar.

    Returns:
        Lista de dicts ``{"url", "title", "snippet"}`` (url ya decodificada
        desde ``uddg``). En cualquier fallo de red/timeout devuelve ``[]``.
        Lanza ``urllib.error.HTTPError`` (403/429) para que ``search_website``
        degrade a ``blocked``/``quota``.
    """
    url = DDG_URL + "?q=" + urllib.parse.quote_plus(query or "")
    timeout_ms = max(int(timeout or 12) * 1000, 1000)

    owns_browser = False
    pw = browser = temp_page = None
    effective_page = page
    if effective_page is None:
        try:
            pw, browser, temp_page = _launch_temp_browser()
            effective_page = temp_page
            owns_browser = True
        except Exception:
            return []

    try:
        # Navegar a DDG HTML.
        try:
            response = effective_page.goto(
                url, wait_until="domcontentloaded", timeout=timeout_ms
            )
        except urllib.error.HTTPError:
            raise
        except Exception as exc:
            # Playwright a veces mete el estado HTTP en el mensaje.
            msg = str(exc or "")
            if " 403" in msg or "Forbidden" in msg:
                raise urllib.error.HTTPError(url, 403, "Forbidden", None, None) from exc
            if " 429" in msg or "Too Many Requests" in msg:
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None) from exc
            return []

        # Mapear estado HTTP -> HTTPError para degradación 403/429.
        if response is not None:
            try:
                status = response.status
            except Exception:
                status = None
            if status == 403:
                raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
            if status == 429:
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

        # Esperar a que aparezcan resultados.
        try:
            effective_page.wait_for_selector("a.result__a", timeout=timeout_ms)
        except Exception:
            return []

        # Extraer del DOM renderizado (selectores del brief).
        try:
            entries = effective_page.eval_on_selector_all(
                "a.result__a",
                "els => els.map(e => ({href: e.getAttribute('href') || '', text: (e.innerText || e.textContent || '').trim()}))",
            )
        except Exception:
            return []
        if not entries:
            return []

        try:
            snippets = effective_page.eval_on_selector_all(
                "a.result__snippet",
                "els => els.map(e => (e.innerText || e.textContent || '').trim())",
            )
        except Exception:
            snippets = []
        if not isinstance(snippets, (list, tuple)):
            snippets = []

        results: list[dict] = []
        for idx, entry in enumerate(entries):
            if isinstance(entry, dict):
                href = entry.get("href") or ""
                title = (entry.get("text") or "").strip()
            else:
                # Fallback por orden título/snippet si el mock devuelve strings.
                href = ""
                title = str(entry or "").strip()
            decoded = _decode_uddg(href)
            if not decoded or not title:
                continue
            snippet = ""
            if idx < len(snippets):
                raw = snippets[idx]
                snippet = (
                    (raw or "").strip()
                    if isinstance(raw, str)
                    else str(raw or "").strip()
                )
                snippet = " ".join(snippet.split())
            results.append({"url": decoded, "title": title, "snippet": snippet})
        return results
    finally:
        if owns_browser:
            _close_temp_browser(pw, browser, temp_page)


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
    name: str,
    address: str | None,
    *,
    api_key: str | None,
    timeout: int = 12,
    page=None,
    browser=None,
) -> tuple[str | None, float, str | None]:
    """Busca el sitio oficial de un lugar en DuckDuckGo y lo valida con LLM.

    Args:
        name: nombre del lugar.
        address: dirección (o None).
        api_key: GEMINI_API_KEY. Sin ella devuelve ``(None, 0.0, None)`` sin red.
        timeout: segundos para la búsqueda DDG.
        page: página Playwright opcional (se usa directamente, no se cierra).
        browser: browser Playwright opcional. Se crea una página temporal
            con él y se cierra al final (el browser no se cierra).
            Si no se pasa ni ``page`` ni ``browser``, se lanza un browser
            temporal standalone (ver ``_launch_temp_browser``) y se cierra
            todo al final.
    """
    if not api_key:
        return (None, 0.0, None)
    query = build_search_query(name, address)

    effective_page = page
    temp_page = None
    owns_page = False
    pw = None
    temp_browser = None

    try:
        if effective_page is None:
            if browser is not None:
                try:
                    temp_page = browser.new_page(user_agent=UA)
                except Exception:
                    return (None, 0.0, None)
                effective_page = temp_page
                owns_page = True
            else:
                try:
                    pw, temp_browser, temp_page = _launch_temp_browser()
                except Exception:
                    return (None, 0.0, None)
                effective_page = temp_page
                owns_page = True

        try:
            candidates = fetch_candidates(query, timeout=timeout, page=effective_page)
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
    finally:
        # No cerrar la page del llamante; solo las temporales.
        if owns_page and temp_page is not None:
            try:
                temp_page.close()
            except Exception:
                pass
        if pw is not None or temp_browser is not None:
            try:
                if temp_browser is not None:
                    temp_browser.close()
            except Exception:
                pass
            try:
                if pw is not None:
                    pw.stop()
            except Exception:
                pass

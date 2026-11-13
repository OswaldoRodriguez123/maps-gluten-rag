"""Website search: SerpAPI (primary) + Brave Search (fallback) + LLM validation.

No acepta ninguna URL sin validación LLM con nombre + overlap de
dirección y score >= 0.85. SerpAPI evita anti-bot/IP ban (250 req/mes gratis);
Brave (plan free, JSON API con token) como fallback cuando SerpAPI no está
configurado o falla — evita el bloqueo anti-bot de DuckDuckGo HTML desde IPs
de datacenter.

Adicional: extrae platform_urls (Rappi, PedidosYa, UberEats, etc.) sin validación LLM.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .net import urlopen

DEFAULT_SEARCH_MODEL = "gemini-flash-lite-latest"
ACCEPT_THRESHOLD = 0.85
SERPAPI_URL = "https://serpapi.com/search.json"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
LLM_TIMEOUT = 30
PROBE_TIMEOUT = 8
PROBE_MAX_BYTES = 200_000

# Tokens genéricos de dirección que no aportan para el probe de página.
_ADDR_STOPWORDS = {
    "avenida", "av", "avda", "calle", "pasaje", "camino", "de", "del",
    "la", "las", "los", "el", "y", "en", "cl", "comuna", "region", "metropolitana",
}

# Igual que photos.py para los GET a los buscadores.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

# Hosts que NO son website oficial (se filtran para official_url, pero se capturan en platform_urls)
PLATFORM_HOST_RE = re.compile(
    r"uber-?eats|rappi|pedidosya|doordash|grubhub|deliveroo|glovo|justeat",
    re.IGNORECASE,
)

BAD_HOST_RE = re.compile(
    r"instagram\.com|facebook\.com|tiktok\.com|tripadvisor"
    r"|findmeglutenfree|wanderboat|yelp|zomato"
    r"|google\.|gstatic|emprendo\.|todosnegocios|cybo\.|gfmapper|atly\.|justeat",
    re.IGNORECASE,
)

# Prefijos de path que indican página de producto/categoría/pedido de una
# tienda propia: se normalizan a homepage (el sitio es lo mismo).
DEEP_PATH_RE = re.compile(
    r"^/(products|types|tags|categoria(-producto)?|pedir|order|colecciones|collections)(/|$)",
    re.IGNORECASE,
)

# Query params de tracking que siempre se quitan de la URL final.
TRACK_QUERY_RE = re.compile(r"^(utm_|srsltid|fbclid|gclid|rwg_token|aff|adj_)", re.IGNORECASE)

def normalize_official_url(url: str | None) -> str | None:
    """Normaliza una URL oficial validada.

    - Quita params de tracking (utm_*, srsltid, fbclid, etc.).
    - Tienda propia con path de producto/categoría/pedido (``/products/N``,
      ``/categoria-producto/...``, ``/pedir/...``) -> homepage (esquema+host).
    - NO toca hosts de plataformas de carta (``menu.tu-mesa.com``,
      ``tucity.cl``): su path profundo ES el contenido útil.
    """
    if not url or not url.strip():
        return url
    parsed = urllib.parse.urlsplit(url.strip())
    # Filtrar params de tracking.
    if parsed.query:
        kept = [
            kv for kv in parsed.query.split("&")
            if kv and not TRACK_QUERY_RE.match(kv.split("=", 1)[0])
        ]
        query = "&".join(kept)
    else:
        query = ""
    path = parsed.path
    if DEEP_PATH_RE.match(path):
        path = "/"
    return urllib.parse.urlunsplit(
        (parsed.scheme or "https", parsed.netloc, path, query, "")
    ) or url


# Hosts de plataformas de delivery conocidas (para platform_urls)
DELIVERY_PLATFORMS = {
    "rappi": re.compile(r"rappi\.(cl|com)", re.IGNORECASE),
    "pedidosya": re.compile(r"pedidosya\.(cl|com)", re.IGNORECASE),
    "ubereats": re.compile(r"uber-?eats|ubereats\.com", re.IGNORECASE),
    "doordash": re.compile(r"doordash\.com", re.IGNORECASE),
    "grubhub": re.compile(r"grubhub\.com", re.IGNORECASE),
    "deliveroo": re.compile(r"deliveroo\.(cl|com)", re.IGNORECASE),
    "glovo": re.compile(r"glovoapp\.com|glovo\.(cl|com)", re.IGNORECASE),
}


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


# --- SerpAPI (primary) ---


def fetch_candidates_serpapi(
    query: str, *, api_key: str | None, timeout: int = 10
) -> tuple[list[dict], str | None]:
    """Busca en SerpAPI (Google Search) y devuelve candidatos.

    Args:
        query: texto de búsqueda.
        api_key: SERPAPI_KEY. Si es None, devuelve ([], "no_key").
        timeout: segundos para la request HTTP.

    Returns:
        Tupla (lista_de_candidatos, status).
        status puede ser: None (ok), "no_key", "blocked", "quota", "error".
        Candidatos: lista de dicts {"url", "title", "snippet"}.
    """
    if not api_key:
        return [], "no_key"

    params = {
        "q": query,
        "api_key": api_key,
        "engine": "google",
        "gl": "cl",
        "hl": "es",
        "num": "10",
        "safe": "active",
    }
    url = SERPAPI_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": UA,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        code = getattr(exc, "code", None)
        if code == 403:
            return [], "blocked"
        if code == 429:
            return [], "quota"
        return [], "error"
    except Exception:
        return [], "error"

    results: list[dict] = []
    # SerpAPI devuelve resultados en "organic_results"
    for item in data.get("organic_results", [])[:10]:
        if not isinstance(item, dict):
            continue
        url = (item.get("link") or "").strip()
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or item.get("description") or "").strip()
        if not url or not title:
            continue
        results.append({"url": url, "title": title, "snippet": snippet})
    return results, None


# --- Brave Search (fallback) ---


def fetch_candidates_brave(
    query: str, *, api_key: str | None, timeout: int = 10
) -> tuple[list[dict], str | None]:
    """Busca en Brave Search API y devuelve candidatos.

    Args:
        query: texto de búsqueda.
        api_key: BRAVE_API_KEY. Si es None, devuelve ([], "no_key").
        timeout: segundos para la request HTTP.

    Returns:
        Tupla (lista_de_candidatos, status).
        status puede ser: None (ok), "no_key", "blocked", "quota", "error".
        Candidatos: lista de dicts {"url", "title", "snippet"}.
    """
    if not api_key:
        return [], "no_key"

    params = {
        "q": query,
        "count": "10",
        "country": "cl",
        "search_lang": "es",
        "safesearch": "moderate",
    }
    url = BRAVE_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": UA,
            "X-Subscription-Token": api_key,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        code = getattr(exc, "code", None)
        if code == 403:
            return [], "blocked"
        if code == 429:
            return [], "quota"
        return [], "error"
    except Exception:
        return [], "error"

    if not isinstance(data, dict):
        return [], None
    web = data.get("web")
    items = web.get("results") if isinstance(web, dict) else None
    if not isinstance(items, list):
        return [], None
    results: list[dict] = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        snippet = (item.get("description") or "").strip()
        if not url or not title:
            continue
        if not url.startswith(("http://", "https://")):
            continue
        results.append({"url": url, "title": title, "snippet": snippet})
    return results, None


def _brand_hits(url: str, name: str | None) -> int:
    """Cuántos tokens de la marca aparecen en el dominio (para pre-ordenar, no para aceptar)."""
    tokens = _significant_tokens(name)
    if not tokens:
        return 0
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return sum(1 for t in tokens if t in host)


def filter_candidates(
    candidates: list[dict], *, name: str | None = None
) -> list[dict]:
    """Filtra candidatos para official_url: quita redes sociales, directorios, delivery.

    Pre-ordena por dominio con tokens de la marca para que el sitio oficial sobreviva
    al límite de 5 (Brave/Google a veces lo traen atrás de artículos y páginas de terceros).
    La decisión final sigue siendo del LLM.
    """
    filtered: list[dict] = []
    for cand in candidates or []:
        url = (cand.get("url") or "").strip() if isinstance(cand, dict) else ""
        if not url:
            continue
        if BAD_HOST_RE.search(url):
            continue
        if PLATFORM_HOST_RE.search(url):
            continue
        filtered.append(cand)
    filtered.sort(key=lambda c: _brand_hits(c.get("url") or "", name), reverse=True)
    return filtered[:5]


def extract_platform_urls(candidates: list[dict]) -> dict[str, list[str]]:
    """Extrae URLs de plataformas de delivery conocidas sin validación LLM."""
    platform_urls: dict[str, list[str]] = {k: [] for k in DELIVERY_PLATFORMS}
    for cand in candidates or []:
        url = (cand.get("url") or "").strip() if isinstance(cand, dict) else ""
        if not url:
            continue
        for platform, pattern in DELIVERY_PLATFORMS.items():
            if pattern.search(url):
                platform_urls[platform].append(url)
                break
    # Quitar vacíos y duplicados preservando orden
    for k in list(platform_urls.keys()):
        seen = set()
        uniq = []
        for u in platform_urls[k]:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        platform_urls[k] = uniq[:3]  # máx 3 por plataforma
        if not platform_urls[k]:
            del platform_urls[k]
    return platform_urls


def _significant_tokens(address: str | None) -> list[str]:
    """Tokens útiles de la dirección (calle, número, comuna), normalizados y sin stopwords."""
    norm = _normalize(address).lower()
    out: list[str] = []
    for tok in norm.split():
        if (len(tok) >= 4 or tok.isdigit()) and tok not in _ADDR_STOPWORDS and tok not in out:
            out.append(tok)
    return out


def _page_evidence(url: str, address: str | None, *, timeout: int = PROBE_TIMEOUT) -> str:
    """GET liviano a la página candidata; devuelve los tokens de la dirección que contiene.

    Degrada a ``""`` ante cualquier fallo (red, timeout, encoding): nunca crashea el pipeline.
    """
    tokens = _significant_tokens(address)
    if not url or not tokens:
        return ""
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": UA, "Accept": "text/html"},
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(PROBE_MAX_BYTES)
    except Exception:
        return ""
    html_text = raw.decode("utf-8", "ignore")
    html_text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html_text)
    html_text = re.sub(r"<[^>]+>", " ", html_text)
    text = _normalize(html_text).lower()
    found = [t for t in tokens if t in text]
    return ",".join(found)


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
    name: str,
    address: str | None,
    candidates: list[dict],
    api_key: str,
    evidence: dict | None = None,
) -> tuple[str | None, float]:
    if not candidates:
        return (None, 0.0)
    model = os.getenv("GEMINI_SEARCH_MODEL", DEFAULT_SEARCH_MODEL) or DEFAULT_SEARCH_MODEL
    lines = []
    for i, c in enumerate(candidates, start=1):
        line = (
            f"{i}. {c.get('url', '')} | {c.get('title', '')} | {c.get('snippet', '')}"
        )
        if evidence is not None:
            line += f" | evidencia: {evidence.get(c.get('url', '')) or 'sin evidencia'}"
        lines.append(line)
    prompt = (
        "Devuelve SOLO JSON {url, score, reason}; acepta SOLO el sitio oficial del local/marca "
        "(dominio propio del negocio; NO artículos, notas de prensa, directorios, reviews, blogs ni redes sociales). "
        "Acepta solo si nombre coincide y hay overlap de dirección; "
        "la evidencia de página (tokens de la dirección hallados en el sitio) cuenta como overlap fuerte, "
        "pero no basta por sí sola si el candidato no es el sitio oficial; "
        "sin evidencia de dirección, exige que el snippet o el título la traigan; score<0.85 => url null. "
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
        with urlopen(request, timeout=LLM_TIMEOUT) as response:
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
) -> tuple[str | None, float, str | None, dict[str, list[str]]]:
    """Busca el sitio oficial + platform URLs: SerpAPI (primary) -> Brave (fallback) + LLM validation.

    Args:
        name: nombre del lugar.
        address: dirección (o None).
        api_key: GEMINI_API_KEY (para validación LLM). Sin ella devuelve ``(None, 0.0, None, {})`` sin red.
        timeout: segundos para la búsqueda.

    Returns:
        Tupla (official_url, score, status, platform_urls).
        official_url: website oficial validado por LLM (score >= 0.85) o None.
        score: float 0.0-1.0.
        status: None (SerpAPI ok), "brave_fallback" (SerpAPI falló, Brave ok),
            "no_serpapi_key" (sin SERPAPI_KEY, Brave ok), "blocked"/"quota"
            (403/429 en el motor intentado), "error" (otro fallo),
            "no_search_key" (ninguna key configurada).
        platform_urls: dict {"rappi": [...], "pedidosya": [...], "ubereats": [...]} sin validación LLM.
    """
    if not api_key:
        return (None, 0.0, None, {})

    query = build_search_query(name, address)
    serpapi_key = os.getenv("SERPAPI_KEY", "").strip() or None
    brave_key = os.getenv("BRAVE_API_KEY", "").strip() or None

    all_candidates: list[dict] = []
    status: str | None = None
    serpapi_status: str | None = None
    brave_status: str | None = None

    # --- 1. Intentar SerpAPI (primary) ---
    if serpapi_key:
        candidates, serpapi_status = fetch_candidates_serpapi(
            query, api_key=serpapi_key, timeout=min(timeout, 10)
        )
        if serpapi_status is None:
            all_candidates = candidates
            status = None

    # --- 2. Fallback a Brave si SerpAPI no produjo candidatos ---
    if not all_candidates and brave_key:
        candidates, brave_status = fetch_candidates_brave(
            query, api_key=brave_key, timeout=min(timeout, 10)
        )
        if brave_status is None:
            all_candidates = candidates
            status = "brave_fallback" if serpapi_key else "no_serpapi_key"

    if not all_candidates:
        if not serpapi_key and not brave_key:
            status = "no_search_key"
        elif brave_status:
            status = brave_status
        elif serpapi_status:
            status = serpapi_status
        # else: motores ok pero sin resultados -> status None.

    # --- Extraer platform_urls de TODOS los candidatos (antes de filtrar) ---
    platform_urls = extract_platform_urls(all_candidates)

    # --- Filtrar para official_url (quita delivery, redes, directorios) ---
    filtered = filter_candidates(all_candidates, name=name)
    if not filtered:
        return (None, 0.0, status, platform_urls)

    # --- Validar con LLM (con evidencia de página si se pudo obtener) ---
    evidences = {
        (c.get("url") or ""): _page_evidence(c.get("url") or "", address)
        for c in filtered
    }
    try:
        url, score = llm_validate(name, address, filtered, api_key, evidences)
    except urllib.error.HTTPError as exc:
        code = _http_code(exc)
        if code == 403:
            return (None, 0.0, "blocked", platform_urls)
        if code == 429:
            return (None, 0.0, "quota", platform_urls)
        return (None, 0.0, status, platform_urls)
    except Exception:
        return (None, 0.0, status, platform_urls)

    try:
        score_f = float(score)
    except (TypeError, ValueError):
        score_f = 0.0
    if not url or score_f < ACCEPT_THRESHOLD:
        return (None, score_f, status, platform_urls)
    normalized = normalize_official_url(url)
    if not normalized:
        return (url, score_f, status, platform_urls)
    return (normalized, score_f, status, platform_urls)

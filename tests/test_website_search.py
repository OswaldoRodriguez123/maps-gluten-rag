"""Tests para maps_gluten.website_search: DuckDuckGo HTML + validación LLM."""
import json
import urllib.error
import urllib.parse


DDG_FIXTURE = """
<html><body>
<div class="result results_links">
  <div class="result__body">
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fbickacafe.cl%2F&rut=aaa">Bicka Café - Sitio Oficial</a>
    <a class="result__snippet">Café sin gluten en Vitacura, Av. Luis Pasteur 6156.
    </a>
  </div>
</div>
<div class="result results_links">
  <div class="result__body">
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fwww.tripadvisor.cl%2FRestaurant_Review-g1.html&rut=bbb">Bicka Café en Tripadvisor</a>
    <a class="result__snippet">Reviews y fotos de Bicka Café.
    </a>
  </div>
</div>
<div class="result results_links">
  <div class="result__body">
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fwww.instagram.com%2Fbickacafe%2F&rut=ccc">Bicka Café en Instagram</a>
    <a class="result__snippet">Síguenos en Instagram.
    </a>
  </div>
</div>
</body></html>
"""


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakePage:
    """Fake página Playwright para fetch_candidates/search_website (DDG HTML)."""

    def __init__(self, entries=None, snippets=None, status=200, goto_exc=None):
        self._entries = entries or []
        self._snippets = snippets or []
        self._status = status
        self._goto_exc = goto_exc
        self.goto_url = None

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_url = url
        assert "html.duckduckgo.com/html/" in url
        assert "q=" in url
        if self._goto_exc is not None:
            raise self._goto_exc
        page = self

        class _Resp:
            status = page._status

        return _Resp()

    def wait_for_selector(self, *args, **kwargs):
        return None

    def eval_on_selector_all(self, selector, expr):
        if selector == "a.result__a":
            return self._entries
        if selector == "a.result__snippet":
            return self._snippets
        return []

    def close(self):
        pass


_DDG_ENTRIES = [
    {"href": "/l/?uddg=https%3A%2F%2Fbickacafe.cl%2F&rut=aaa", "text": "Bicka Café - Sitio Oficial"},
    {"href": "/l/?uddg=https%3A%2F%2Fwww.tripadvisor.cl%2FRestaurant_Review-g1.html&rut=bbb", "text": "Bicka Café en Tripadvisor"},
    {"href": "/l/?uddg=https%3A%2F%2Fwww.instagram.com%2Fbickacafe%2F&rut=ccc", "text": "Bicka Café en Instagram"},
]
_DDG_SNIPPETS = [
    "Café sin gluten en Vitacura, Av. Luis Pasteur 6156.",
    "Reviews y fotos de Bicka Café.",
    "Síguenos en Instagram.",
]


def _fake_ddg_page(**kwargs):
    kwargs.setdefault("entries", _DDG_ENTRIES)
    kwargs.setdefault("snippets", _DDG_SNIPPETS)
    return _FakePage(**kwargs)


def _llm_response(payload: dict) -> _FakeResponse:
    body = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]
                }
            }
        ]
    }
    return _FakeResponse(json.dumps(body, ensure_ascii=False).encode("utf-8"))


# --- 1. build_search_query ---

def test_build_search_query_strips_and_adds_comuna():
    from maps_gluten.website_search import build_search_query

    got = build_search_query("Café Bicka", "Av. Luis Pasteur 6156, Vitacura")
    assert got == '"Café Bicka" sin gluten Vitacura Av Luis Pasteur 6156'


def test_build_search_query_without_address():
    from maps_gluten.website_search import build_search_query

    assert build_search_query("Café Bicka", None) == '"Café Bicka" sin gluten'
    assert build_search_query("Café Bicka", "") == '"Café Bicka" sin gluten'
    # Sin coma: no se inventa comuna; la dirección va tal cual normalizada.
    got = build_search_query("Café Bicka", "Av. Luis Pasteur 6156")
    assert "Vitacura" not in got
    assert "Luis Pasteur" in got


# --- 2. fetch_candidates ---

def test_fetch_candidates_parses_duckduckgo_html():
    from maps_gluten import website_search

    page = _fake_ddg_page()
    results = website_search.fetch_candidates("x", page=page)
    assert len(results) == 3
    assert [r["url"] for r in results] == [
        "https://bickacafe.cl/",
        "https://www.tripadvisor.cl/Restaurant_Review-g1.html",
        "https://www.instagram.com/bickacafe/",
    ]
    assert results[0]["title"] == "Bicka Café - Sitio Oficial"
    assert "Vitacura" in results[0]["snippet"]
    assert results[1]["url"].startswith("https://www.tripadvisor.cl/")


# --- 3. filter_candidates ---

def test_filter_candidates_drops_social_and_keeps_official():
    from maps_gluten.website_search import filter_candidates

    candidates = [
        {"url": "https://bickacafe.cl/", "title": "Oficial", "snippet": "web"},
        {"url": "https://www.instagram.com/bickacafe/", "title": "IG", "snippet": "x"},
        {"url": "https://www.facebook.com/bickacafe", "title": "FB", "snippet": "x"},
        {"url": "https://www.tiktok.com/@bicka", "title": "TT", "snippet": "x"},
        {"url": "https://www.uber-eats.cl/x", "title": "UE", "snippet": "x"},
        {"url": "https://www.ubereats.com/cl/x", "title": "UE2", "snippet": "x"},
        {"url": "https://www.rappi.com.cl/x", "title": "RP", "snippet": "x"},
        {"url": "https://www.pedidosya.cl/x", "title": "PY", "snippet": "x"},
        {"url": "https://www.tripadvisor.cl/x", "title": "TA", "snippet": "x"},
        {"url": "https://otra-bicka.cl/", "title": "Otra oficial", "snippet": "x"},
    ]
    filtered = filter_candidates(candidates)
    urls = [c["url"] for c in filtered]
    assert urls == ["https://bickacafe.cl/", "https://otra-bicka.cl/"]
    for bad in ["instagram", "facebook", "tiktok", "uber-eats", "ubereats", "rappi", "pedidosya", "tripadvisor"]:
        assert not any(bad in u for u in urls)


def test_filter_candidates_drops_directories_and_delivery():
    from maps_gluten.website_search import filter_candidates

    candidates = [
        {"url": "https://cafe-aquelarre.cl/", "title": "Oficial", "snippet": "web"},
        {"url": "https://www.findmeglutenfree.com/biz/cafe-aquelarre/5290473287188480", "title": "FMGF", "snippet": "x"},
        {"url": "https://emprendo.sanmiguel.cl/project/cafe_aquelarre/", "title": "Emprendo", "snippet": "x"},
        {"url": "https://wanderboat.ai/restaurants/chile/san-miguel/cafe-aquelarre/mthR2RpHTrqvBFRAAb0Mlg", "title": "WB", "snippet": "x"},
        {"url": "https://www.google.com/maps/search/cafe-aquelarre", "title": "Maps", "snippet": "x"},
    ]
    filtered = filter_candidates(candidates)
    assert [c["url"] for c in filtered] == ["https://cafe-aquelarre.cl/"]


def test_filter_candidates_limits_to_five_and_bad_host_re():
    from maps_gluten.website_search import BAD_HOST_RE, PLATFORM_HOST_RE, filter_candidates

    candidates = [
        {"url": f"https://sitio{i}.cl/", "title": f"t{i}", "snippet": "x"}
        for i in range(7)
    ]
    filtered = filter_candidates(candidates)
    assert len(filtered) == 5
    # BAD_HOST_RE debe cubrir sociales/directorios (case-insensitive).
    for host in [
        "https://www.instagram.com/a",
        "https://www.facebook.com/a",
        "https://www.tiktok.com/a",
        "https://www.tripadvisor.cl/a",
        "https://www.findmeglutenfree.com/biz/cafe-aquelarre/",
        "https://wanderboat.ai/restaurants/chile/san-miguel/cafe-aquelarre/",
        "https://emprendo.sanmiguel.cl/project/cafe_aquelarre/",
        "https://www.yelp.com/biz/cafe",
        "https://www.zomato.com/santiago/cafe",
        "https://www.google.com/maps/search/cafe",
    ]:
        assert BAD_HOST_RE.search(host), host
    # PLATFORM_HOST_RE debe cubrir delivery platforms.
    for host in [
        "https://WWW.UBEREATS.COM/a",
        "https://www.uber-eats.cl/a",
        "https://www.rappi.com.cl/a",
        "https://www.pedidosya.cl/a",
        "https://www.doordash.com/store/cafe",
        "https://www.grubhub.com/restaurant/cafe",
        "https://deliveroo.cl/restaurants/santiago/cafe",
        "https://glovoapp.com/cl/cafe",
    ]:
        assert PLATFORM_HOST_RE.search(host), host


# --- 4. llm_validate ---

def test_llm_validate_requires_name_and_address_overlap(monkeypatch):
    from maps_gluten import website_search

    candidates = [{"url": "https://bickacafe.cl/", "title": "Bicka", "snippet": "Av Pasteur"}]

    def ok_urlopen(request, timeout=None):
        url = request.full_url
        assert "generativelanguage.googleapis.com" in url
        assert ":generateContent" in url
        return _llm_response({"url": "https://bickacafe.cl/", "score": 0.92, "reason": "ok"})

    monkeypatch.setattr("urllib.request.urlopen", ok_urlopen)
    assert website_search.llm_validate(
        "Café Bicka", "Av. Luis Pasteur 6156, Vitacura", candidates, "key"
    ) == ("https://bickacafe.cl/", 0.92)

    def low_urlopen(request, timeout=None):
        return _llm_response({"url": "https://bickacafe.cl/", "score": 0.4, "reason": "nombre distinto"})

    monkeypatch.setattr("urllib.request.urlopen", low_urlopen)
    assert website_search.llm_validate(
        "Café Bicka", "Av. Luis Pasteur 6156, Vitacura", candidates, "key"
    ) == (None, 0.4)


def test_llm_validate_rejects_invented_url_homonym(monkeypatch):
    """Homónimo / alucinación: la URL del LLM no puede inventarse fuera de candidatos."""
    from maps_gluten import website_search

    candidates = [{"url": "https://bickacafe.cl/", "title": "Bicka", "snippet": "Av Pasteur"}]

    def fake_urlopen(request, timeout=None):
        # LLM devuelve una URL que no está en los candidatos (homónimo).
        return _llm_response({"url": "https://bicka-providencia.cl/", "score": 0.93, "reason": "parece"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    url, score = website_search.llm_validate(
        "Café Bicka", "Av. Luis Pasteur 6156, Vitacura", candidates, "key"
    )
    assert url is None
    assert score == 0.93

    # score bajo por homónimo real (mismo nombre, dirección distinta) -> None.
    def homonym_urlopen(request, timeout=None):
        return _llm_response({"url": "https://bicka-providencia.cl/", "score": 0.3, "reason": "otra dirección"})

    monkeypatch.setattr("urllib.request.urlopen", homonym_urlopen)
    assert website_search.llm_validate(
        "Café Bicka", "Av. Luis Pasteur 6156, Vitacura", candidates, "key"
    ) == (None, 0.3)


# --- 5. search_website sin API key ---

def test_search_website_returns_none_when_no_api_key(monkeypatch):
    from maps_gluten import website_search

    def boom(*args, **kwargs):
        raise AssertionError("no debe llamar a la red sin API key")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert website_search.search_website("Café", "Av X", api_key=None) == (None, 0.0, None, {})
    assert website_search.search_website("Café", "Av X", api_key="") == (None, 0.0, None, {})


# --- 5b. normalize_official_url ---

def test_normalize_official_url_strips_tracking_and_deep_shop_paths():
    from maps_gluten.website_search import normalize_official_url

    # Tracking params fuera.
    assert normalize_official_url(
        "https://ejemplo.cl/?utm_src=x&srsltid=y&q=ok"
    ) == "https://ejemplo.cl/?q=ok"
    # Deep-link de tienda propia -> homepage.
    assert normalize_official_url("https://www.allfree.cl/products/2") == "https://www.allfree.cl/"
    assert normalize_official_url(
        "https://www.biomercado.cl/categoria-producto/pan/"
    ) == "https://www.biomercado.cl/"
    assert normalize_official_url(
        "https://www.bfreshpaseo.cl/pedir/d5hfAYwkpTKJ"
    ) == "https://www.bfreshpaseo.cl/"
    # Path profundo útil en host de carta: NO se recorta.
    assert normalize_official_url(
        "https://menu.tu-mesa.com/bar-el-bajo/7689/menu"
    ) == "https://menu.tu-mesa.com/bar-el-bajo/7689/menu"
    # Homepage simple queda igual.
    assert normalize_official_url("https://ejemplo.cl/") == "https://ejemplo.cl/"
    assert normalize_official_url(None) is None
    assert normalize_official_url("") == ""


# --- 6. search_website degradación 403 / 429 ---

def test_search_website_degrades_on_block_and_429(monkeypatch):
    from maps_gluten import website_search

    # Mock SerpAPI para que no se use (simular que no hay key o falla)
    monkeypatch.setattr(
        "maps_gluten.website_search.fetch_candidates_serpapi",
        lambda query, *, api_key, timeout: ([], "no_key"),
    )

    # DDG responde 403 vía Playwright (status en response) -> blocked.
    result = website_search.search_website(
        "Café Bicka", "Vitacura", api_key="key", page=_FakePage(status=403)
    )
    assert result == (None, 0.0, "blocked", {})

    # DDG responde 429 -> quota.
    result = website_search.search_website(
        "Café Bicka", "Vitacura", api_key="key", page=_FakePage(status=429)
    )
    assert result == (None, 0.0, "quota", {})


def test_search_website_end_to_end_accepts_strong_match(monkeypatch):
    """Flujo completo: build->fetch->filter->llm_validate, solo acepta score>=0.85."""
    from maps_gluten import website_search

    # Mock SerpAPI para que no se use
    monkeypatch.setattr(
        "maps_gluten.website_search.fetch_candidates_serpapi",
        lambda query, *, api_key, timeout: ([], "no_key"),
    )

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        # Solo Gemini usa urllib (DDG va por la página Playwright falsa).
        calls["n"] += 1
        assert "generativelanguage.googleapis.com" in request.full_url
        return _llm_response({"url": "https://bickacafe.cl/", "score": 0.91, "reason": "ok"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    url, score, error, platforms = website_search.search_website(
        "Café Bicka", "Av. Luis Pasteur 6156, Vitacura", api_key="key", page=_fake_ddg_page()
    )
    assert (url, score, error) == ("https://bickacafe.cl/", 0.91, "no_serpapi_key")
    assert platforms == {}
    assert calls["n"] == 1


# --- 7. Task 2: integración en enrich_places (fallback search) ---

def test_enrich_places_uses_search_fallback(monkeypatch):
    from maps_gluten import enrich
    from maps_gluten.extract import Place

    class FakePage:
        def __init__(self, website=None):
            self._website = website

        def goto(self, *args, **kwargs):
            pass

        def wait_for_selector(self, *args, **kwargs):
            pass

        def wait_for_timeout(self, *args, **kwargs):
            pass

        def evaluate(self, js):
            if js == enrich.WEBSITE_JS:
                return self._website
            return []

        def inner_text(self, *args, **kwargs):
            return ""

    monkeypatch.setattr(enrich, "_site_dishes", lambda url, ocr=False: [])
    monkeypatch.setattr(enrich, "_render_site_products", lambda page, url: [])
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    # Caso fuerte: search devuelve score 0.9 -> acepta URL + procedencia search.
    place = Place(
        ftid="t1",
        name="Café Ejemplo",
        address="Av X 123, Vitacura",
        category=None,
        rating=None,
        reviews=None,
        note=None,
        url="https://maps.example/1",
    )
    captured: dict = {}

    def _fake_search(name, address, *, api_key, timeout=12, page=None):
        captured["page"] = page
        return ("https://ejemplo.cl/", 0.9, None, {})

    monkeypatch.setattr(
        "maps_gluten.website_search.search_website",
        _fake_search,
    )
    fake_page = FakePage(website=None)
    enrich.enrich_places(
        fake_page,
        [place],
        cache={},
        search_enabled=True,
        gemini_api_key="key",
        website_dishes=False,
    )
    assert place.website == "https://ejemplo.cl/"
    assert place.website_source == "search"
    assert captured.get("page") is fake_page

    # Caso débil: score 0.3 -> no acepta, queda sin website.
    place2 = Place(
        ftid="t2",
        name="Café Ejemplo",
        address="Av X 123, Vitacura",
        category=None,
        rating=None,
        reviews=None,
        note=None,
        url="https://maps.example/2",
    )
    monkeypatch.setattr(
        "maps_gluten.website_search.search_website",
        lambda name, address, *, api_key, timeout=12, page=None: ("https://ejemplo.cl/", 0.3, None, {}),
    )
    enrich.enrich_places(
        FakePage(website=None),
        [place2],
        cache={},
        search_enabled=True,
        gemini_api_key="key",
        website_dishes=False,
    )
    assert place2.website is None
    assert place2.website_source is None


# --- 8. Task 4: flag CLI --website-search/--no-website-search ---

def test_cli_parses_no_website_search():
    from maps_gluten.cli import _build_parser

    args = _build_parser().parse_args(["run", "--no-website-search"])
    assert args.website_search is False

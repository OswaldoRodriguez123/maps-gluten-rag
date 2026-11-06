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

def test_fetch_candidates_parses_duckduckgo_html(monkeypatch):
    from maps_gluten import website_search

    def fake_urlopen(request, timeout=None):
        # Debe pedir al endpoint HTML de DuckDuckGo con el query.
        url = request.full_url
        assert "html.duckduckgo.com/html/" in url
        assert "q=" in url
        assert request.get_header("User-agent") is not None
        return _FakeResponse(DDG_FIXTURE.encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    results = website_search.fetch_candidates("x")
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


def test_filter_candidates_limits_to_five_and_bad_host_re():
    from maps_gluten.website_search import BAD_HOST_RE, filter_candidates

    candidates = [
        {"url": f"https://sitio{i}.cl/", "title": f"t{i}", "snippet": "x"}
        for i in range(7)
    ]
    filtered = filter_candidates(candidates)
    assert len(filtered) == 5
    # BAD_HOST_RE debe cubrir sociales/agregadores (case-insensitive).
    for host in [
        "https://www.instagram.com/a",
        "https://www.facebook.com/a",
        "https://www.tiktok.com/a",
        "https://www.tripadvisor.cl/a",
        "https://WWW.UBEREATS.COM/a",
    ]:
        assert BAD_HOST_RE.search(host), host


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
    assert website_search.search_website("Café", "Av X", api_key=None) == (None, 0.0, None)
    assert website_search.search_website("Café", "Av X", api_key="") == (None, 0.0, None)


# --- 6. search_website degradación 403 / 429 ---

def test_search_website_degrades_on_block_and_429(monkeypatch):
    from maps_gluten import website_search

    def blocked(request, timeout=None):
        raise urllib.error.HTTPError(
            url=request.full_url, code=403, msg="Forbidden", hdrs=None, fp=None
        )

    monkeypatch.setattr("urllib.request.urlopen", blocked)
    assert website_search.search_website("Café Bicka", "Vitacura", api_key="key") == (
        None,
        0.0,
        "blocked",
    )

    def quota(request, timeout=None):
        raise urllib.error.HTTPError(
            url=request.full_url, code=429, msg="Too Many Requests", hdrs=None, fp=None
        )

    monkeypatch.setattr("urllib.request.urlopen", quota)
    assert website_search.search_website("Café Bicka", "Vitacura", api_key="key") == (
        None,
        0.0,
        "quota",
    )


def test_search_website_end_to_end_accepts_strong_match(monkeypatch):
    """Flujo completo: build->fetch->filter->llm_validate, solo acepta score>=0.85."""
    from maps_gluten import website_search

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        url = request.full_url
        if "html.duckduckgo.com" in url:
            return _FakeResponse(DDG_FIXTURE.encode("utf-8"))
        return _llm_response({"url": "https://bickacafe.cl/", "score": 0.91, "reason": "ok"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    url, score, error = website_search.search_website(
        "Café Bicka", "Av. Luis Pasteur 6156, Vitacura", api_key="key"
    )
    assert (url, score, error) == ("https://bickacafe.cl/", 0.91, None)
    assert calls["n"] == 2

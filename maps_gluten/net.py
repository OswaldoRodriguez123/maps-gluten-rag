"""Control de egress para fetches a URLs externas.

Toda URL derivada de material no confiable (websites de Maps, candidatos de
búsqueda, fotos de Apify) pasa por :func:`ensure_public_url` antes de
cualquier conexión, y cada redirect es revalidado:

- urllib: :func:`urlopen` valida la URL inicial y cada salto de redirect.
- requests: :func:`fetch_capped` sigue redirects manualmente con
  ``allow_redirects=False`` y revalida cada salto (robusto incluso con una
  sesión plana); :func:`guarded_session` además monta un adapter que valida
  cada request como defensa en profundidad.
- Playwright: ver ``extract._launch`` (route guard a nivel de contexto).

Reglas: esquema http/https únicamente; el host debe existir (IP literal o DNS)
y todas sus direcciones resueltas deben ser globales (no loopback, privadas,
link-local, CGN ni reservadas).
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.request
from urllib.parse import urljoin, urlparse

DEFAULT_MAX_BYTES = 5_000_000

_host_cache: dict[str, bool] = {}


class UnsafeUrlError(ValueError):
    """La URL apunta a un destino no público o no es http(s)."""


class BodyTooLargeError(ValueError):
    """El cuerpo excedió el tope permitido."""


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_global


def _host_public(host: str) -> bool:
    if host in _host_cache:
        return _host_cache[host]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        # IP literal: no requiere DNS.
        result = _ip_is_public(ip)
        _host_cache[host] = result
        return result
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        _host_cache[host] = False
        return False
    result = bool(infos) and all(
        _ip_is_public(ipaddress.ip_address(info[4][0])) for info in infos
    )
    _host_cache[host] = result
    return result


def public_url_error(url: str) -> str | None:
    """Devuelve el motivo si la URL no es un destino público http(s), o None."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "url inválida"
    if parsed.scheme not in {"http", "https"}:
        return "esquema no permitido (solo http/https)"
    host = parsed.hostname
    if not host:
        return "URL sin host"
    if not _host_public(host):
        return f"host no público o no resolvible: {host}"
    return None


def ensure_public_url(url: str) -> str:
    error = public_url_error(url)
    if error:
        raise UnsafeUrlError(f"Destino no permitido: {error}")
    return url


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ensure_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_PublicRedirectHandler())
# Instala el opener con validación de redirects a nivel proceso: cualquier
# uso stdlib de urllib en el proceso pasa por el chequeo de redirects.
urllib.request.install_opener(_OPENER)


def urlopen(request, timeout: int = 60):
    """urllib con validación de la URL inicial y de cada redirect."""
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    ensure_public_url(url)
    return urllib.request.urlopen(request, timeout=timeout)


def guarded_session():
    """Session de requests que valida cada request (incluidos redirects)."""
    import requests

    class _PublicAdapter(requests.adapters.HTTPAdapter):
        def send(self, request, **kwargs):
            ensure_public_url(request.url)
            return super().send(request, **kwargs)

    session = requests.Session()
    adapter = _PublicAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class CappedResponse:
    """Respuesta requests con cuerpo limitado a max_bytes."""

    def __init__(self, status_code: int, url: str, content: bytes):
        self.status_code = status_code
        self.url = url
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "ignore")

    def json(self):
        return json.loads(self.text)


MAX_REDIRECTS = 10


def fetch_capped(
    session,
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: int = 25,
    headers: dict | None = None,
    params: dict | None = None,
) -> CappedResponse:
    """GET con tope de tamaño; nunca mantiene más de max_bytes en memoria.

    Los redirects se siguen manualmente revalidando cada salto (una sesión
    plana de requests no garantiza que los hops pasen por el guard).

    Los test doubles de sesión (sin iter_content) se devuelven tal cual:
    son fixtures confiables y ya viven en memoria.
    """
    current = ensure_public_url(url)
    redirects = 0
    while True:
        response = session.get(
            current,
            headers=headers,
            params=params,
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        if not hasattr(response, "iter_content"):
            return response
        status = getattr(response, "status_code", None)
        location = response.headers.get("location") if hasattr(response, "headers") else None
        if status in {301, 302, 303, 307, 308} and location:
            response.close()
            current = ensure_public_url(urljoin(current, location))
            redirects += 1
            if redirects > MAX_REDIRECTS:
                raise UnsafeUrlError(f"demasiados redirects (>{MAX_REDIRECTS})")
            params = None  # params solo aplican a la URL original
            continue
        with response as resp:
            data = b""
            for chunk in resp.iter_content(chunk_size=65536):
                data += chunk
                if len(data) > max_bytes:
                    resp.close()
                    raise BodyTooLargeError(
                        f"cuerpo excede {max_bytes} bytes: {current}"
                    )
            return CappedResponse(resp.status_code, resp.url, data)

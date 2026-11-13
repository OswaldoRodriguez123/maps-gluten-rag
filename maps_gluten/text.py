"""Utilidades de texto para datos no confiables que van a Markdown/Docs."""

from __future__ import annotations

import re

# Separadores de línea ASCII y Unicode (incluye NEL, LS, PS) y controles.
_LINE_BREAKS = re.compile(r"[\t\n\r\f\v\u0085\u2028\u2029]+")
_SPACES = re.compile(r" {2,}")


def one_line(value: object) -> str:
    """Colapsa todo separador de línea/control a un solo espacio.

    El Markdown generado se interpreta como estructura (encabezados/bullets
    por prefijo de línea); un valor con '\\n' embebido rompería esa estructura.
    """
    text = str(value or "")
    text = _LINE_BREAKS.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def normalize_markdown(markdown: str) -> str:
    """Limpia control chars/CR y colapsa espacios en cada línea.

    NO fusiona líneas inyectadas (en un string crudo no hay forma de
    distinguirlas de las legítimas): la defensa anti-inyección está en los
    productores, que pasan cada línea por :func:`one_line` antes de unirlas.
    Este paso es limpieza de entrada para el Doc, no el control principal.
    """
    return "\n".join(one_line(line) for line in markdown.splitlines())

# Website Search fallback — diseño corto

## Intención y por qué
Cuando Google Maps no trae web, el enriquecido y `update-new` quedan en `needs_manual` y hoy lo resuelves a mano con una búsqueda en Google. Esto automatiza ese paso con la opción A elegida.

## Tamaño
Cambio pequeño: un módulo nuevo + dos puntos de integración (enrich y new-places), sin tocar la extracción de la lista ni la carta.

## Metas
- Recuperar `place.website` cuando `_extract_website` / `discover_links` no lo traen.
- Que el flujo posterior (`_site_dishes`, adaptadores Fudo/Shopify/etc., fotos como respaldo) funcione igual que con web de Maps.
- Dejar constancia de origen (`website_source='search'`) en SQLite/JSONL para auditar.

## No metas
- Sin API paga (SerpAPI/Bing) ni navegador con Google Search.
- Sin cambiar `entitylist/getlist` ni el scraper de la lista.

## Anti-metas
- Una web equivocada es peor que ninguna: nada de aceptar por coincidencia débil ni de inventar la URL solo con el LLM.
- Si no hay match fuerte, seguir como hoy: `needs_manual`.

## Restricciones
- Solo stdlib (`urllib`) + `GEMINI_API_KEY` ya usada para visión; sin dependencias nuevas.
- Funcionar en GitHub Actions (sin navegador extra, bajo volumen).
- Rate limit suave y reintentos con backoff; degradar en silencio si el buscador bloquea.

## Enfoques
- **A) DuckDuckGo HTML + validación LLM (elegido):** query `"<nombre>" sin gluten <comuna/dirección>`, top 5, descarta sociales/agregadores, LLM comprueba nombre + dirección, solo acepta match fuerte. Sin costo, liviano, testeable con mocks.
- **B) API paga:** más confiable, pero exige clave/presupuesto. Descartado por costo.
- **C) LLM solo que adivina la URL:** alucina dominios. Descartado por riesgo.

## Decisiones (mías)
- Módulo nuevo `maps_gluten/website_search.py` con `search_website(name, address, llm) -> (url, score)`.
- Fallback en `enrich.py:enrich_places` solo si `website` es `None`; y en `update_new_places.py` tras `discover_links` si sigue vacío.
- `MAPS_WEBSITE_SEARCH=1` por defecto; si falta `GEMINI_API_KEY`, no se acepta nada (sin LLM no hay match).
- Query y prompt con nombre + comuna/tokens de dirección; umbral alto (nombre + al menos un token distintivo de dirección).

## Queda al builder
- Abstracción mínima de proveedor para poder cambiar DuckDuckGo por otro si bloquea.
- Backoff, timeouts y tests con fixtures HTML mockeadas.
- Actualizar README y `.env.example`.

---
**Estado:** pendiente de aprobación.

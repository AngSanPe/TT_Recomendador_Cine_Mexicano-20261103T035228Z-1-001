"""Extraccion de reseñas desde /film/<slug>/reviews/."""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, Iterator, List, Optional

from bs4 import BeautifulSoup, Tag

from .http import BASE, Cliente, ErrorDeDescarga

log = logging.getLogger(__name__)

# Letterboxd dibuja la calificacion como estrellas: "★★★½" equivale a 3.5.
_ESTRELLA, _MEDIA = "★", "½"

# El listado de reseñas se corta en la pagina 256 (la 257 llega vacia, medido en
# septiembre de 2026). Son 3,072 reseñas como maximo por pelicula, sin importar
# cuantas tenga en realidad.
TOPE_PAGINAS = 256
RESENAS_POR_PAGINA = 12


def calificacion_a_numero(texto: Optional[str]) -> Optional[float]:
    if not texto:
        return None
    texto = texto.strip()
    valor = texto.count(_ESTRELLA) + 0.5 * texto.count(_MEDIA)
    return valor or None


def _texto_reseña(cuerpo: Optional[Tag]) -> str:
    if cuerpo is None:
        return ""
    for basura in cuerpo.select(".contains-spoilers, .js-translation-disclaimer, script"):
        # El aviso "this review may contain spoilers" no es parte de la opinion.
        if "contains-spoilers" in (basura.get("class") or []) and basura.name in ("p", "div"):
            basura.decompose()
    parrafos = [p.get_text(" ", strip=True) for p in cuerpo.find_all("p")]
    if not parrafos:
        return cuerpo.get_text(" ", strip=True)
    return "\n\n".join(p for p in parrafos if p)


def _identificador(articulo: Tag) -> Optional[str]:
    nodo = articulo.select_one("[data-likeable-identifier]")
    if nodo:
        try:
            return json.loads(nodo["data-likeable-identifier"]).get("uid")
        except (json.JSONDecodeError, KeyError):
            pass
    enlace = articulo.select_one("a.context")
    return enlace["href"].strip("/") if enlace else None


def analizar_articulo(articulo: Tag, slug: str) -> Optional[Dict[str, object]]:
    enlace_usuario = articulo.select_one("a.avatar[href], a.context[href]")
    if enlace_usuario is None:
        return None
    usuario = enlace_usuario["href"].strip("/").split("/")[0]

    nombre = articulo.select_one(".displayname")
    titulo_rating = articulo.select_one("svg.glyph.-rating title, .rating")
    contexto = articulo.select_one("a.context[href]")
    tiempo = articulo.select_one("time[datetime]")
    cuerpo = articulo.select_one(".body-text")
    likes = articulo.select_one("[data-count]")

    texto = _texto_reseña(cuerpo)
    if not texto:
        return None  # es solo una calificacion, sin opinion escrita

    return {
        "id": _identificador(articulo),
        "pelicula_slug": slug,
        "usuario": usuario,
        "nombre_visible": nombre.get_text(strip=True) if nombre else usuario,
        "url": BASE + contexto["href"] if contexto else None,
        "calificacion": calificacion_a_numero(
            titulo_rating.get_text(strip=True) if titulo_rating else None
        ),
        "fecha": tiempo["datetime"] if tiempo else None,
        "texto": texto,
        "likes": int(likes["data-count"]) if likes and likes.get("data-count") else 0,
        "spoiler": 1 if articulo.select_one(".contains-spoilers") else 0,
        "idioma": (cuerpo.get("lang") if cuerpo else None),
        "es_relectura": 1 if articulo.select_one(".icon-rewatch") else 0,
    }


def analizar_pagina(html: str, slug: str) -> List[Dict[str, object]]:
    sopa = BeautifulSoup(html, "lxml")
    articulos = sopa.select("article.production-viewing, li.film-detail")
    reseñas = []
    for articulo in articulos:
        try:
            datos = analizar_articulo(articulo, slug)
        except Exception as e:  # una reseña rara no debe tumbar el scraping
            log.warning("No se pudo analizar una reseña de %s: %s", slug, e)
            continue
        if datos:
            reseñas.append(datos)
    return reseñas


def _hay_siguiente(html: str, pagina: int) -> bool:
    sopa = BeautifulSoup(html, "lxml")
    objetivo = "/page/%d/" % (pagina + 1)
    return any(objetivo in (a.get("href") or "") for a in sopa.select(".pagination a, a.next"))


def reseñas_de_pelicula(
    cliente: Cliente,
    slug: str,
    paginas_max: int = 5,
    usar_cache: bool = True,
) -> Iterator[Dict[str, object]]:
    """Recorre las paginas de reseñas de una pelicula.

    Se usa la ruta simple `/reviews/page/N/`: las variantes con orden
    (`/reviews/by/activity/`) estan prohibidas por el robots.txt del sitio.
    """
    for pagina in range(1, min(paginas_max, TOPE_PAGINAS) + 1):
        url = "/film/%s/reviews/page/%d/" % (slug, pagina)
        try:
            html = cliente.obtener(url, usar_cache=usar_cache)
        except ErrorDeDescarga as e:
            log.warning("Se detiene %s en la pagina %d: %s", slug, pagina, e)
            return

        encontradas = analizar_pagina(html, slug)
        log.info("%s pagina %d: %d reseñas", slug, pagina, len(encontradas))
        for reseña in encontradas:
            yield reseña

        if not encontradas or not _hay_siguiente(html, pagina):
            return

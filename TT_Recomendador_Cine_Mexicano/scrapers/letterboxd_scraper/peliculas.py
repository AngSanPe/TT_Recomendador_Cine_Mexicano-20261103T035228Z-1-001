"""Descubrimiento de peliculas mexicanas y lectura de sus metadatos."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from .http import BASE, Cliente, ErrorDeDescarga

log = logging.getLogger(__name__)


class CredencialInvalida(RuntimeError):
    pass


TMDB_API = "https://api.themoviedb.org/3"


def normalizar_slug(entrada: str) -> Optional[str]:
    """Acepta un slug, una URL de pelicula o una linea de archivo y devuelve el slug."""
    entrada = entrada.strip()
    if not entrada or entrada.startswith("#"):
        return None
    if entrada.startswith("http"):
        partes = [p for p in urlsplit(entrada).path.split("/") if p]
        if len(partes) >= 2 and partes[0] == "film":
            return partes[1]
        return None
    return entrada.strip("/").split("/")[-1]


def leer_archivo_de_peliculas(ruta: Path) -> List[str]:
    slugs = []
    for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
        slug = normalizar_slug(linea)
        if slug:
            slugs.append(slug)
    return slugs


def _json_ld(html: str) -> Optional[dict]:
    sopa = BeautifulSoup(html, "lxml")
    for etiqueta in sopa.find_all("script", {"type": "application/ld+json"}):
        crudo = etiqueta.string or ""
        crudo = crudo.replace("/* <![CDATA[ */", "").replace("/* ]]> */", "").strip()
        if not crudo:
            continue
        try:
            datos = json.loads(crudo)
        except json.JSONDecodeError:
            continue
        if isinstance(datos, dict) and datos.get("@type") == "Movie":
            return datos
    return None


def metadatos_pelicula(cliente: Cliente, slug: str) -> Dict[str, object]:
    """Lee titulo, año, director, paises y rating promedio de /film/<slug>/."""
    html = cliente.obtener("/film/%s/" % slug)
    datos = _json_ld(html) or {}
    sopa = BeautifulSoup(html, "lxml")

    anio = None
    fecha = datos.get("dateCreated") or ""
    evento = datos.get("releasedEvent") or []
    if isinstance(evento, list) and evento:
        fecha = str(evento[0].get("startDate") or fecha)
    m = re.search(r"\d{4}", str(fecha))
    if m:
        anio = int(m.group())

    tmdb_id = None
    enlace = sopa.select_one("a[href*='themoviedb.org/movie/']")
    if enlace:
        m = re.search(r"/movie/(\d+)", enlace["href"])
        if m:
            tmdb_id = int(m.group(1))

    calificacion = (datos.get("aggregateRating") or {}).get("ratingValue")

    return {
        "slug": slug,
        "titulo": datos.get("name") or slug,
        "anio": anio,
        "directores": ", ".join(
            d.get("name", "") for d in (datos.get("director") or []) if isinstance(d, dict)
        ),
        "paises": ", ".join(
            c.get("name", "") for c in (datos.get("countryOfOrigin") or []) if isinstance(c, dict)
        ),
        "tmdb_id": tmdb_id,
        "calificacion_promedio": float(calificacion) if calificacion is not None else None,
        "url": "%s/film/%s/" % (BASE, slug),
    }


def slug_desde_tmdb(cliente: Cliente, tmdb_id: int) -> Optional[str]:
    """Letterboxd redirige /tmdb/<id>/ a la ficha de la pelicula."""
    try:
        final = cliente.url_final("/tmdb/%s/" % tmdb_id)
    except ErrorDeDescarga as e:
        log.info("TMDb %s sin equivalente en Letterboxd (%s)", tmdb_id, e)
        return None
    partes = [p for p in urlsplit(final).path.split("/") if p]
    if len(partes) >= 2 and partes[0] == "film":
        return partes[1]
    return None


def _peticion_tmdb(api_key: str, ruta: str, parametros: Dict[str, object]) -> dict:
    """Llama a TMDb aceptando las dos formas de credencial que reparte el sitio.

    La clave v3 son 32 caracteres y viaja como parametro `api_key`; el token de
    lectura v4 es un JWT largo y viaja como encabezado Authorization.
    """
    parametros = dict(parametros)
    encabezados = {"accept": "application/json"}
    if api_key.count(".") == 2 or len(api_key) > 64:
        encabezados["Authorization"] = "Bearer " + api_key
    else:
        parametros["api_key"] = api_key

    for intento in range(3):
        r = requests.get(TMDB_API + ruta, params=parametros,
                         headers=encabezados, timeout=30)
        if r.status_code == 429:  # TMDb pide bajar el ritmo
            time.sleep(float(r.headers.get("Retry-After", 2)) + 1)
            continue
        if r.status_code == 401:
            raise CredencialInvalida(
                "TMDb rechazo la credencial (401). Revisa que sea la API Key (v3) "
                "o el Read Access Token (v4) de themoviedb.org/settings/api"
            )
        r.raise_for_status()
        return r.json()
    raise RuntimeError("TMDb sigue respondiendo 429 tras 3 intentos")


def _pagina_tmdb(api_key: str, parametros: Dict[str, object]) -> dict:
    return _peticion_tmdb(api_key, "/discover/movie", parametros)


def paises_de_produccion(api_key: str, tmdb_id: int) -> List[str]:
    """Paises de produccion reales segun la ficha de TMDb, en codigo ISO."""
    detalle = _peticion_tmdb(api_key, "/movie/%d" % tmdb_id, {})
    return [p.get("iso_3166_1") for p in detalle.get("production_countries") or []]


def es_produccion_exclusivamente_mx(api_key: str, tmdb_id: int) -> bool:
    """True si Mexico es el UNICO pais de produccion (descarta coproducciones)."""
    return paises_de_produccion(api_key, tmdb_id) == ["MX"]


# ---- sinopsis ---------------------------------------------------------------

def sinopsis_letterboxd(html: str) -> Optional[str]:
    """Sinopsis (en ingles) tal como la muestra la ficha /film/<slug>/."""
    sopa = BeautifulSoup(html, "lxml")
    nodo = (sopa.select_one("section.production-synopsis .truncate")
            or sopa.select_one("div.review.body-text .truncate"))
    if nodo is None:
        return None
    parrafos = [p.get_text(" ", strip=True) for p in nodo.find_all("p")]
    if not parrafos:
        parrafos = [nodo.get_text(" ", strip=True)]
    return "\n\n".join(p for p in parrafos if p) or None


def textos_tmdb(api_key: str, tmdb_id: int) -> Dict[str, Optional[str]]:
    """Titulo y sinopsis en español e ingles desde TMDb, en una sola peticion.

    Si falta la traduccion pedida, TMDb deja la sinopsis vacia en lugar de usar
    otro idioma. Por eso se piden todas las traducciones y se elige aqui:
    primero es-MX, luego es-ES y al final cualquier otra variante de español.
    """
    detalle = _peticion_tmdb(api_key, "/movie/%d" % tmdb_id,
                             {"language": "es-MX", "append_to_response": "translations"})
    return elegir_textos(detalle)


def elegir_textos(detalle: dict) -> Dict[str, Optional[str]]:
    """Elige titulo y sinopsis de una ficha de TMDb pedida con
    language=es-MX y append_to_response=translations.

    Si no hay ni español ni ingles, `sinopsis_otra` guarda la del idioma
    original de la pelicula (o la primera que exista).
    """
    traducciones = (detalle.get("translations") or {}).get("translations") or []

    def sinopsis(idioma: str, preferidas: List[str]) -> tuple:
        por_region = {
            t.get("iso_3166_1"): ((t.get("data") or {}).get("overview") or "").strip()
            for t in traducciones if t.get("iso_639_1") == idioma
        }
        orden = preferidas + sorted(r for r in por_region if r not in preferidas)
        for region in orden:
            if por_region.get(region):
                return por_region[region], "tmdb %s-%s" % (idioma, region)
        return None, None

    es, fuente_es = sinopsis("es", ["MX", "ES"])
    en, fuente_en = sinopsis("en", ["US", "GB"])

    otra, fuente_otra = None, None
    if not es and not en:
        original = detalle.get("original_language")
        idiomas = sorted({t.get("iso_639_1") for t in traducciones if t.get("iso_639_1")},
                         key=lambda i: (i != original, i))
        for idioma in idiomas:
            otra, fuente_otra = sinopsis(idioma, [])
            if otra:
                break

    return {
        # Con language=es-MX, TMDb cae al titulo original si no hay traduccion.
        "titulo_es": detalle.get("title") or detalle.get("original_title"),
        "sinopsis_es": es,
        "sinopsis_es_fuente": fuente_es,
        "sinopsis_en": en,
        "sinopsis_en_fuente": fuente_en,
        "sinopsis_otra": otra,
        "sinopsis_otra_fuente": fuente_otra,
    }


def verificar_credencial(api_key: str) -> dict:
    """Comprueba la credencial y devuelve cuantas peliculas mexicanas ve TMDb."""
    cuerpo = _pagina_tmdb(api_key, {"with_origin_country": "MX", "page": 1})
    return {
        "valida": True,
        "peliculas_mx": cuerpo.get("total_results", 0),
        "paginas": cuerpo.get("total_pages", 0),
    }


def _normalizar_resultado(p: dict) -> Dict[str, object]:
    return {
        "tmdb_id": p["id"],
        "titulo": p.get("title") or p.get("original_title"),
        "anio": int((p.get("release_date") or "0000")[:4]) or None,
        "popularidad": p.get("popularity"),
        "votos": p.get("vote_count") or 0,
    }


def descubrir_en_tmdb(
    api_key: str,
    paginas: int = 5,
    desde_anio: Optional[int] = None,
    hasta_anio: Optional[int] = None,
    pais: str = "MX",
    orden: str = "popularity.desc",
) -> List[Dict[str, object]]:
    """Lista peliculas de origen mexicano con la API oficial de TMDb.

    Se usa TMDb para el descubrimiento porque el robots.txt de Letterboxd
    prohibe explicitamente sus listados por pais (`/*/country/*`).
    """
    resultados: List[Dict[str, object]] = []
    for pagina in range(1, paginas + 1):
        parametros: Dict[str, object] = {
            "with_origin_country": pais,
            "sort_by": orden,
            "page": pagina,
            "include_adult": "false",
        }
        if desde_anio:
            parametros["primary_release_date.gte"] = "%d-01-01" % desde_anio
        if hasta_anio:
            parametros["primary_release_date.lte"] = "%d-12-31" % hasta_anio

        cuerpo = _pagina_tmdb(api_key, parametros)
        resultados.extend(_normalizar_resultado(p) for p in cuerpo.get("results", []))
        if pagina >= cuerpo.get("total_pages", 1):
            break
        time.sleep(0.3)
    return resultados


def catalogo_completo_mx(
    api_key: str,
    desde_anio: int = 1930,
    hasta_anio: Optional[int] = None,
    pais: str = "MX",
    estricto: bool = False,
) -> Iterator[Dict[str, object]]:
    """Recorre TODO el catalogo de cine de origen mexicano, año por año.

    TMDb corta cada consulta en 500 paginas (10 mil resultados), asi que la
    particion anual es lo que permite barrer el catalogo entero sin toparse
    con ese limite.
    """
    hasta_anio = hasta_anio or datetime.now().year
    for anio in range(desde_anio, hasta_anio + 1):
        pagina = 1
        while True:
            cuerpo = _pagina_tmdb(
                api_key,
                {
                    "with_origin_country": pais,
                    "primary_release_year": anio,
                    "sort_by": "vote_count.desc",
                    "page": pagina,
                    "include_adult": "false",
                },
            )
            resultados = cuerpo.get("results", [])
            if not resultados:
                break
            for p in resultados:
                if estricto and not es_produccion_exclusivamente_mx(api_key, p["id"]):
                    continue
                yield _normalizar_resultado(p)
            total = min(int(cuerpo.get("total_pages", 1)), 500)
            log.info("TMDb %d: pagina %d/%d (%d titulos en el año)",
                     anio, pagina, total, cuerpo.get("total_results", 0))
            if pagina >= total:
                break
            pagina += 1
            time.sleep(0.25)


def slugs_de_lista_letterboxd(cliente: Cliente, url: str, paginas_max: int = 500) -> List[str]:
    """Extrae los slugs de una lista publica de Letterboxd (/usuario/list/...).

    Son 100 peliculas por pagina. La ventaja sobre cualquier otra fuente es que
    los slugs vienen del propio sitio: no hay que adivinarlos ni verificarlos.
    """
    slugs: List[str] = []
    vistos = set()
    ruta = urlsplit(url).path.rstrip("/") or url.rstrip("/")
    for pagina in range(1, paginas_max + 1):
        # La diagonal final importa: sin ella Letterboxd responde 403.
        destino = ruta + "/" if pagina == 1 else "%s/page/%d/" % (ruta, pagina)
        try:
            html = cliente.obtener(destino)
        except ErrorDeDescarga as e:
            log.warning("Lista %s cortada en la pagina %d: %s", ruta, pagina, e)
            break
        sopa = BeautifulSoup(html, "lxml")
        encontrados = [s for s in _slugs_en_html(sopa) if s not in vistos]
        if not encontrados:
            break
        vistos.update(encontrados)
        slugs.extend(encontrados)
        log.info("Lista %s pagina %d: %d peliculas (%d acumuladas)",
                 ruta, pagina, len(encontrados), len(slugs))
        siguiente = "/page/%d/" % (pagina + 1)
        if not any(siguiente in (a.get("href") or "") for a in sopa.find_all("a", href=True)):
            break
    return slugs


def _slugs_en_html(sopa: BeautifulSoup) -> List[str]:
    vistos: List[str] = []
    for nodo in sopa.select("[data-film-slug], [data-item-slug], a[href^='/film/']"):
        slug = nodo.get("data-film-slug") or nodo.get("data-item-slug")
        if not slug and nodo.name == "a":
            slug = normalizar_slug(BASE + nodo["href"])
        if slug and slug not in vistos:
            vistos.append(slug)
    return vistos


def resolver_slugs(cliente: Cliente, peliculas: Iterable[Dict[str, object]]) -> List[str]:
    """Convierte resultados de TMDb en slugs de Letterboxd."""
    slugs = []
    for p in peliculas:
        slug = slug_desde_tmdb(cliente, int(p["tmdb_id"]))
        if slug:
            log.info("TMDb %s (%s) -> %s", p["tmdb_id"], p.get("titulo"), slug)
            slugs.append(slug)
        else:
            log.info("Sin ficha en Letterboxd: %s", p.get("titulo"))
    return slugs

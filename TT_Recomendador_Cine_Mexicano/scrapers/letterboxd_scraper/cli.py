"""Interfaz de linea de comandos del scraper."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path
from typing import List

from .almacen import Almacen
from .http import BloqueadoPorRobots, Cliente, ErrorDeDescarga
from .peliculas import (
    CredencialInvalida,
    catalogo_completo_mx,
    paises_de_produccion,
    descubrir_en_tmdb,
    leer_archivo_de_peliculas,
    metadatos_pelicula,
    normalizar_slug,
    resolver_slugs,
    slug_desde_tmdb,
    sinopsis_letterboxd,
    slugs_de_lista_letterboxd,
    textos_tmdb,
)
from .resenas import TOPE_PAGINAS, reseñas_de_pelicula

BD_POR_DEFECTO = Path("datos/letterboxd.db")
SEMILLA = Path(__file__).resolve().parent.parent / "peliculas_mexicanas.txt"


def _configurar_log(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _cliente(args) -> Cliente:
    cliente = Cliente(
        retardo=args.retardo,
        cache=Path(args.cache) if getattr(args, "cache", None) else None,
        respetar_robots=not getattr(args, "sin_robots", False),
    )
    if getattr(args, "sin_robots", False):
        logging.warning("robots.txt desactivado por --sin-robots: usalo bajo tu responsabilidad")
    return cliente


ARCHIVO_ENV = Path(".env")


def _clave_tmdb() -> str:
    """Lee la credencial de TMDb del entorno o del archivo .env local.

    Se prefiere el archivo a escribir la clave en la linea de comandos: asi no
    queda registrada en el historial de la terminal.
    """
    clave = os.environ.get("TMDB_API_KEY", "")

    if not clave and ARCHIVO_ENV.exists():
        for linea in ARCHIVO_ENV.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea.startswith("#") or "=" not in linea:
                continue
            nombre, _, valor = linea.partition("=")
            if nombre.strip() == "TMDB_API_KEY":
                clave = valor.strip().strip('"').strip("'")
                break

    if not clave:
        sys.exit(
            "Falta la credencial de TMDb.\n"
            "1. Entra a https://www.themoviedb.org/settings/api\n"
            "2. Copia tu 'API Key (v3)' o tu 'API Read Access Token (v4)'\n"
            "3. Pegala en el archivo .env de este proyecto:\n"
            "     TMDB_API_KEY=tu_clave_aqui\n"
            "   (el .env ya esta en .gitignore, no se sube a ningun lado)\n"
            "Luego verifica con: .venv/bin/python tmdb.py"
        )
    return clave


# --------------------------------------------------------------------------
# catalogo: descubre en TMDb todas las peliculas de origen mexicano
# --------------------------------------------------------------------------

def comando_catalogo(args) -> int:
    clave = _clave_tmdb()
    nuevas = lote = 0
    with Almacen(Path(args.bd)) as almacen:
        acumulado: List[dict] = []
        for pelicula in catalogo_completo_mx(
            clave, args.desde_anio, args.hasta_anio, estricto=args.estricto
        ):
            acumulado.append(pelicula)
            if len(acumulado) >= 200:
                nuevas += almacen.guardar_candidatos(acumulado)
                lote += len(acumulado)
                acumulado = []
        nuevas += almacen.guardar_candidatos(acumulado)
        lote += len(acumulado)
        conteo = almacen.conteo_catalogo()
        logging.info("TMDb devolvio %d titulos; %d nuevos en el catalogo", lote, nuevas)
        logging.info("Catalogo: %s", conteo)
    return 0


# --------------------------------------------------------------------------
# depurar: confirma que la pelicula sea realmente mexicana
# --------------------------------------------------------------------------

def comando_depurar(args) -> int:
    """Anota los paises de produccion reales y descarta lo que no es mexicano.

    El filtro `with_origin_country=MX` de TMDb es ruidoso: mete peliculas
    estadounidenses rodadas en Mexico e incluso titulos sin relacion alguna.
    La ficha individual si trae los paises de produccion correctos.
    """
    clave = _clave_tmdb()
    aceptadas = descartadas = sin_dato = 0
    with Almacen(Path(args.bd)) as almacen:
        pendientes = almacen.candidatos_sin_paises(args.min_votos, args.limite)
        logging.info("Por depurar: %d peliculas (votos >= %d, modo %s)",
                     len(pendientes), args.min_votos, args.modo)
        for i, fila in enumerate(pendientes, 1):
            try:
                paises = paises_de_produccion(clave, fila["tmdb_id"])
            except Exception as e:
                logging.warning("No se pudo consultar %s: %s", fila["titulo"], e)
                continue

            texto = ",".join(paises)

            if not paises:
                # TMDb no siempre llena production_countries, sobre todo en cine
                # reciente y pequeño. Descartarlas seria perder peliculas
                # mexicanas por un hueco de metadatos, no por su origen: la
                # consulta que las trajo ya filtraba por pais de origen MX.
                almacen.actualizar_candidato(fila["tmdb_id"], "pendiente", paises="?")
                sin_dato += 1
                continue

            pasa = paises == ["MX"] if args.modo == "solo-mx" else "MX" in paises
            if pasa:
                almacen.actualizar_candidato(fila["tmdb_id"], "pendiente", paises=texto)
                aceptadas += 1
            else:
                almacen.actualizar_candidato(fila["tmdb_id"], "descartada", paises=texto)
                descartadas += 1
                logging.debug("Fuera: %s (%s)", fila["titulo"], texto or "sin dato")

            if i % 200 == 0:
                logging.info("[%d/%d] aceptadas=%d descartadas=%d",
                             i, len(pendientes), aceptadas, descartadas)
        logging.info("Listo. Aceptadas: %d. Descartadas: %d. Sin dato de pais: %d "
                     "(se conservan, marcadas con '?').",
                     aceptadas, descartadas, sin_dato)
        logging.info("Catalogo: %s", almacen.conteo_catalogo())
    return 0


# --------------------------------------------------------------------------
# resolver: traduce tmdb_id -> slug de Letterboxd (una peticion por pelicula)
# --------------------------------------------------------------------------

def comando_resolver(args) -> int:
    cliente = _cliente(args)
    resueltos = sin_ficha = 0
    with Almacen(Path(args.bd)) as almacen:
        pendientes = almacen.candidatos("pendiente", args.limite, args.min_votos)
        logging.info("Por resolver: %d peliculas (votos >= %d)", len(pendientes), args.min_votos)
        for i, fila in enumerate(pendientes, 1):
            try:
                slug = slug_desde_tmdb(cliente, fila["tmdb_id"])
            except BloqueadoPorRobots as e:
                logging.error("%s", e)
                break
            except Exception as e:
                # Una corrida de horas no puede caerse por un titulo raro.
                logging.warning("Se omite %s (%s): %s", fila["titulo"], fila["tmdb_id"], e)
                continue
            if slug:
                almacen.actualizar_candidato(fila["tmdb_id"], "resuelto", slug)
                resueltos += 1
            else:
                almacen.actualizar_candidato(fila["tmdb_id"], "sin_ficha")
                sin_ficha += 1
            if i % 25 == 0:
                logging.info("[%d/%d] resueltos=%d sin_ficha=%d",
                             i, len(pendientes), resueltos, sin_ficha)
        logging.info("Listo. Resueltos: %d. Sin ficha en Letterboxd: %d", resueltos, sin_ficha)
        logging.info("Catalogo: %s", almacen.conteo_catalogo())
    return 0


# --------------------------------------------------------------------------
# recolectar
# --------------------------------------------------------------------------

def _reunir_slugs(args, cliente: Cliente, almacen: Almacen) -> List[str]:
    slugs: List[str] = []

    if args.del_catalogo:
        filas = almacen.candidatos("resuelto", args.limite, args.min_votos)
        if not filas:
            logging.warning(
                "El catalogo no tiene peliculas resueltas. Corre primero: "
                "`catalogo` y luego `resolver`."
            )
        return [f["slug"] for f in filas]

    for s in args.slug or []:
        slug = normalizar_slug(s)
        if slug:
            slugs.append(slug)

    if args.peliculas:
        slugs.extend(leer_archivo_de_peliculas(Path(args.peliculas)))

    if args.lista:
        slugs.extend(slugs_de_lista_letterboxd(cliente, args.lista))

    if args.tmdb:
        encontradas = descubrir_en_tmdb(
            _clave_tmdb(),
            paginas=args.paginas_tmdb,
            desde_anio=args.desde_anio,
            hasta_anio=args.hasta_anio,
        )
        logging.info("TMDb devolvio %d peliculas mexicanas", len(encontradas))
        slugs.extend(resolver_slugs(cliente, encontradas))

    if not slugs:
        logging.info("Sin fuente indicada: se usa la lista semilla %s", SEMILLA.name)
        slugs.extend(leer_archivo_de_peliculas(SEMILLA))

    unicos: List[str] = []
    for s in slugs:
        if s not in unicos:
            unicos.append(s)
    return unicos[: args.limite] if args.limite else unicos


def comando_recolectar(args) -> int:
    if args.paginas > TOPE_PAGINAS:
        logging.warning(
            "Letterboxd corta el listado en %d paginas (%d reseñas por pelicula); "
            "se usara ese tope en vez de %d",
            TOPE_PAGINAS, TOPE_PAGINAS * 12, args.paginas,
        )
        args.paginas = TOPE_PAGINAS

    cliente = _cliente(args)
    nuevas = 0
    with Almacen(Path(args.bd)) as almacen:
        slugs = _reunir_slugs(args, cliente, almacen)
        logging.info("Peliculas por procesar: %d", len(slugs))

        for i, slug in enumerate(slugs, 1):
            logging.info("[%d/%d] %s", i, len(slugs), slug)
            try:
                pelicula = metadatos_pelicula(cliente, slug)
            except BloqueadoPorRobots as e:
                logging.error("%s", e)
                continue
            except ErrorDeDescarga as e:
                logging.warning("Se omite %s: %s", slug, e)
                continue

            if args.solo_mexicanas and "mexico" not in str(pelicula["paises"]).lower():
                logging.info("Se salta %s: paises = %s",
                             pelicula["titulo"], pelicula["paises"] or "(sin dato)")
                almacen.guardar_pelicula(pelicula)
                continue

            almacen.guardar_pelicula(pelicula)
            lote = list(
                reseñas_de_pelicula(
                    cliente, slug, paginas_max=args.paginas, usar_cache=not args.sin_cache
                )
            )
            guardadas = almacen.guardar_resenas(lote)
            nuevas += guardadas
            if pelicula.get("tmdb_id"):
                almacen.actualizar_candidato(int(pelicula["tmdb_id"]), "recolectado", slug)
            logging.info(
                "%s (%s): %d reseñas leidas, %d nuevas | acumulado: %d",
                pelicula["titulo"], pelicula["anio"], len(lote), guardadas,
                almacen.total_resenas(),
            )

        logging.info("Listo. Reseñas nuevas: %d. Total en la base: %d",
                     nuevas, almacen.total_resenas())
    return 0


# --------------------------------------------------------------------------
# sinopsis: español de TMDb, ingles de la ficha de Letterboxd
# --------------------------------------------------------------------------

def comando_sinopsis(args) -> int:
    """Guarda la sinopsis de cada pelicula ya registrada en la tabla `peliculas`.

    El español sale de TMDb (es-MX, si no es-ES). El ingles sale de la ficha de
    Letterboxd, que ya esta en la cache desde la recoleccion, asi que casi
    nunca cuesta peticiones al sitio; si falta, se usa el ingles de TMDb.
    """
    clave = _clave_tmdb()
    cliente = _cliente(args)
    with Almacen(Path(args.bd)) as almacen:
        filas = almacen.peliculas_para_sinopsis(args.todas, args.limite)
        logging.info("Peliculas por revisar: %d", len(filas))
        for i, fila in enumerate(filas, 1):
            datos = {}
            if fila["tmdb_id"]:
                try:
                    datos = textos_tmdb(clave, int(fila["tmdb_id"]))
                except CredencialInvalida:
                    raise
                except Exception as e:
                    # Sin marcarla como revisada: la siguiente corrida la reintenta.
                    logging.warning("TMDb fallo con %s (%s): %s",
                                    fila["titulo"], fila["tmdb_id"], e)
                    continue

            try:
                en_letterboxd = sinopsis_letterboxd(cliente.obtener("/film/%s/" % fila["slug"]))
            except ErrorDeDescarga as e:
                logging.warning("Sin ficha de Letterboxd para %s: %s", fila["slug"], e)
                en_letterboxd = None
            if en_letterboxd:
                datos["sinopsis_en"] = en_letterboxd
                datos["sinopsis_en_fuente"] = "letterboxd"

            almacen.guardar_sinopsis(fila["slug"], datos)
            if not datos.get("sinopsis_es"):
                logging.debug("Sin sinopsis en español: %s", fila["titulo"])
            if i % 100 == 0:
                logging.info("[%d/%d] %s", i, len(filas), almacen.conteo_sinopsis())

        logging.info("Listo. %s", almacen.conteo_sinopsis())
        if args.csv:
            n = almacen.exportar_sinopsis_csv(Path(args.csv))
            logging.info("CSV: %s (%d peliculas)", args.csv, n)
    return 0


# --------------------------------------------------------------------------
# sinopsis-imdb: sinopsis de TMDb para cada pelicula de un CSV de IMDb
# --------------------------------------------------------------------------

def comando_sinopsis_imdb(args) -> int:
    """Consulta TMDb por el id de IMDb (tconst) de cada pelicula del CSV.

    Va de la mas votada en IMDb a la menos y es reanudable: lo consultado
    queda en --base y la siguiente corrida solo pide lo que falta.
    """
    from . import imdb

    if not args.solo_exportar:
        # `kill <pid>` detiene igual que Ctrl+C: el lote en curso se descarta
        # y la siguiente corrida lo vuelve a pedir.
        signal.signal(signal.SIGTERM, signal.default_int_handler)
        try:
            conteo = imdb.recolectar(_clave_tmdb(), Path(args.archivo), Path(args.base),
                                     hilos=args.hilos, por_segundo=args.por_segundo,
                                     limite=args.limite, min_votos=args.min_votos)
            logging.info("Listo. %s", conteo)
        except KeyboardInterrupt:
            logging.info("Interrumpido; lo consultado ya esta guardado en %s", args.base)
    if args.csv:
        n = imdb.exportar_csv(Path(args.archivo), Path(args.base), Path(args.csv),
                              solo_con_sinopsis=args.solo_con_sinopsis)
        logging.info("CSV: %s (%s peliculas)", args.csv, f"{n:,}")
    return 0


# --------------------------------------------------------------------------
# exportar / resumen
# --------------------------------------------------------------------------

def comando_exportar(args) -> int:
    with Almacen(Path(args.bd)) as almacen:
        if args.csv:
            print("CSV:", args.csv, almacen.exportar_csv(Path(args.csv), args.idioma), "filas")
        if args.jsonl:
            print("JSONL:", args.jsonl, almacen.exportar_jsonl(Path(args.jsonl), args.idioma), "filas")
        if not args.csv and not args.jsonl:
            return comando_resumen(args)
    return 0


def comando_resumen(args) -> int:
    with Almacen(Path(args.bd)) as almacen:
        filas = almacen.resumen()
        print("%-40s %6s %8s %8s" % ("PELICULA", "AÑO", "RESEÑAS", "CALIF."))
        for f in filas[:40]:
            print("%-40.40s %6s %8d %8s" % (
                f["titulo"], f["anio"] or "?", f["resenas"], f["calificacion_media"] or "-"))
        if len(filas) > 40:
            print("... y %d peliculas mas" % (len(filas) - 40))
        print("\nTotal de reseñas: %d en %d peliculas" % (almacen.total_resenas(), len(filas)))
        print("Por idioma:", almacen.conteo_idiomas(8))
        catalogo = almacen.conteo_catalogo()
        if catalogo:
            print("Catalogo TMDb:", catalogo)
    return 0


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="letterboxd-mx",
        description="Recolecta reseñas de peliculas mexicanas publicadas en Letterboxd.",
    )
    p.add_argument("--bd", default=str(BD_POR_DEFECTO), help="ruta de la base SQLite")
    p.add_argument("-v", "--verboso", action="store_true")
    sub = p.add_subparsers(dest="comando", required=True)

    def opciones_red(sp):
        sp.add_argument("--retardo", type=float, default=2.5, help="segundos entre peticiones")
        sp.add_argument("--cache", default="datos/cache", help="carpeta de cache HTML")
        sp.add_argument("--sin-robots", action="store_true", help="no consultar robots.txt")

    c = sub.add_parser("catalogo", help="descubre en TMDb todo el cine de origen mexicano")
    c.add_argument("--desde-anio", type=int, default=1930)
    c.add_argument("--hasta-anio", type=int)
    c.add_argument("--estricto", action="store_true",
                   help="solo peliculas donde Mexico es el UNICO pais de produccion "
                        "(descarta coproducciones; cuesta una peticion extra por titulo)")
    c.set_defaults(func=comando_catalogo)

    d = sub.add_parser("depurar",
                       help="confirma con TMDb que cada pelicula sea realmente mexicana")
    d.add_argument("--modo", choices=["con-mx", "solo-mx"], default="con-mx",
                   help="con-mx: Mexico entre los paises de produccion (incluye "
                        "coproducciones). solo-mx: Mexico como unico pais.")
    d.add_argument("--min-votos", type=int, default=5)
    d.add_argument("--limite", type=int)
    d.set_defaults(func=comando_depurar)

    s = sub.add_parser("resolver", help="traduce los ids de TMDb a slugs de Letterboxd")
    s.add_argument("--limite", type=int, help="maximo de peliculas por corrida")
    s.add_argument("--min-votos", type=int, default=5,
                   help="ignora peliculas con menos votos en TMDb (casi sin publico)")
    opciones_red(s)
    s.set_defaults(func=comando_resolver)

    r = sub.add_parser("recolectar", help="descarga fichas y reseñas")
    r.add_argument("--del-catalogo", action="store_true",
                   help="usa las peliculas ya resueltas del catalogo, de mas a menos votadas")
    r.add_argument("--slug", action="append", help="slug o URL de pelicula (repetible)")
    r.add_argument("--peliculas", help="archivo de texto con un slug o URL por linea")
    r.add_argument("--lista", help="URL de una lista publica de Letterboxd")
    r.add_argument("--tmdb", action="store_true", help="descubrir con la API de TMDb (MX)")
    r.add_argument("--paginas-tmdb", type=int, default=3)
    r.add_argument("--desde-anio", type=int)
    r.add_argument("--hasta-anio", type=int)
    r.add_argument("--paginas", type=int, default=5,
                   help="paginas de reseñas por pelicula (12 c/u, tope %d)" % TOPE_PAGINAS)
    r.add_argument("--limite", type=int, help="maximo de peliculas a procesar")
    r.add_argument("--min-votos", type=int, default=5, help="con --del-catalogo: votos minimos")
    r.add_argument("--solo-mexicanas", action="store_true",
                   help="omite las peliculas que Letterboxd no marca como de Mexico "
                        "(util con listas comunitarias; ojo: ese dato tiene errores)")
    r.add_argument("--sin-cache", action="store_true", help="ignora la cache al leer")
    opciones_red(r)
    r.set_defaults(func=comando_recolectar)

    so = sub.add_parser("sinopsis",
                        help="guarda la sinopsis (español e ingles) de las peliculas registradas")
    so.add_argument("--csv", default="datos/sinopsis_peliculas.csv",
                    help="ademas exporta las sinopsis a este CSV ('' para no exportar)")
    so.add_argument("--todas", action="store_true",
                    help="vuelve a consultar tambien las que ya tienen sinopsis")
    so.add_argument("--limite", type=int, help="maximo de peliculas por corrida")
    opciones_red(so)
    so.set_defaults(func=comando_sinopsis)

    si = sub.add_parser("sinopsis-imdb",
                        help="sinopsis de TMDb para cada pelicula de un CSV de IMDb (tconst)")
    si.add_argument("--archivo", default="imdb_movies.csv",
                    help="CSV con columnas tconst, primaryTitle, numVotes...")
    si.add_argument("--base", default="datos/sinopsis_imdb.db",
                    help="base SQLite donde se va guardando lo consultado")
    si.add_argument("--csv", default="datos/sinopsis_imdb.csv",
                    help="exporta al terminar ('' para no exportar)")
    si.add_argument("--solo-con-sinopsis", action="store_true",
                    help="el CSV omite las peliculas sin sinopsis o aun no consultadas")
    si.add_argument("--solo-exportar", action="store_true",
                    help="no consulta TMDb, solo regenera el CSV con lo que hay")
    si.add_argument("--hilos", type=int, default=16,
                    help="peticiones simultaneas (TMDb admite hasta 20 por IP)")
    si.add_argument("--por-segundo", type=float, default=40,
                    help="tope de peticiones por segundo (TMDb corta cerca de 50)")
    si.add_argument("--min-votos", type=int, default=0,
                    help="ignora las peliculas con menos votos en IMDb")
    si.add_argument("--limite", type=int, help="maximo de peliculas por corrida")
    si.set_defaults(func=comando_sinopsis_imdb)

    e = sub.add_parser("exportar", help="exporta a CSV o JSONL")
    e.add_argument("--csv")
    e.add_argument("--jsonl")
    e.add_argument("--idioma", help="filtra por idioma de la reseña, p. ej. es")
    e.set_defaults(func=comando_exportar)

    rs = sub.add_parser("resumen", help="muestra el conteo por pelicula")
    rs.set_defaults(func=comando_resumen)
    return p


def main(argv=None) -> int:
    args = construir_parser().parse_args(argv)
    _configurar_log(args.verboso)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        logging.info("Interrumpido; lo recolectado ya esta guardado en %s", args.bd)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

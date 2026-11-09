"""Sinopsis de TMDb para las peliculas de un volcado de IMDb (imdb_movies.csv).

TMDb acepta el id de IMDb (tt...) directamente en /movie/<id>, asi que basta
una peticion por pelicula: no hay que buscar por titulo ni adivinar nada.

Lo consultado se guarda en una base SQLite propia. La recoleccion es
reanudable: al volver a correrla solo pide las peliculas que faltan.
"""

from __future__ import annotations

import csv
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests

from .peliculas import TMDB_API, CredencialInvalida, elegir_textos

log = logging.getLogger(__name__)

CAMPOS = [
    "tmdb_id", "titulo_es",
    "sinopsis_es", "sinopsis_es_fuente",
    "sinopsis_en", "sinopsis_en_fuente",
    "sinopsis_otra", "sinopsis_otra_fuente",
]

COLUMNAS_CSV = (["tconst", "titulo", "titulo_original", "anio", "generos",
                 "votos_imdb", "estado"] + CAMPOS)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sinopsis_imdb (
    tconst               TEXT PRIMARY KEY,
    estado               TEXT NOT NULL,  -- con_sinopsis | sin_sinopsis | no_en_tmdb
    tmdb_id              INTEGER,
    titulo_es            TEXT,
    sinopsis_es          TEXT,
    sinopsis_es_fuente   TEXT,
    sinopsis_en          TEXT,
    sinopsis_en_fuente   TEXT,
    sinopsis_otra        TEXT,
    sinopsis_otra_fuente TEXT,
    consultado_en        TEXT NOT NULL
);
"""

# Peliculas que se guardan juntas. Al interrumpir se pierde a lo mucho un lote.
LOTE = 500


class ErrorTMDb(RuntimeError):
    pass


class LimiteDeRitmo:
    """Reparte las peticiones de todos los hilos a un maximo por segundo."""

    def __init__(self, por_segundo: float):
        self.intervalo = 1.0 / por_segundo
        self.siguiente = time.monotonic()
        self.candado = threading.Lock()

    def esperar(self) -> None:
        with self.candado:
            turno = max(self.siguiente, time.monotonic())
            self.siguiente = turno + self.intervalo
        pendiente = turno - time.monotonic()
        if pendiente > 0:
            time.sleep(pendiente)

    def frenar(self, segundos: float) -> None:
        """Detiene a todos los hilos (TMDb respondio 429)."""
        with self.candado:
            self.siguiente = max(self.siguiente, time.monotonic() + segundos)


class ClienteTMDb:
    """Cliente concurrente: una sesion por hilo y un ritmo compartido."""

    def __init__(self, api_key: str, por_segundo: float = 40.0, reintentos: int = 5):
        self.ritmo = LimiteDeRitmo(por_segundo)
        self.reintentos = reintentos
        self.local = threading.local()
        self.parametros: Dict[str, str] = {
            "language": "es-MX", "append_to_response": "translations"}
        self.encabezados = {"accept": "application/json"}
        # Igual que _peticion_tmdb: el token v4 es un JWT, la clave v3 no.
        if api_key.count(".") == 2 or len(api_key) > 64:
            self.encabezados["Authorization"] = "Bearer " + api_key
        else:
            self.parametros["api_key"] = api_key

    def _sesion(self) -> requests.Session:
        sesion = getattr(self.local, "sesion", None)
        if sesion is None:
            sesion = requests.Session()
            sesion.headers.update(self.encabezados)
            self.local.sesion = sesion
        return sesion

    def ficha(self, tconst: str) -> Optional[dict]:
        """Ficha de TMDb del id de IMDb, o None si TMDb no la tiene.

        Los mensajes de error no incluyen la URL: con la clave v3 la URL lleva
        la credencial y terminaria en los logs.
        """
        motivo = "?"
        for intento in range(1, self.reintentos + 1):
            self.ritmo.esperar()
            try:
                r = self._sesion().get("%s/movie/%s" % (TMDB_API, tconst),
                                       params=self.parametros, timeout=30)
            except requests.RequestException as e:
                motivo = type(e).__name__
                time.sleep(min(60, 2 ** intento))
                continue

            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code == 401:
                raise CredencialInvalida(
                    "TMDb rechazo la credencial (401). Revisa TMDB_API_KEY en .env")
            motivo = "HTTP %d" % r.status_code
            if r.status_code == 429:
                self.ritmo.frenar(float(r.headers.get("Retry-After", 2)) + 1)
            else:
                time.sleep(min(60, 2 ** intento))
        raise ErrorTMDb("%s: %s tras %d intentos" % (tconst, motivo, self.reintentos))


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fila(tconst: str, ficha: Optional[dict]) -> tuple:
    if ficha is None:
        return (tconst, "no_en_tmdb") + (None,) * len(CAMPOS) + (_ahora(),)
    datos = elegir_textos(ficha)
    datos["tmdb_id"] = ficha.get("id")
    con_texto = datos["sinopsis_es"] or datos["sinopsis_en"] or datos["sinopsis_otra"]
    estado = "con_sinopsis" if con_texto else "sin_sinopsis"
    return (tconst, estado) + tuple(datos.get(c) for c in CAMPOS) + (_ahora(),)


class BaseSinopsis:
    def __init__(self, ruta: Path):
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(ruta))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(ESQUEMA)

    def __enter__(self) -> "BaseSinopsis":
        return self

    def __exit__(self, *exc) -> None:
        self.con.close()

    def consultadas(self) -> Set[str]:
        return {f[0] for f in self.con.execute("SELECT tconst FROM sinopsis_imdb")}

    def guardar(self, filas: List[tuple]) -> None:
        if not filas:
            return
        marcas = ",".join("?" * (len(CAMPOS) + 3))
        self.con.executemany(
            "INSERT OR REPLACE INTO sinopsis_imdb (tconst, estado, %s, consultado_en) "
            "VALUES (%s)" % (", ".join(CAMPOS), marcas), filas)
        self.con.commit()

    def buscar(self, tconst: str) -> Optional[tuple]:
        return self.con.execute(
            "SELECT estado, %s FROM sinopsis_imdb WHERE tconst=?" % ", ".join(CAMPOS),
            (tconst,)).fetchone()

    def conteo(self) -> Dict[str, int]:
        filas = self.con.execute(
            "SELECT estado, COUNT(*) FROM sinopsis_imdb GROUP BY estado").fetchall()
        conteo = {estado: n for estado, n in filas}
        for idioma in ("es", "en"):
            conteo["con_" + idioma] = self.con.execute(
                "SELECT COUNT(*) FROM sinopsis_imdb WHERE sinopsis_%s IS NOT NULL"
                % idioma).fetchone()[0]
        return conteo


def _votos(fila: Dict[str, str]) -> int:
    v = fila.get("numVotes") or ""
    return int(v) if v.isdigit() else 0


def pendientes(ruta_csv: Path, ya: Set[str], min_votos: int = 0) -> List[str]:
    """tconst por consultar, de la mas votada en IMDb a la menos."""
    orden = []
    with open(ruta_csv, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["tconst"] in ya:
                continue
            votos = _votos(fila)
            if votos >= min_votos:
                orden.append((-votos, fila["tconst"]))
    orden.sort()
    return [t for _, t in orden]


def _duracion(segundos: float) -> str:
    h, m = divmod(int(segundos) // 60, 60)
    return "%dh %02dm" % (h, m) if h else "%dm" % m


def recolectar(api_key: str, ruta_csv: Path, ruta_bd: Path, hilos: int = 16,
               por_segundo: float = 40.0, limite: Optional[int] = None,
               min_votos: int = 0) -> Dict[str, int]:
    cliente = ClienteTMDb(api_key, por_segundo)

    def consultar(tconst: str) -> Optional[tuple]:
        try:
            return _fila(tconst, cliente.ficha(tconst))
        except ErrorTMDb as e:
            # No se guarda: la siguiente corrida la vuelve a intentar.
            log.warning("Se omite %s", e)
            return None

    with BaseSinopsis(ruta_bd) as base:
        lista = pendientes(ruta_csv, base.consultadas(), min_votos)
        if limite:
            lista = lista[:limite]
        total = len(lista)
        log.info("Peliculas por consultar: {:,} (ya en la base: {:,})".format(
            total, sum(base.conteo().get(e, 0)
                       for e in ("con_sinopsis", "sin_sinopsis", "no_en_tmdb"))))

        inicio = time.monotonic()
        hechas = 0
        ejecutor = ThreadPoolExecutor(max_workers=hilos)
        try:
            for i in range(0, total, LOTE):
                lote = lista[i:i + LOTE]
                filas = [f for f in ejecutor.map(consultar, lote) if f is not None]
                base.guardar(filas)
                hechas += len(lote)
                ritmo = hechas / max(time.monotonic() - inicio, 1e-6)
                c = base.conteo()
                log.info("[{:,}/{:,}] {:.0f}/s, faltan ~{} | con sinopsis {:,} "
                         "(es {:,}, en {:,}) · sin texto {:,} · no en TMDb {:,}".format(
                             hechas, total, ritmo, _duracion((total - hechas) / ritmo),
                             c.get("con_sinopsis", 0), c["con_es"], c["con_en"],
                             c.get("sin_sinopsis", 0), c.get("no_en_tmdb", 0)))
        finally:
            # Ctrl+C: no esperar a que termine el lote en curso.
            ejecutor.shutdown(wait=False, cancel_futures=True)
        return base.conteo()


def exportar_csv(ruta_csv: Path, ruta_bd: Path, salida: Path,
                 solo_con_sinopsis: bool = False) -> int:
    """Una fila por pelicula del CSV de IMDb, en su mismo orden.

    `estado` es pendiente para las que aun no se consultan.
    """
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    temporal = salida.with_suffix(salida.suffix + ".tmp")
    n = 0
    with BaseSinopsis(ruta_bd) as base, \
            open(ruta_csv, newline="", encoding="utf-8") as entrada, \
            temporal.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(COLUMNAS_CSV)
        for fila in csv.DictReader(entrada):
            guardada = base.buscar(fila["tconst"])
            if guardada is None:
                guardada = ("pendiente",) + (None,) * len(CAMPOS)
            if solo_con_sinopsis and guardada[0] != "con_sinopsis":
                continue
            escritor.writerow([fila["tconst"], fila["primaryTitle"], fila["originalTitle"],
                               fila["startYear"], fila["genres"], fila["numVotes"]]
                              + list(guardada))
            n += 1
    temporal.replace(salida)
    return n

"""Cliente HTTP cortes: una peticion a la vez, con pausa, reintentos y cache."""

from __future__ import annotations

import hashlib
import logging
import random
import time
from pathlib import Path
from typing import Optional

import requests

from .robots import Robots

BASE = "https://letterboxd.com"

# Letterboxd sirve HTML distinto (y bloquea) segun el User-Agent; se usa uno de
# navegador real y se compensa siendo lento y secuencial.
ENCABEZADOS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
}

log = logging.getLogger(__name__)


class ErrorDeDescarga(RuntimeError):
    pass


class BloqueadoPorRobots(ErrorDeDescarga):
    pass


class Cliente:
    """Descarga paginas respetando robots.txt y un retardo entre peticiones."""

    def __init__(
        self,
        retardo: float = 2.0,
        reintentos: int = 3,
        cache: Optional[Path] = None,
        respetar_robots: bool = True,
        tiempo_limite: int = 30,
    ):
        self.retardo = retardo
        self.reintentos = reintentos
        self.tiempo_limite = tiempo_limite
        self.cache = Path(cache) if cache else None
        if self.cache:
            self.cache.mkdir(parents=True, exist_ok=True)

        self.sesion = requests.Session()
        self.sesion.headers.update(ENCABEZADOS)
        self._ultima_peticion = 0.0
        self.robots: Optional[Robots] = self._cargar_robots() if respetar_robots else None

    def _cargar_robots(self) -> Optional[Robots]:
        try:
            r = self.sesion.get(BASE + "/robots.txt", timeout=self.tiempo_limite)
            r.raise_for_status()
            return Robots(r.text)
        except requests.RequestException as e:
            log.warning("No se pudo leer robots.txt (%s); se asume permitido", e)
            return None

    def permitido(self, url: str) -> bool:
        return self.robots is None or self.robots.permitido(url)

    def _ruta_cache(self, url: str) -> Path:
        assert self.cache is not None
        return self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".html")

    def _esperar(self) -> None:
        # Jitter para no golpear el servidor con un patron perfectamente regular.
        objetivo = self.retardo * random.uniform(0.8, 1.3)
        pendiente = objetivo - (time.monotonic() - self._ultima_peticion)
        if pendiente > 0:
            time.sleep(pendiente)

    def obtener(self, url: str, usar_cache: bool = True) -> str:
        if not url.startswith("http"):
            url = BASE + url
        if not self.permitido(url):
            raise BloqueadoPorRobots("robots.txt prohibe " + url)

        archivo = self._ruta_cache(url) if self.cache else None
        if archivo is not None and usar_cache and archivo.exists():
            return archivo.read_text(encoding="utf-8")

        ultimo_error: Optional[Exception] = None
        for intento in range(1, self.reintentos + 1):
            self._esperar()
            try:
                r = self.sesion.get(url, timeout=self.tiempo_limite)
                self._ultima_peticion = time.monotonic()

                if r.status_code == 404:
                    raise ErrorDeDescarga("404 en " + url)
                if r.status_code in (403, 429, 500, 502, 503, 504):
                    # 403 aqui suele ser el reto de Cloudflare: bajar el ritmo.
                    espera = min(60.0, self.retardo * 2 ** intento)
                    log.warning("HTTP %s en %s; reintento en %.0fs", r.status_code, url, espera)
                    ultimo_error = ErrorDeDescarga("HTTP %s en %s" % (r.status_code, url))
                    time.sleep(espera)
                    continue
                r.raise_for_status()
            except ErrorDeDescarga:
                raise
            except requests.RequestException as e:
                ultimo_error = e
                log.warning("Fallo de red en %s (%s/%s): %s", url, intento, self.reintentos, e)
                time.sleep(min(60.0, self.retardo * 2 ** intento))
                continue

            if archivo is not None:
                archivo.write_text(r.text, encoding="utf-8")
            return r.text

        raise ErrorDeDescarga("No se pudo descargar %s: %s" % (url, ultimo_error))

    def url_final(self, url: str) -> str:
        """Sigue redirecciones y devuelve la URL resultante (sin guardar cache).

        Reintenta igual que `obtener`: una conexion cortada a mitad de una
        corrida de horas no debe tumbarla entera.
        """
        if not url.startswith("http"):
            url = BASE + url
        if not self.permitido(url):
            raise BloqueadoPorRobots("robots.txt prohibe " + url)

        ultimo_error: Optional[Exception] = None
        for intento in range(1, self.reintentos + 1):
            self._esperar()
            try:
                r = self.sesion.get(url, timeout=self.tiempo_limite, allow_redirects=True)
                self._ultima_peticion = time.monotonic()
            except requests.RequestException as e:
                ultimo_error = e
                log.warning("Fallo de red en %s (%s/%s): %s",
                            url, intento, self.reintentos, e)
                time.sleep(min(60.0, self.retardo * 2 ** intento))
                continue

            if r.status_code == 404:
                raise ErrorDeDescarga("404 en " + url)
            if r.status_code >= 400:
                espera = min(60.0, self.retardo * 2 ** intento)
                log.warning("HTTP %s en %s; reintento en %.0fs", r.status_code, url, espera)
                ultimo_error = ErrorDeDescarga("HTTP %s en %s" % (r.status_code, url))
                time.sleep(espera)
                continue
            return r.url

        raise ErrorDeDescarga("No se pudo resolver %s: %s" % (url, ultimo_error))

"""Verificacion de robots.txt con soporte para comodines.

La clase RobotFileParser de la biblioteca estandar no interpreta los patrones
con `*` que usa Letterboxd (por ejemplo `/*/country/*`), y ademas pide el
archivo con el User-Agent de urllib, al que el sitio responde 403 (lo que hace
que el parser asuma "todo prohibido"). Por eso aqui se descarga el robots.txt
con la misma sesion del scraper y se traducen los patrones a expresiones
regulares.
"""

from __future__ import annotations

import re
from typing import List
from urllib.parse import urlsplit


def _patron_a_regex(patron: str) -> "re.Pattern[str]":
    partes = [re.escape(p) for p in patron.split("*")]
    return re.compile("^" + ".*".join(partes))


class Robots:
    """Reglas de robots.txt aplicables al User-Agent generico `*`."""

    def __init__(self, texto: str):
        self.disallow: List["re.Pattern[str]"] = []
        self.allow: List["re.Pattern[str]"] = []
        en_bloque_generico = False

        for linea in texto.splitlines():
            linea = linea.split("#", 1)[0].strip()
            if not linea or ":" not in linea:
                continue
            campo, _, valor = linea.partition(":")
            campo = campo.strip().lower()
            valor = valor.strip()

            if campo == "user-agent":
                en_bloque_generico = valor == "*"
            elif en_bloque_generico and valor:
                if campo == "disallow":
                    self.disallow.append(_patron_a_regex(valor))
                elif campo == "allow":
                    self.allow.append(_patron_a_regex(valor))

    def permitido(self, url: str) -> bool:
        partes = urlsplit(url)
        ruta = partes.path or "/"
        if partes.query:
            ruta += "?" + partes.query

        # Allow gana sobre Disallow, como en la especificacion original.
        if any(p.match(ruta) for p in self.allow):
            return True
        return not any(p.match(ruta) for p in self.disallow)

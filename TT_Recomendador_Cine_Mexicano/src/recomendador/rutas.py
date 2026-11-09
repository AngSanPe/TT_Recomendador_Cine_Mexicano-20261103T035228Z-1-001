"""Rutas del proyecto.

La raíz se toma de la variable de entorno TT_RAIZ; si no existe, se busca hacia
arriba la carpeta que contiene src/recomendador. Así los notebooks funcionan igual
en la Mac, en Colab (Drive montado) o en cualquier servidor con GPU.
"""

from __future__ import annotations

import os
from pathlib import Path


def raiz() -> Path:
    if os.environ.get("TT_RAIZ"):
        return Path(os.environ["TT_RAIZ"]).expanduser().resolve()
    aqui = Path(__file__).resolve()
    for padre in aqui.parents:
        if (padre / "src" / "recomendador").is_dir():
            return padre
    return Path.cwd()


RAIZ = raiz()
CRUDOS = RAIZ / "datos" / "crudos"
LIMPIOS = RAIZ / "datos" / "limpios"
SENTIMIENTO = LIMPIOS / "sentimiento"
RESULTADOS = RAIZ / "resultados"

GRUPOS = {
    "g34": {
        "nombre": "Usuarios con 3 a 4 películas mexicanas reseñadas",
        "historial": "historial_3_a_4.db",
        "experimento": "exp1",
    },
    "g5": {
        "nombre": "Usuarios con 5 o más películas mexicanas reseñadas",
        "historial": "historial_min5.db",
        "experimento": "exp2",
    },
}

ANALIZADORES = {
    "beto": SENTIMIENTO / "sentimiento_beto.parquet",
    "jev": SENTIMIENTO / "sentimiento_jev.parquet",
}


def carpeta_resultados(nombre: str) -> Path:
    ruta = RESULTADOS / nombre
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta

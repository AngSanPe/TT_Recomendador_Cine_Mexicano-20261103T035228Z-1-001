"""Verifica la credencial de TMDb antes de lanzar el catalogo.

Uso:
    .venv/bin/python tmdb.py

Lee TMDB_API_KEY del entorno o del archivo .env de este proyecto.
Nunca imprime la clave completa.
"""

import sys

from letterboxd_scraper.cli import _clave_tmdb
from letterboxd_scraper.peliculas import CredencialInvalida, verificar_credencial


def main() -> int:
    clave = _clave_tmdb()
    print("Credencial encontrada: %s…%s (%d caracteres)"
          % (clave[:4], clave[-4:], len(clave)))
    try:
        datos = verificar_credencial(clave)
    except CredencialInvalida as e:
        print("\n✗", e)
        return 1

    print("✓ La credencial funciona.")
    print("  TMDb tiene %s peliculas de origen mexicano (%s paginas de resultados)."
          % (f"{datos['peliculas_mx']:,}", datos["paginas"]))
    print("\nSiguiente paso:")
    print("  .venv/bin/python -m letterboxd_scraper catalogo --desde-anio 1930")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

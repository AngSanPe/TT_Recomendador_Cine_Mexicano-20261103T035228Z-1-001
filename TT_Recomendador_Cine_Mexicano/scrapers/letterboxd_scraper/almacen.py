"""Almacenamiento en SQLite y exportacion a CSV/JSONL."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ESQUEMA = """
CREATE TABLE IF NOT EXISTS peliculas (
    slug                  TEXT PRIMARY KEY,
    titulo                TEXT,
    anio                  INTEGER,
    directores            TEXT,
    paises                TEXT,
    tmdb_id               INTEGER,
    calificacion_promedio REAL,
    url                   TEXT,
    actualizado           TEXT,
    titulo_es             TEXT,
    sinopsis_es           TEXT,
    sinopsis_es_fuente    TEXT,
    sinopsis_en           TEXT,
    sinopsis_en_fuente    TEXT,
    sinopsis_revisada     TEXT
);

CREATE TABLE IF NOT EXISTS resenas (
    id             TEXT PRIMARY KEY,
    pelicula_slug  TEXT NOT NULL REFERENCES peliculas(slug),
    usuario        TEXT,
    nombre_visible TEXT,
    url            TEXT,
    calificacion   REAL,
    fecha          TEXT,
    texto          TEXT,
    likes          INTEGER,
    spoiler        INTEGER,
    idioma         TEXT,
    es_relectura   INTEGER,
    recolectado_en TEXT
);

CREATE INDEX IF NOT EXISTS idx_resenas_pelicula ON resenas(pelicula_slug);
CREATE INDEX IF NOT EXISTS idx_resenas_usuario  ON resenas(usuario);
CREATE INDEX IF NOT EXISTS idx_resenas_idioma   ON resenas(idioma);

-- Catalogo de candidatas descubiertas en TMDb. Separa el descubrimiento de la
-- recoleccion: resolver el slug de Letterboxd cuesta una peticion por pelicula,
-- asi que se guarda para no repetirlo nunca.
CREATE TABLE IF NOT EXISTS catalogo (
    tmdb_id     INTEGER PRIMARY KEY,
    titulo      TEXT,
    anio        INTEGER,
    popularidad REAL,
    votos       INTEGER,
    slug        TEXT,
    paises      TEXT,
    estado      TEXT DEFAULT 'pendiente',
    visto_en    TEXT
);

CREATE INDEX IF NOT EXISTS idx_catalogo_estado ON catalogo(estado, votos DESC);
"""

CAMPOS_RESENA = [
    "id", "pelicula_slug", "usuario", "nombre_visible", "url", "calificacion",
    "fecha", "texto", "likes", "spoiler", "idioma", "es_relectura", "recolectado_en",
]

CAMPOS_SINOPSIS = [
    "titulo_es", "sinopsis_es", "sinopsis_es_fuente", "sinopsis_en", "sinopsis_en_fuente",
]

CAMPOS_EXPORT_SINOPSIS = [
    "slug", "titulo", "titulo_es", "anio", "directores", "paises", "tmdb_id",
    "sinopsis_es", "sinopsis_es_fuente", "sinopsis_en", "sinopsis_en_fuente", "url",
]


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Almacen:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.ruta)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)
        self._migrar()
        self.con.commit()

    def _migrar(self) -> None:
        """Agrega columnas nuevas a bases creadas por versiones anteriores."""
        columnas = {f[1] for f in self.con.execute("PRAGMA table_info(catalogo)")}
        if "paises" not in columnas:
            self.con.execute("ALTER TABLE catalogo ADD COLUMN paises TEXT")

        columnas = {f[1] for f in self.con.execute("PRAGMA table_info(peliculas)")}
        for nueva in CAMPOS_SINOPSIS + ["sinopsis_revisada"]:
            if nueva not in columnas:
                self.con.execute("ALTER TABLE peliculas ADD COLUMN %s TEXT" % nueva)

    def __enter__(self) -> "Almacen":
        return self

    def __exit__(self, *_) -> None:
        self.cerrar()

    def guardar_pelicula(self, pelicula: Dict[str, object]) -> None:
        datos = dict(pelicula)
        datos["actualizado"] = _ahora()
        columnas = ["slug", "titulo", "anio", "directores", "paises", "tmdb_id",
                    "calificacion_promedio", "url", "actualizado"]
        self.con.execute(
            "INSERT INTO peliculas (%s) VALUES (%s) ON CONFLICT(slug) DO UPDATE SET %s"
            % (
                ",".join(columnas),
                ",".join("?" * len(columnas)),
                ",".join("%s=excluded.%s" % (c, c) for c in columnas[1:]),
            ),
            [datos.get(c) for c in columnas],
        )
        self.con.commit()

    def guardar_resenas(self, resenas: Iterable[Dict[str, object]]) -> int:
        filas = []
        for r in resenas:
            datos = dict(r)
            datos["recolectado_en"] = _ahora()
            filas.append([datos.get(c) for c in CAMPOS_RESENA])
        if not filas:
            return 0
        # INSERT OR IGNORE hace idempotente la recoleccion: se puede reanudar.
        cur = self.con.executemany(
            "INSERT OR IGNORE INTO resenas (%s) VALUES (%s)"
            % (",".join(CAMPOS_RESENA), ",".join("?" * len(CAMPOS_RESENA))),
            filas,
        )
        self.con.commit()
        return cur.rowcount

    # ---- catalogo de candidatas -------------------------------------------

    def guardar_candidatos(self, candidatos: Iterable[Dict[str, object]]) -> int:
        filas = [
            [c.get("tmdb_id"), c.get("titulo"), c.get("anio"), c.get("popularidad"),
             c.get("votos"), _ahora()]
            for c in candidatos
        ]
        if not filas:
            return 0
        cur = self.con.executemany(
            "INSERT OR IGNORE INTO catalogo (tmdb_id,titulo,anio,popularidad,votos,visto_en)"
            " VALUES (?,?,?,?,?,?)",
            filas,
        )
        self.con.commit()
        return cur.rowcount

    def candidatos(self, estado: str = "pendiente", limite: Optional[int] = None,
                   min_votos: int = 0) -> List[sqlite3.Row]:
        sql = ("SELECT * FROM catalogo WHERE estado=? AND COALESCE(votos,0)>=? "
               "ORDER BY votos DESC, popularidad DESC")
        parametros: List[object] = [estado, min_votos]
        if limite:
            sql += " LIMIT ?"
            parametros.append(limite)
        return list(self.con.execute(sql, parametros))

    def actualizar_candidato(self, tmdb_id: int, estado: str,
                             slug: Optional[str] = None,
                             paises: Optional[str] = None) -> None:
        self.con.execute(
            "UPDATE catalogo SET estado=?, slug=COALESCE(?, slug), "
            "paises=COALESCE(?, paises) WHERE tmdb_id=?",
            (estado, slug, paises, tmdb_id),
        )
        self.con.commit()

    def candidatos_sin_paises(self, min_votos: int = 0,
                              limite: Optional[int] = None) -> List[sqlite3.Row]:
        sql = ("SELECT * FROM catalogo WHERE paises IS NULL AND estado='pendiente' "
               "AND COALESCE(votos,0)>=? ORDER BY votos DESC")
        parametros: List[object] = [min_votos]
        if limite:
            sql += " LIMIT ?"
            parametros.append(limite)
        return list(self.con.execute(sql, parametros))

    def conteo_catalogo(self) -> Dict[str, int]:
        return {f[0]: f[1] for f in self.con.execute(
            "SELECT estado, COUNT(*) FROM catalogo GROUP BY estado")}

    # ---- sinopsis ----------------------------------------------------------

    def peliculas_para_sinopsis(self, todas: bool = False,
                                limite: Optional[int] = None) -> List[sqlite3.Row]:
        """Peliculas aun sin revisar (o todas, para rehacer la consulta)."""
        sql = "SELECT slug, titulo, tmdb_id FROM peliculas"
        if not todas:
            sql += " WHERE sinopsis_revisada IS NULL"
        sql += " ORDER BY slug"
        parametros: List[object] = []
        if limite:
            sql += " LIMIT ?"
            parametros.append(limite)
        return list(self.con.execute(sql, parametros))

    def guardar_sinopsis(self, slug: str, datos: Dict[str, Optional[str]]) -> None:
        self.con.execute(
            "UPDATE peliculas SET %s, sinopsis_revisada=? WHERE slug=?"
            % ", ".join("%s=?" % c for c in CAMPOS_SINOPSIS),
            [datos.get(c) for c in CAMPOS_SINOPSIS] + [_ahora(), slug],
        )
        self.con.commit()

    def conteo_sinopsis(self) -> Dict[str, int]:
        fila = self.con.execute(
            "SELECT COUNT(*), COUNT(sinopsis_revisada), COUNT(sinopsis_es), "
            "COUNT(sinopsis_en), SUM(sinopsis_revisada IS NOT NULL "
            "AND sinopsis_es IS NULL AND sinopsis_en IS NULL) "
            "FROM peliculas"
        ).fetchone()
        return {"peliculas": fila[0], "revisadas": fila[1], "con_espanol": fila[2],
                "con_ingles": fila[3], "sin_ninguna": fila[4] or 0}

    def exportar_sinopsis_csv(self, ruta: Path) -> int:
        filas = self.con.execute(
            "SELECT %s FROM peliculas ORDER BY titulo" % ",".join(CAMPOS_EXPORT_SINOPSIS)
        ).fetchall()
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("w", newline="", encoding="utf-8") as f:
            escritor = csv.DictWriter(f, fieldnames=CAMPOS_EXPORT_SINOPSIS)
            escritor.writeheader()
            for fila in filas:
                escritor.writerow(dict(fila))
        return len(filas)

    def peliculas_registradas(self) -> List[str]:
        return [f["slug"] for f in self.con.execute("SELECT slug FROM peliculas")]

    def total_resenas(self, slug: Optional[str] = None) -> int:
        if slug:
            cur = self.con.execute("SELECT COUNT(*) FROM resenas WHERE pelicula_slug=?", (slug,))
        else:
            cur = self.con.execute("SELECT COUNT(*) FROM resenas")
        return cur.fetchone()[0]

    def resumen(self) -> List[sqlite3.Row]:
        return list(
            self.con.execute(
                """
                SELECT p.slug, p.titulo, p.anio, COUNT(r.id) AS resenas,
                       ROUND(AVG(r.calificacion), 2) AS calificacion_media
                FROM peliculas p LEFT JOIN resenas r ON r.pelicula_slug = p.slug
                GROUP BY p.slug ORDER BY resenas DESC
                """
            )
        )

    _SQL_EXPORT = """
        SELECT r.*, p.titulo AS pelicula_titulo, p.anio AS pelicula_anio
        FROM resenas r JOIN peliculas p ON p.slug = r.pelicula_slug
        {filtro}
        ORDER BY p.titulo, r.fecha
    """

    def _filas_export(self, idioma: Optional[str]) -> List[sqlite3.Row]:
        filtro = "WHERE r.idioma = ?" if idioma else ""
        parametros = [idioma] if idioma else []
        return list(self.con.execute(self._SQL_EXPORT.format(filtro=filtro), parametros))

    def conteo_idiomas(self, limite: int = 10) -> Dict[str, int]:
        return {
            (f[0] or "?"): f[1]
            for f in self.con.execute(
                "SELECT idioma, COUNT(*) c FROM resenas GROUP BY idioma "
                "ORDER BY c DESC LIMIT ?", (limite,)
            )
        }

    def exportar_csv(self, ruta: Path, idioma: Optional[str] = None) -> int:
        filas = self._filas_export(idioma)
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("w", newline="", encoding="utf-8") as f:
            if not filas:
                return 0
            escritor = csv.DictWriter(f, fieldnames=filas[0].keys())
            escritor.writeheader()
            for fila in filas:
                escritor.writerow(dict(fila))
        return len(filas)

    def exportar_jsonl(self, ruta: Path, idioma: Optional[str] = None) -> int:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with ruta.open("w", encoding="utf-8") as f:
            for fila in self._filas_export(idioma):
                f.write(json.dumps(dict(fila), ensure_ascii=False) + "\n")
                n += 1
        return n

    def cerrar(self) -> None:
        self.con.close()

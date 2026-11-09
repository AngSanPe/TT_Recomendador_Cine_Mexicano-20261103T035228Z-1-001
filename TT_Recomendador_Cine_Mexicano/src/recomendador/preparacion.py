"""De los datos crudos (bases SQLite y CSV de los scrapers) a los datos limpios.

Salida en datos/limpios/:
    catalogo_mx.parquet            películas mexicanas recomendables (878) con metadatos y sinopsis limpias
    items_contenido.parquet        toda película que aparece en algún historial, con su sinopsis limpia
    interacciones_g34.parquet      usuario × película del grupo 3–4, con la partición train/val/test
    interacciones_g5.parquet       ídem para el grupo ≥5
    resenas_sentimiento.parquet    reseñas en español de los usuarios de los experimentos (para BETO y JEV)
    resenas_afinado_beto.parquet   reseñas en español de OTROS usuarios (para afinar BETO sin fuga de datos)
    reporte_preparacion.json       conteos de cada paso
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from . import limpieza, rutas

SEMILLA = 42
FRACCION_PRUEBA = 0.2


# --------------------------------------------------------------------------
# Lectura de las fuentes crudas
# --------------------------------------------------------------------------
def cargar_catalogo(db: Path) -> pd.DataFrame:
    with sqlite3.connect(db) as con:
        cat = pd.read_sql(
            """SELECT slug AS item, titulo, titulo_es, anio, directores, paises, tmdb_id,
                      calificacion_promedio, sinopsis_es, sinopsis_en
               FROM peliculas""",
            con,
        )
        n = pd.read_sql(
            "SELECT pelicula_slug AS item, COUNT(*) AS n_resenas_total FROM resenas GROUP BY pelicula_slug",
            con,
        )
    cat = cat.merge(n, on="item", how="left")
    cat["n_resenas_total"] = cat["n_resenas_total"].fillna(0).astype(int)
    return cat


def cargar_resenas(db: Path) -> pd.DataFrame:
    with sqlite3.connect(db) as con:
        return pd.read_sql(
            """SELECT id, pelicula_slug AS item, usuario, calificacion, fecha, texto,
                      idioma, spoiler, es_relectura
               FROM resenas""",
            con,
        )


def cargar_historial(ruta: Path) -> tuple[pd.DataFrame, set]:
    with sqlite3.connect(ruta) as con:
        hist = pd.read_sql(
            'SELECT usuario, pelicula_slug AS item, calificacion, "like" FROM historial_usuario', con
        )
        procesados = pd.read_sql("SELECT usuario, estado FROM usuarios_procesados", con)
    usuarios = set(procesados.loc[procesados.estado != "vacio", "usuario"])
    return hist, usuarios


# --------------------------------------------------------------------------
# Enlace con IMDb (géneros y sinopsis de las películas del historial)
# --------------------------------------------------------------------------
def _slug(titulo) -> str:
    """Imita la forma en que Letterboxd arma sus slugs a partir del título."""
    t = unicodedata.normalize("NFKD", str(titulo)).encode("ascii", "ignore").decode().lower()
    t = t.replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def cargar_imdb(crudos: Path) -> pd.DataFrame:
    imdb = pd.read_csv(
        crudos / "imdb_movies.csv",
        usecols=["tconst", "primaryTitle", "originalTitle", "startYear", "genres", "averageRating", "numVotes"],
        low_memory=False,
    )
    sin = pd.read_csv(
        crudos / "sinopsis_imdb.csv",
        usecols=["tconst", "tmdb_id", "sinopsis_es", "sinopsis_en", "sinopsis_otra"],
        low_memory=False,
    )
    imdb = imdb.merge(sin, on="tconst", how="left")
    imdb["anio"] = pd.to_numeric(imdb["startYear"], errors="coerce")
    imdb["generos"] = imdb["genres"].replace("\\N", np.nan)
    return imdb.sort_values("numVotes", ascending=False)


def enlazar_slugs_con_imdb(slugs: pd.Series, imdb: pd.DataFrame) -> pd.DataFrame:
    """slug de Letterboxd -> tconst de IMDb, por coincidencia de título (y año).

    Orden de búsqueda:
      1. slug == titulo-año             ("the-odyssey-2026")
      2. slug == titulo                 (el título más votado, que es el que Letterboxd deja sin año)
      3. slug sin sufijo de duplicado   ("eternity-2025-1" -> "eternity-2025")
    Las coincidencias por título sin año pueden fallar con títulos homónimos: es
    una limitación documentada (cubre ~87 % de las interacciones).
    """
    anio = imdb["anio"].astype("Int64").astype(str)
    claves_anio, claves_titulo = {}, {}
    for col in ("primaryTitle", "originalTitle"):
        s = imdb[col].map(_slug)
        for k, t in zip(s + "-" + anio, imdb["tconst"]):
            claves_anio.setdefault(k, t)
        for k, t in zip(s, imdb["tconst"]):
            claves_titulo.setdefault(k, t)

    def buscar(slug):
        if slug in claves_anio:
            return claves_anio[slug]
        if slug in claves_titulo:
            return claves_titulo[slug]
        sin_dup = re.sub(r"(-\d{4})-\d+$", r"\1", slug)
        return claves_anio.get(sin_dup)

    unicos = pd.Series(slugs.unique())
    return pd.DataFrame({"item": unicos, "tconst": unicos.map(buscar)})


def _sinopsis_genericas(imdb: pd.DataFrame) -> set:
    """Textos idénticos usados en 3 o más películas: no describen la trama."""
    genericas = set()
    for col in ("sinopsis_es", "sinopsis_en", "sinopsis_otra"):
        limpias = imdb[col].dropna().map(limpieza.limpiar_sinopsis)
        cuenta = limpias.value_counts()
        genericas |= set(cuenta[cuenta >= 3].index)
    return genericas


def _elegir_sinopsis(en: pd.Series, es: pd.Series, otra: pd.Series, genericas: set) -> pd.DataFrame:
    """Prefiere inglés (idioma común a casi todo el catálogo), luego español, luego otro."""
    salida = pd.DataFrame({"sinopsis": "", "idioma_sinopsis": ""}, index=en.index)
    for idioma, serie in (("otra", otra), ("es", es), ("en", en)):  # el último gana
        limpia = serie.map(limpieza.limpiar_sinopsis)
        ok = limpia.map(lambda t: limpieza.sinopsis_informativa(t, genericas))
        salida.loc[ok, "sinopsis"] = limpia[ok]
        salida.loc[ok, "idioma_sinopsis"] = idioma
    return salida


# --------------------------------------------------------------------------
# Interacciones y partición
# --------------------------------------------------------------------------
def construir_interacciones(
    resenas: pd.DataFrame, hist: pd.DataFrame, usuarios: set, catalogo: set
) -> pd.DataFrame:
    """Une las reseñas de cine mexicano del usuario con su historial general.

    Por par (usuario, película):
      calificacion  la de la reseña más reciente con estrellas; si no hay, la del historial
      like          del historial (las reseñas no traen el like del autor)
      tiene_resena  el usuario escribió al menos una reseña (solo pasa con cine mexicano)
      es_mx         la película pertenece al catálogo recomendable
    """
    r = resenas[resenas.usuario.isin(usuarios) & resenas.item.isin(catalogo)].sort_values("fecha")
    r = (
        r.groupby(["usuario", "item"], as_index=False)
        .agg(calif_resena=("calificacion", "last"), n_resenas=("id", "size"))
    )
    h = hist[hist.usuario.isin(usuarios)].rename(columns={"calificacion": "calif_hist"})
    inter = r.merge(h, on=["usuario", "item"], how="outer")
    inter["calificacion"] = inter["calif_resena"].fillna(inter["calif_hist"])
    inter["like"] = inter["like"].fillna(0).astype(np.int8)
    inter["tiene_resena"] = inter["n_resenas"].notna()
    inter["n_resenas"] = inter["n_resenas"].fillna(0).astype(np.int16)
    inter["es_mx"] = inter["item"].isin(catalogo)
    return inter[["usuario", "item", "calificacion", "like", "tiene_resena", "n_resenas", "es_mx"]]


def particionar(inter: pd.DataFrame, semilla: int = SEMILLA, fraccion: float = FRACCION_PRUEBA) -> pd.DataFrame:
    """Asigna train / val / test por usuario.

    Candidatas a prueba: películas mexicanas que el usuario reseñó y calificó
    (la calificación es la verdad de referencia). Por usuario con n candidatas:
      test  max(1, round(0.2·n))  si n ≥ 2  (así queda al menos una en entrenamiento)
      val   el mismo tamaño, si después de test quedan ≥ 2 (se usa solo para ajustar hiperparámetros)
    Todo lo demás —incluido el historial general— es entrenamiento. Al sacar un
    par a val/test se retira completo: también su entrada del historial.
    """
    inter = inter.copy()
    inter["particion"] = "train"
    cand = inter[inter.tiene_resena & inter.calificacion.notna() & inter.es_mx]
    cand = cand.sample(frac=1.0, random_state=semilla)
    orden = cand.groupby("usuario").cumcount()
    n = cand.groupby("usuario")["item"].transform("size")
    k = np.maximum(1, np.round(fraccion * n)).astype(int)
    k_val = np.minimum(k, n - k - 1)
    es_test = (n >= 2) & (orden < k)
    es_val = (n - k >= 2) & (orden >= k) & (orden < k + k_val)
    inter.loc[cand.index[es_test.values], "particion"] = "test"
    inter.loc[cand.index[es_val.values], "particion"] = "val"
    return inter


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------
def preparar(crudos: Path = rutas.CRUDOS, limpios: Path = rutas.LIMPIOS, semilla: int = SEMILLA) -> dict:
    limpios.mkdir(parents=True, exist_ok=True)
    reporte: dict = {"semilla": semilla}

    # 1. Catálogo de cine mexicano + géneros de IMDb (vía tmdb_id) + sinopsis limpias
    db = crudos / "letterboxd.db"
    cat = cargar_catalogo(db)
    imdb = cargar_imdb(crudos)
    genericas = _sinopsis_genericas(imdb)
    puente = imdb.dropna(subset=["tmdb_id"]).drop_duplicates("tmdb_id")[["tmdb_id", "tconst", "generos"]]
    cat = cat.merge(puente, on="tmdb_id", how="left")
    sel = _elegir_sinopsis(cat.sinopsis_en, cat.sinopsis_es, pd.Series("", index=cat.index), genericas)
    cat["sinopsis_en_limpia"] = cat.sinopsis_en.map(limpieza.limpiar_sinopsis)
    cat["sinopsis_es_limpia"] = cat.sinopsis_es.map(limpieza.limpiar_sinopsis)
    cat[["sinopsis", "idioma_sinopsis"]] = sel
    cat["es_mexicana_segun_letterboxd"] = cat.paises.fillna("").str.contains("Mexico")
    reporte["catalogo"] = {
        "peliculas": len(cat),
        "con_genero_imdb": int(cat.generos.notna().sum()),
        "con_sinopsis_informativa": int((cat.sinopsis != "").sum()),
        "paises_incluye_mexico": int(cat.es_mexicana_segun_letterboxd.sum()),
    }
    cat.to_parquet(limpios / "catalogo_mx.parquet", index=False)
    catalogo = set(cat["item"])

    # 2. Interacciones de cada grupo
    resenas = cargar_resenas(db)
    usuarios_exp = {}
    todos_items = []
    for grupo, info in rutas.GRUPOS.items():
        hist, usuarios = cargar_historial(crudos / info["historial"])
        inter = particionar(construir_interacciones(resenas, hist, usuarios, catalogo), semilla)
        inter.to_parquet(limpios / f"interacciones_{grupo}.parquet", index=False)
        usuarios_exp[grupo] = usuarios
        todos_items.append(inter["item"])
        mx = inter[inter.es_mx]
        reporte[grupo] = {
            "usuarios": int(inter.usuario.nunique()),
            "peliculas": int(inter.item.nunique()),
            "interacciones": int(len(inter)),
            "interacciones_mx": int(len(mx)),
            "interacciones_mx_con_resena": int(mx.tiene_resena.sum()),
            "con_calificacion": int(inter.calificacion.notna().sum()),
            "particion": inter.particion.value_counts().to_dict(),
            "usuarios_con_test": int(inter.loc[inter.particion == "test", "usuario"].nunique()),
            "test_relevantes_>=3.5": int(((inter.particion == "test") & (inter.calificacion >= 3.5)).sum()),
        }

    # 3. Sinopsis de todas las películas del historial (para el filtrado por contenido)
    slugs = pd.concat(todos_items + [cat["item"]]).drop_duplicates()
    enlace = enlazar_slugs_con_imdb(slugs, imdb)
    imdb_u = imdb.drop_duplicates("tconst").set_index("tconst")
    enlace = enlace.join(
        imdb_u[["primaryTitle", "anio", "generos", "sinopsis_es", "sinopsis_en", "sinopsis_otra"]], on="tconst"
    )
    sel = _elegir_sinopsis(enlace.sinopsis_en, enlace.sinopsis_es, enlace.sinopsis_otra, genericas)
    items = pd.concat([enlace[["item", "tconst", "primaryTitle", "anio", "generos"]], sel], axis=1)
    items = items.rename(columns={"primaryTitle": "titulo"})
    # Para las películas mexicanas manda la información del catálogo (más confiable que el enlace por título)
    items = items[~items.item.isin(catalogo)]
    mx_items = cat[["item", "tconst", "titulo", "anio", "generos", "directores", "sinopsis", "idioma_sinopsis"]]
    items = pd.concat([mx_items, items], ignore_index=True)  # directores solo existe para el catálogo
    items["es_mx"] = items.item.isin(catalogo)
    items["anio"] = pd.to_numeric(items["anio"], errors="coerce")
    items.to_parquet(limpios / "items_contenido.parquet", index=False)
    con_sin = items.sinopsis != ""
    reporte["items_contenido"] = {
        "peliculas": len(items),
        "enlazadas_imdb": int(items.tconst.notna().sum()),
        "con_sinopsis_informativa": int(con_sin.sum()),
        "idioma_sinopsis": items.loc[con_sin, "idioma_sinopsis"].value_counts().to_dict(),
    }

    # 4. Reseñas en español para el análisis de sentimiento (limpias)
    todos = usuarios_exp["g34"] | usuarios_exp["g5"]
    grupo_de = {u: g for g, us in usuarios_exp.items() for u in us}
    es = resenas[(resenas.idioma == "es") & resenas.item.isin(catalogo)].copy()
    es["texto_beto"] = es.texto.map(lambda t: limpieza.limpiar_resena(t, emojis="texto"))
    es["texto_llm"] = es.texto.map(lambda t: limpieza.limpiar_resena(t, emojis="conservar"))
    es["util"] = es.texto_beto.map(limpieza.texto_util)

    exp = es[es.usuario.isin(todos)].copy()
    exp["grupo"] = exp.usuario.map(grupo_de)
    columnas = ["id", "usuario", "item", "grupo", "calificacion", "fecha", "spoiler", "texto", "texto_beto", "texto_llm"]
    exp_util = exp[exp.util][columnas]
    exp_util.to_parquet(limpios / "resenas_sentimiento.parquet", index=False)

    afin = es[~es.usuario.isin(todos) & es.util & es.calificacion.notna()]
    afin = afin[["id", "usuario", "item", "calificacion", "texto_beto"]]
    afin.to_parquet(limpios / "resenas_afinado_beto.parquet", index=False)

    reporte["resenas_sentimiento"] = {
        "resenas_es_usuarios_experimento": int(len(exp)),
        "descartadas_sin_texto_util": int((~exp.util).sum()),
        "finales": int(len(exp_util)),
        "por_grupo": exp_util.grupo.value_counts().to_dict(),
        "con_calificacion": int(exp_util.calificacion.notna().sum()),
        "con_emoji_traducido": int((exp_util.texto_beto != exp_util.texto_llm).sum()),
        "largo_mediana_caracteres": float(exp_util.texto_beto.str.len().median()),
        "largo_p95_caracteres": float(exp_util.texto_beto.str.len().quantile(0.95)),
    }
    reporte["resenas_afinado_beto"] = {
        "resenas": int(len(afin)),
        "usuarios": int(afin.usuario.nunique()),
    }

    with open(limpios / "reporte_preparacion.json", "w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2, default=int)
    return reporte

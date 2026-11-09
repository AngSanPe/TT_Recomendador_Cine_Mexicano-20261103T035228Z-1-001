"""Orquestación común de los experimentos 1, 2 y 3.

Protocolo (igual para filtrado colaborativo y por contenido):
  1. Ajuste: se entrena con `train` y se mide en `val`; se elige el hiperparámetro
     con mejor nDCG@10.
  2. Evaluación final: se reentrena con `train + val` y se mide una sola vez en `test`.
  3. Variantes con sentimiento (B = BETO, C = JEV): con los hiperparámetros ya
     elegidos, se elige λ en `val` y se mide en `test`.

Relevante = película mexicana retenida con calificación ≥ 3.5 ★. El ranking se
hace sobre todo el catálogo mexicano menos lo que el usuario ya vio en
entrenamiento (protocolo de ranking completo, sin muestreo de negativos).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from . import metricas as M
from . import modelos_cf as cf
from . import rutas, senal

LOTE_USUARIOS = 4096
METRICA_AJUSTE = "nDCG@10"
LAMBDAS = (0.0, 0.25, 0.5, 0.75, 1.0)


# --------------------------------------------------------------------------
# Carga
# --------------------------------------------------------------------------
def cargar_catalogo() -> pd.DataFrame:
    return pd.read_parquet(rutas.LIMPIOS / "catalogo_mx.parquet")


def cargar_interacciones(grupo: str) -> pd.DataFrame:
    return senal.senal_base(pd.read_parquet(rutas.LIMPIOS / f"interacciones_{grupo}.parquet"))


def analizadores_disponibles() -> dict:
    """Archivos de sentimiento que ya existen (los generan los notebooks 04 y 05)."""
    return {nombre: ruta for nombre, ruta in rutas.ANALIZADORES.items() if ruta.exists()}


def cargar_sentimiento(analizador: str) -> pd.DataFrame | None:
    ruta = rutas.ANALIZADORES[analizador]
    if not ruta.exists():
        return None
    return senal.sentimiento_por_par(pd.read_parquet(ruta, columns=["usuario", "item", "s"]))


# --------------------------------------------------------------------------
# Escenario: una matriz de entrenamiento + un conjunto objetivo
# --------------------------------------------------------------------------
@dataclass
class Escenario:
    inter: pd.DataFrame
    catalogo: pd.Index
    fase: str  # "val" o "test"
    m: cf.Matriz = field(init=False)

    def __post_init__(self):
        entrenar_con = {"val": ["train"], "test": ["train", "val"]}[self.fase]
        train = self.inter[self.inter.particion.isin(entrenar_con)]
        objetivo = self.inter[self.inter.particion == self.fase]
        self.usuarios = pd.Index(self.inter.usuario.unique())
        self.m = cf.construir_matriz(train, self.catalogo, self.usuarios)
        self.n_usuarios_train = int(train.usuario.nunique())

        rel = objetivo[objetivo.calificacion >= senal.UMBRAL_RELEVANTE]
        self.usuarios_eval = pd.Index(rel.usuario.unique())
        self.filas = self.usuarios.get_indexer(self.usuarios_eval)
        self.relevantes = np.zeros((len(self.filas), len(self.catalogo)), dtype=bool)
        self.relevantes[self.usuarios_eval.get_indexer(rel.usuario), self.catalogo.get_indexer(rel.item)] = True
        self.vistos = self.m.vistos_mx[self.filas].toarray()

        cal = objetivo[objetivo.calificacion.notna()]
        self.rating_filas = self.usuarios.get_indexer(cal.usuario)
        self.rating_cols = self.m.items.get_indexer(cal.item)
        self.rating_real = cal.calificacion.values
        self.rating_pares = cal[["usuario", "item"]].reset_index(drop=True)

    # ---- ranking ----
    def top(self, modelo, kmax: int = max(M.KS)) -> np.ndarray:
        bloques = []
        for i in range(0, len(self.filas), LOTE_USUARIOS):
            f = self.filas[i:i + LOTE_USUARIOS]
            bloques.append(M.top_k(modelo.puntuar(self.m, f), self.vistos[i:i + LOTE_USUARIOS], kmax))
        return np.vstack(bloques)

    def evaluar_ranking(self, modelo, similitud=None, globales: bool = True):
        top = self.top(modelo)
        por_usuario = M.metricas_ranking_por_usuario(top, self.relevantes)
        resumen = por_usuario.mean().to_dict()
        if globales:
            resumen.update(M.metricas_globales(top, self.m.popularidad_mx(), self.n_usuarios_train, similitud))
        por_usuario.insert(0, "usuario", self.usuarios_eval.values)
        return resumen, por_usuario, top

    # ---- predicción de calificación ----
    def evaluar_rating(self, modelo):
        pred = modelo.predecir(self.m, self.rating_filas, self.rating_cols)
        detalle = self.rating_pares.assign(real=self.rating_real, pred=pred)
        return M.rmse_mae(self.rating_real, pred), detalle


# --------------------------------------------------------------------------
# Ajuste de hiperparámetros y evaluación
# --------------------------------------------------------------------------
Fabrica = Callable[[dict], object]


def _ajustar_familia(esc: Escenario, nombre: str, fabrica: Fabrica, rejilla: list[dict]):
    filas = []
    if nombre.startswith("PureSVD") and len(rejilla) > 1:
        # Una sola SVD con el máximo de factores; las demás se obtienen truncando
        fmax = max(p["factores"] for p in rejilla)
        base = cf.PureSVD(fmax).ajustar(esc.m)
        modelos = [(p, base.con_factores(p["factores"])) for p in rejilla]
    else:
        modelos = ((p, None) for p in rejilla)
    for params, modelo in modelos:
        t0 = time.time()
        modelo = modelo or fabrica(params).ajustar(esc.m)
        res, _, _ = esc.evaluar_ranking(modelo, globales=False)
        filas.append({"modelo": nombre, "params": str(params), **res, "segundos": round(time.time() - t0, 1)})
        print(f"  {nombre:<18} {str(params):<40} {METRICA_AJUSTE}={res[METRICA_AJUSTE]:.4f}")
    return filas


def ajustar(inter: pd.DataFrame, catalogo: pd.Index, familias: dict[str, tuple[Fabrica, list[dict]]]):
    """Busca en `val` el mejor hiperparámetro de cada familia de modelos."""
    esc = Escenario(inter, catalogo, "val")
    print(f"Validación: {len(esc.filas):,} usuarios con al menos un relevante")
    filas = []
    for nombre, (fabrica, rejilla) in familias.items():
        filas += _ajustar_familia(esc, nombre, fabrica, rejilla)
    tabla = pd.DataFrame(filas)
    mejores = {}
    for nombre, (fabrica, rejilla) in familias.items():
        t = tabla[tabla.modelo == nombre]
        mejor = t.loc[t[METRICA_AJUSTE].idxmax(), "params"]
        mejores[nombre] = next(p for p in rejilla if str(p) == mejor)
    return tabla, mejores


def ajustar_rating(inter: pd.DataFrame, catalogo: pd.Index, familias: dict[str, tuple[Fabrica, list[dict]]]):
    """Igual que `ajustar`, pero para predicción de calificación (criterio: menor RMSE en val)."""
    esc = Escenario(inter, catalogo, "val")
    filas = []
    for nombre, (fabrica, rejilla) in familias.items():
        for params in rejilla:
            res, _ = esc.evaluar_rating(fabrica(params).ajustar(esc.m))
            filas.append({"modelo": nombre, "params": str(params), **res})
            print(f"  {nombre:<14} {str(params):<55} RMSE={res['RMSE']:.4f}")
    tabla = pd.DataFrame(filas)
    mejores = {}
    for nombre, (fabrica, rejilla) in familias.items():
        t = tabla[tabla.modelo == nombre]
        mejor = t.loc[t["RMSE"].idxmin(), "params"]
        mejores[nombre] = next(p for p in rejilla if str(p) == mejor)
    return tabla, mejores


def constructores(familias: dict, mejores: dict) -> dict:
    """{nombre: función sin argumentos que crea el modelo con sus mejores hiperparámetros}."""
    return {n: (lambda f=f, p=mejores[n]: f(p)) for n, (f, _) in familias.items()}


def comparar_variantes(por_usuario: pd.DataFrame, base: str = "A", metrica: str = "nDCG@10") -> pd.DataFrame:
    """Prueba de Wilcoxon pareada (por usuario) de cada variante contra la línea base, por modelo.

    Un valor p < 0.05 indica que la diferencia entre variantes no se explica por azar.
    """
    from scipy.stats import wilcoxon

    filas = []
    for modelo, df in por_usuario.groupby("modelo"):
        tabla = df.pivot_table(index="usuario", columns="variante", values=metrica)
        if base not in tabla:
            continue
        for var in tabla.columns.drop(base):
            par = tabla[[base, var]].dropna()
            dif = par[var] - par[base]
            p = wilcoxon(par[var], par[base], zero_method="wilcox").pvalue if (dif != 0).any() else 1.0
            filas.append({"modelo": modelo, "variante": var, "metrica": metrica, "usuarios": len(par),
                          f"media_{base}": par[base].mean(), "media_variante": par[var].mean(),
                          "diferencia": dif.mean(), "mejora_relativa": dif.mean() / max(par[base].mean(), 1e-12),
                          "usuarios_mejoran": int((dif > 0).sum()), "usuarios_empeoran": int((dif < 0).sum()),
                          "p_valor": p, "significativo_5%": p < 0.05})
    columnas = ["modelo", "variante", "metrica", "usuarios", f"media_{base}", "media_variante", "diferencia",
                "mejora_relativa", "usuarios_mejoran", "usuarios_empeoran", "p_valor", "significativo_5%"]
    return pd.DataFrame(filas, columns=columnas)


def evaluar_test(inter, catalogo, familias, mejores, variante: str, similitud=None,
                 modelos_rating: dict | None = None):
    """Reentrena con train+val y evalúa una vez en test."""
    esc = Escenario(inter, catalogo, "test")
    resumen, por_usuario, tops = [], [], {}
    for nombre, (fabrica, _) in familias.items():
        params = mejores[nombre]
        modelo = fabrica(params).ajustar(esc.m)
        res, pu, top = esc.evaluar_ranking(modelo, similitud)
        resumen.append({"modelo": nombre, "variante": variante, "params": str(params),
                        "usuarios_evaluados": len(esc.filas), **res})
        por_usuario.append(pu.assign(modelo=nombre, variante=variante))
        tops[nombre] = top
    rating, detalle = [], []
    for nombre, modelo in (modelos_rating or {}).items():
        res, det = esc.evaluar_rating(modelo().ajustar(esc.m))
        rating.append({"modelo": nombre, "variante": variante, **res})
        detalle.append(det.assign(modelo=nombre, variante=variante))
    return {  # las listas pueden venir vacías (p. ej., un λ que solo eligieron los modelos de predicción)
        "ranking": pd.DataFrame(resumen),
        "por_usuario": pd.concat(por_usuario, ignore_index=True) if por_usuario else pd.DataFrame(),
        "rating": pd.DataFrame(rating),
        "rating_detalle": pd.concat(detalle, ignore_index=True) if detalle else pd.DataFrame(),
        "tops": tops,
        "escenario": esc,
    }


def variante_sentimiento(inter_base, sent_par, catalogo, familias, mejores, variante: str,
                         similitud=None, modelos_rating: dict | None = None, lambdas=LAMBDAS):
    """Elige λ en val (por modelo) y evalúa en test con el λ elegido."""
    cobertura = _cobertura_sentimiento(inter_base, sent_par)
    print(f"[{variante}] sentimiento disponible en {cobertura['pares_train_con_sentimiento']:,} pares "
          f"de entrenamiento ({cobertura['fraccion_resenas_train']:.1%} de los pares reseñados)")

    filas_val = []
    for lam in lambdas:
        inter = senal.aplicar_sentimiento(inter_base, sent_par, lam)
        esc = Escenario(inter, catalogo, "val")
        for nombre, (fabrica, _) in familias.items():
            res, _, _ = esc.evaluar_ranking(fabrica(mejores[nombre]).ajustar(esc.m), globales=False)
            filas_val.append({"modelo": nombre, "variante": variante, "lambda": lam, **res})
        for nombre, modelo in (modelos_rating or {}).items():
            res, _ = esc.evaluar_rating(modelo().ajustar(esc.m))
            filas_val.append({"modelo": nombre, "variante": variante, "lambda": lam, **res})
        print(f"  λ={lam:<5} listo")
    val = pd.DataFrame(filas_val)

    lam_rank = {n: val.loc[val[val.modelo == n][METRICA_AJUSTE].idxmax(), "lambda"] for n in familias}
    lam_rat = {n: val.loc[val[val.modelo == n]["RMSE"].idxmin(), "lambda"] for n in (modelos_rating or {})}

    salidas = []
    for lam in sorted(set(lam_rank.values()) | set(lam_rat.values())):
        inter = senal.aplicar_sentimiento(inter_base, sent_par, lam)
        fam = {n: f for n, f in familias.items() if lam_rank[n] == lam}
        rat = {n: f for n, f in (modelos_rating or {}).items() if lam_rat[n] == lam}
        r = evaluar_test(inter, catalogo, fam, mejores, variante, similitud, rat)
        r["ranking"]["lambda"] = lam
        if len(r["rating"]):
            r["rating"]["lambda"] = lam
        salidas.append(r)
    return {
        "validacion": val,
        "lambda_ranking": lam_rank,
        "lambda_rating": lam_rat,
        "cobertura": cobertura,
        "ranking": pd.concat([s["ranking"] for s in salidas], ignore_index=True),
        "por_usuario": pd.concat([s["por_usuario"] for s in salidas], ignore_index=True),
        "rating": pd.concat([s["rating"] for s in salidas], ignore_index=True),
        "rating_detalle": pd.concat([s["rating_detalle"] for s in salidas], ignore_index=True),
    }


def _cobertura_sentimiento(inter, sent_par) -> dict:
    train = inter[(inter.particion != "test") & inter.tiene_resena]
    con = train.merge(sent_par, on=["usuario", "item"], how="inner")
    return {
        "pares_train_resenados": int(len(train)),
        "pares_train_con_sentimiento": int(len(con)),
        "fraccion_resenas_train": float(len(con) / max(len(train), 1)),
        "pares_sin_calificacion_imputados": int(con.calificacion.isna().sum()),
    }


# --------------------------------------------------------------------------
# Utilidades de presentación
# --------------------------------------------------------------------------
def similitud_catalogo(catalogo_df: pd.DataFrame) -> np.ndarray:
    """Similitud coseno TF-IDF (sinopsis + géneros) entre películas del catálogo; se usa para ILD."""
    from .modelos_contenido import RepresentacionTFIDF

    rep = RepresentacionTFIDF(min_df=1, peso_generos=0.3, peso_decada=0, peso_directores=0).ajustar(catalogo_df)
    idx = rep.items.get_indexer(catalogo_df["item"])
    V = rep.V[idx]
    return np.asarray((V @ V.T).todense(), dtype=np.float32)


def ejemplos_recomendacion(resultado: dict, catalogo_df: pd.DataFrame, inter: pd.DataFrame,
                           modelo: str, n_usuarios: int = 3, n: int = 10, semilla: int = 7) -> pd.DataFrame:
    """Top-n de algunos usuarios, marcando cuáles eran relevantes en test."""
    esc = resultado["escenario"]
    top = resultado["tops"][modelo]
    rng = np.random.default_rng(semilla)
    elegidos = rng.choice(len(esc.filas), size=min(n_usuarios, len(esc.filas)), replace=False)
    titulos = catalogo_df.set_index("item")["titulo"]
    filas = []
    for e in elegidos:
        u = esc.usuarios_eval[e]
        for pos, j in enumerate(top[e, :n], 1):
            item = esc.catalogo[j]
            filas.append({"usuario": u, "posicion": pos, "pelicula": titulos.get(item, item),
                          "relevante_en_test": bool(esc.relevantes[e, j])})
    return pd.DataFrame(filas)


def guardar(resultados: dict, carpeta, prefijo: str = ""):
    for clave in ("ranking", "rating", "validacion"):
        if clave in resultados and isinstance(resultados[clave], pd.DataFrame) and len(resultados[clave]):
            resultados[clave].to_csv(carpeta / f"{prefijo}{clave}.csv", index=False)
    for clave in ("por_usuario", "rating_detalle"):
        if clave in resultados and isinstance(resultados[clave], pd.DataFrame) and len(resultados[clave]):
            resultados[clave].to_parquet(carpeta / f"{prefijo}{clave}.parquet", index=False)

"""Filtrado basado en contenido.

Cada película se representa con bloques de contenido, cada uno normalizado y con su peso:
    texto        sinopsis limpia, como
                   TF-IDF       bolsa de palabras ponderada (unigramas y bigramas). Corre en CPU.
                   Embeddings   vector denso de un modelo de oraciones (sentence-transformers),
                                calculado aparte y leído de disco.
    géneros      one-hot de los géneros de IMDb
    década       one-hot de la década de estreno
    directores   one-hot de los directores (solo se conocen para el catálogo mexicano)

El perfil del usuario es la suma ponderada de los vectores de lo que vio, con
peso w = p − 0.5 (o p − media del usuario): lo que calificó alto acerca el
perfil, lo que calificó bajo lo aleja. Las películas mexicanas vistas pesan
`peso_mx` veces más que el resto del historial. El puntaje de una película del
catálogo es su similitud coseno con ese perfil. Como el puntaje es lineal en los
pesos, se calcula como W · S, con S = similitud (películas vistas × catálogo),
sin materializar perfiles de 50 mil dimensiones.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import MultiLabelBinarizer, normalize

from .modelos_cf import Matriz


# --------------------------------------------------------------------------
# Bloques de metadatos
# --------------------------------------------------------------------------
def _one_hot(listas: pd.Series) -> sp.csr_matrix:
    mlb = MultiLabelBinarizer(sparse_output=True)
    return normalize(sp.csr_matrix(mlb.fit_transform(listas).astype(np.float32)))


def _bloques_metadatos(items: pd.DataFrame, peso_generos: float, peso_decada: float,
                       peso_directores: float) -> list[sp.csr_matrix]:
    bloques = []
    if peso_generos > 0:
        g = items["generos"].fillna("").map(lambda s: [x for x in s.split(",") if x])
        bloques.append(_one_hot(g) * peso_generos)
    if peso_decada > 0:
        d = (items["anio"] // 10 * 10).map(lambda a: [] if pd.isna(a) else [int(a)])
        bloques.append(_one_hot(d) * peso_decada)
    if peso_directores > 0 and "directores" in items:
        di = items["directores"].fillna("").map(lambda s: [x.strip() for x in s.split(",") if x.strip()])
        bloques.append(_one_hot(di) * peso_directores)
    return bloques


class _Representacion:
    """Base: guarda `items` (slugs) y `V` (vectores, una fila por película)."""

    def __init__(self, peso_generos=0.3, peso_decada=0.3, peso_directores=0.3):
        self.peso_generos, self.peso_decada, self.peso_directores = peso_generos, peso_decada, peso_directores

    def _armar(self, texto, items: pd.DataFrame):
        bloques = [normalize(sp.csr_matrix(texto))] + _bloques_metadatos(
            items, self.peso_generos, self.peso_decada, self.peso_directores)
        return normalize(sp.hstack(bloques)).tocsr()

    def describir(self) -> str:
        return (f"{self.nombre} (géneros={self.peso_generos}, década={self.peso_decada}, "
                f"directores={self.peso_directores})")


class RepresentacionTFIDF(_Representacion):
    nombre = "TF-IDF"

    def __init__(self, max_features: int = 50_000, min_df: int = 2, ngramas=(1, 2), **pesos):
        super().__init__(**pesos)
        self.max_features, self.min_df, self.ngramas = max_features, min_df, ngramas

    def ajustar(self, items: pd.DataFrame):
        items = items[(items.sinopsis != "") | items.generos.notna()].reset_index(drop=True)
        vect = TfidfVectorizer(
            max_features=self.max_features, min_df=self.min_df, ngram_range=self.ngramas,
            stop_words="english", strip_accents="unicode", lowercase=True, sublinear_tf=True,
            dtype=np.float32,
        )
        T = vect.fit_transform(items["sinopsis"])
        self.vocabulario = len(vect.vocabulary_)
        self.items = pd.Index(items["item"])
        self.V = self._armar(T, items)
        return self


class RepresentacionEmbeddings(_Representacion):
    nombre = "Embeddings"

    def __init__(self, ruta_vectores: Path, **pesos):
        super().__init__(**pesos)
        self.ruta = Path(ruta_vectores)

    def ajustar(self, items: pd.DataFrame):
        datos = np.load(self.ruta, allow_pickle=True)
        indice = pd.Index(datos["items"])
        E = datos["vectores"].astype(np.float32)
        items = items.set_index("item").loc[indice].reset_index()
        self.items = indice
        self.modelo = str(datos["modelo"])
        V = self._armar(E, items)
        self.V = V.toarray()  # denso: el producto con matrices densas es mucho más rápido así
        return self


def similitud_con_catalogo(rep, items: pd.Index, catalogo: pd.Index) -> np.ndarray:
    """Coseno entre cada película de `items` y cada película del catálogo (items × catálogo)."""
    fila_items = rep.items.get_indexer(items)
    fila_cat = rep.items.get_indexer(catalogo)
    d = rep.V.shape[1]
    # Se agrega una fila de ceros al final para las películas sin vector
    if sp.issparse(rep.V):
        V = sp.vstack([rep.V, sp.csr_matrix((1, d), dtype=np.float32)]).tocsr()
    else:
        V = np.vstack([rep.V, np.zeros((1, d), dtype=rep.V.dtype)])
    fila_items = np.where(fila_items < 0, V.shape[0] - 1, fila_items)
    fila_cat = np.where(fila_cat < 0, V.shape[0] - 1, fila_cat)
    S = V[fila_items] @ V[fila_cat].T
    return np.asarray(S.todense() if sp.issparse(S) else S, dtype=np.float32)


# --------------------------------------------------------------------------
# Modelo
# --------------------------------------------------------------------------
class PerfilContenido:
    nombre = "Contenido"

    def __init__(self, rep, centrado: str = "neutral", peso_mx: float = 1.0):
        self.rep, self.centrado, self.peso_mx = rep, centrado, peso_mx

    def ajustar(self, m: Matriz):
        self.S = similitud_con_catalogo(self.rep, m.items, m.catalogo)
        self.S[m.mx, np.arange(len(m.mx))] = 0.0   # una película no se recomienda por parecerse a sí misma
        self.cubiertas = float((self.rep.items.get_indexer(m.items) >= 0).mean())
        return self

    def pesos(self, m: Matriz, filas: np.ndarray) -> sp.csr_matrix:
        W = m.X[filas].tocsr(copy=True)
        if self.centrado == "usuario":
            n = np.diff(W.indptr)
            medias = np.asarray(W.sum(axis=1)).ravel() / np.maximum(n, 1)
            W.data -= np.repeat(medias, n)
        else:
            W.data -= 0.5
        if self.peso_mx != 1.0:
            es_mx = np.zeros(W.shape[1], dtype=bool)
            es_mx[m.mx] = True
            W.data[es_mx[W.indices]] *= self.peso_mx
        return W

    def puntuar(self, m: Matriz, filas: np.ndarray) -> np.ndarray:
        return np.asarray(self.pesos(m, filas) @ self.S)


# --------------------------------------------------------------------------
# Embeddings de sinopsis
# --------------------------------------------------------------------------
def calcular_embeddings(items: pd.DataFrame, modelo: str, ruta_salida: Path, lote: int = 128,
                        dispositivo: str | None = None) -> Path:
    """Calcula y guarda embeddings de las sinopsis limpias con sentence-transformers.

    Guarda un .npz con `items` (slugs), `vectores` (float16, normalizados) y `modelo`.
    Requiere `pip install sentence-transformers`.
    """
    from sentence_transformers import SentenceTransformer

    items = items[items.sinopsis != ""]
    st = SentenceTransformer(modelo, device=dispositivo)
    orden = items.sinopsis.str.len().sort_values().index  # menos relleno por lote
    vec = st.encode(items.loc[orden, "sinopsis"].tolist(), batch_size=lote, show_progress_bar=True,
                    normalize_embeddings=True, convert_to_numpy=True)
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(ruta_salida, items=items.loc[orden, "item"].values.astype(object),
                        vectores=vec.astype(np.float16), modelo=np.array(modelo))
    return ruta_salida

"""Modelos de filtrado colaborativo.

Ranking (top-N) sobre la matriz usuario × película con la preferencia `p`:
    Popularidad   referencia: las películas mexicanas más vistas en entrenamiento
    ItemKNN       vecinos más cercanos por ítem, similitud coseno (Sarwar et al., 2001)
    PureSVD       SVD truncada de la matriz de preferencias (Cremonesi et al., 2010)
    EASE          autoencoder lineal de forma cerrada (Steck, 2019)

Predicción de calificación sobre `calif_efectiva` (estrellas):
    MediaGlobal   μ
    Sesgos        μ + b_u + b_i, regularizado (Koren, 2010)
    ItemKNNSesgos sesgos + vecinos sobre los residuales (como KNNBaseline de Surprise)

Solo se puntúan las películas del catálogo mexicano: el historial general sirve
para aprender los gustos, pero lo que se recomienda es cine mexicano.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.utils.extmath import randomized_svd


# --------------------------------------------------------------------------
# Matriz de entrenamiento
# --------------------------------------------------------------------------
@dataclass
class Matriz:
    usuarios: pd.Index          # índice de usuario -> fila
    items: pd.Index             # índice de película -> columna
    X: sp.csr_matrix            # preferencia p (usuarios × items)
    R: sp.csr_matrix            # calificación efectiva (0 = sin calificación)
    mx: np.ndarray              # columnas de las películas del catálogo mexicano
    catalogo: pd.Index          # slugs del catálogo, en el orden de `mx`

    @property
    def vistos_mx(self) -> sp.csr_matrix:
        return self.X[:, self.mx] > 0

    def popularidad_mx(self) -> np.ndarray:
        return np.asarray((self.X[:, self.mx] > 0).sum(axis=0)).ravel()


def construir_matriz(train: pd.DataFrame, catalogo: pd.Index, usuarios: pd.Index | None = None) -> Matriz:
    usuarios = usuarios if usuarios is not None else pd.Index(train["usuario"].unique())
    items = pd.Index(pd.concat([pd.Series(catalogo), train["item"]]).unique())
    fil = usuarios.get_indexer(train["usuario"])
    col = items.get_indexer(train["item"])
    ok = fil >= 0
    forma = (len(usuarios), len(items))
    X = sp.csr_matrix((train["p"].values[ok].astype(np.float32), (fil[ok], col[ok])), shape=forma)
    r = train["calif_efectiva"].fillna(0).values[ok].astype(np.float32)
    R = sp.csr_matrix((r, (fil[ok], col[ok])), shape=forma)
    R.eliminate_zeros()
    return Matriz(usuarios, items, X, R, items.get_indexer(catalogo), catalogo)


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------
class Popularidad:
    nombre = "Popularidad"

    def ajustar(self, m: Matriz):
        self.pop = m.popularidad_mx().astype(np.float32)
        return self

    def puntuar(self, m: Matriz, filas: np.ndarray) -> np.ndarray:
        return np.tile(self.pop, (len(filas), 1))


class ItemKNN:
    nombre = "ItemKNN"

    def __init__(self, k: int = 100, shrink: float = 0.0):
        self.k, self.shrink = k, shrink

    def ajustar(self, m: Matriz):
        X = m.X.tocsc()
        normas = np.sqrt(np.asarray(X.multiply(X).sum(axis=0)).ravel())
        S = (X.T @ X[:, m.mx]).toarray()                     # (items, catálogo)
        S /= (normas[:, None] * normas[m.mx][None, :] + self.shrink + 1e-9)
        S[m.mx, np.arange(len(m.mx))] = 0.0                    # sin auto-similitud
        if self.k and self.k < S.shape[0]:
            corte = np.argpartition(-S, self.k, axis=0)[self.k:, :]
            np.put_along_axis(S, corte, 0.0, axis=0)
        self.S = sp.csr_matrix(S.astype(np.float32))
        return self

    def puntuar(self, m: Matriz, filas: np.ndarray) -> np.ndarray:
        return np.asarray((m.X[filas] @ self.S).todense())


class PureSVD:
    nombre = "PureSVD"

    def __init__(self, factores: int = 64):
        self.factores = factores

    def ajustar(self, m: Matriz, factores_max: int | None = None):
        k = factores_max or self.factores
        # SVD aleatorizada (Halko et al., 2011): con cientos de factores es mucho más
        # rápida que ARPACK y da prácticamente los mismos vectores singulares.
        _, _, vt = randomized_svd(m.X, n_components=k, n_iter=6, random_state=0)
        self.Vt_completa = vt.astype(np.float32)  # ya vienen de mayor a menor
        self.Vt = self.Vt_completa[: self.factores]
        return self

    def con_factores(self, factores: int) -> "PureSVD":
        """Reutiliza una SVD ya calculada con más factores (para el ajuste)."""
        nuevo = PureSVD(factores)
        nuevo.Vt_completa = self.Vt_completa
        nuevo.Vt = self.Vt_completa[:factores]
        return nuevo

    def puntuar(self, m: Matriz, filas: np.ndarray) -> np.ndarray:
        return (m.X[filas] @ self.Vt.T) @ self.Vt[:, m.mx]


class EASE:
    nombre = "EASE"

    def __init__(self, lam: float = 500.0, min_interacciones: int = 20):
        self.lam, self.min_interacciones = lam, min_interacciones

    def ajustar(self, m: Matriz):
        conteo = np.asarray((m.X > 0).sum(axis=0)).ravel()
        cols = np.union1d(np.where(conteo >= self.min_interacciones)[0], m.mx)
        self.cols = cols
        Xs = m.X[:, cols]
        G = (Xs.T @ Xs).toarray().astype(np.float64)
        G[np.diag_indices_from(G)] += self.lam
        P = np.linalg.inv(G)
        del G
        pos_mx = np.searchsorted(cols, m.mx)
        B = -P[:, pos_mx] / np.diag(P)[pos_mx][None, :]
        B[pos_mx, np.arange(len(pos_mx))] = 0.0
        self.B = B.astype(np.float32)
        return self

    def puntuar(self, m: Matriz, filas: np.ndarray) -> np.ndarray:
        return np.asarray(m.X[filas][:, self.cols] @ self.B)


# --------------------------------------------------------------------------
# Predicción de calificación
# --------------------------------------------------------------------------
class MediaGlobal:
    nombre = "MediaGlobal"

    def ajustar(self, m: Matriz):
        self.mu = float(m.R.data.mean())
        return self

    def predecir(self, m: Matriz, filas, cols) -> np.ndarray:
        return np.full(len(filas), self.mu)


class Sesgos:
    nombre = "Sesgos"

    def __init__(self, reg_item: float = 5.0, reg_usuario: float = 10.0, iteraciones: int = 10):
        self.reg_item, self.reg_usuario, self.iteraciones = reg_item, reg_usuario, iteraciones

    def ajustar(self, m: Matriz):
        R = m.R.tocoo()
        u, i, r = R.row, R.col, R.data.astype(np.float64)
        self.mu = r.mean()
        bu = np.zeros(R.shape[0])
        bi = np.zeros(R.shape[1])
        nu = np.bincount(u, minlength=R.shape[0])
        ni = np.bincount(i, minlength=R.shape[1])
        for _ in range(self.iteraciones):
            bi = np.bincount(i, r - self.mu - bu[u], minlength=R.shape[1]) / (self.reg_item + ni)
            bu = np.bincount(u, r - self.mu - bi[i], minlength=R.shape[0]) / (self.reg_usuario + nu)
        self.bu, self.bi = bu, bi
        return self

    def predecir(self, m: Matriz, filas, cols) -> np.ndarray:
        return np.clip(self.mu + self.bu[filas] + self.bi[cols], 0.5, 5.0)


class ItemKNNSesgos:
    nombre = "ItemKNNSesgos"

    def __init__(self, k: int = 40, shrink: float = 100.0, reg: float = 1.0,
                 reg_item: float = 5.0, reg_usuario: float = 10.0):
        # reg: se suma al denominador del promedio de vecinos; si los vecinos son
        # pocos o poco parecidos, la corrección se encoge hacia la predicción de sesgos.
        self.k, self.shrink, self.reg = k, shrink, reg
        self.reg_item, self.reg_usuario = reg_item, reg_usuario

    def ajustar(self, m: Matriz):
        self.base = Sesgos(self.reg_item, self.reg_usuario).ajustar(m)
        R = m.R.tocoo()
        z = R.data - (self.base.mu + self.base.bu[R.row] + self.base.bi[R.col])
        Z = sp.csc_matrix((z.astype(np.float32), (R.row, R.col)), shape=R.shape)
        B = sp.csc_matrix((np.ones_like(z, dtype=np.float32), (R.row, R.col)), shape=R.shape)
        normas = np.sqrt(np.asarray(Z.multiply(Z).sum(axis=0)).ravel())
        num = (Z.T @ Z[:, m.mx]).toarray()
        cuenta = (B.T @ B[:, m.mx]).toarray()
        S = num / (normas[:, None] * normas[m.mx][None, :] + 1e-9)
        S *= cuenta / (cuenta + self.shrink)
        self.S = S.astype(np.float32)          # (items, catálogo)
        self.Z = Z.tocsr()
        self.pos_mx = {c: j for j, c in enumerate(m.mx)}
        return self

    def predecir(self, m: Matriz, filas, cols) -> np.ndarray:
        base = self.base.predecir(m, filas, cols)
        pred = base.copy()
        for n, (u, c) in enumerate(zip(filas, cols)):
            j = self.pos_mx.get(c)
            if j is None:
                continue
            ini, fin = self.Z.indptr[u], self.Z.indptr[u + 1]
            vecinos, z = self.Z.indices[ini:fin], self.Z.data[ini:fin]
            s = self.S[vecinos, j]
            ok = s > 0
            if not ok.any():
                continue
            s, z = s[ok], z[ok]
            if len(s) > self.k:
                top = np.argpartition(-s, self.k)[: self.k]
                s, z = s[top], z[top]
            pred[n] = base[n] + (s * z).sum() / (s.sum() + self.reg)
        return np.clip(pred, 0.5, 5.0)

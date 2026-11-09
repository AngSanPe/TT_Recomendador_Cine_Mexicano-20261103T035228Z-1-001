"""Métricas de evaluación.

Ranking (top-K), por usuario y luego promediadas sobre usuarios con al menos un
ítem relevante en el conjunto evaluado:
    Precision@K  fracción de las K recomendaciones que son relevantes
    Recall@K     fracción de los relevantes que aparecen en las K recomendaciones
    HitRate@K    1 si al menos un relevante aparece en las K
    nDCG@K       ganancia acumulada descontada normalizada: premia acertar arriba
    MAP@K        precisión promedio (truncada a K)
    MRR@K        1 / posición del primer acierto

Más allá de la precisión (sobre todas las listas):
    Cobertura@K  fracción del catálogo mexicano que aparece en alguna lista
    Novedad@K    autoinformación media −log2(popularidad): alto = menos obvio
    ILD@K        diversidad intra-lista: 1 − similitud coseno media entre pares de la lista

Predicción de calificación: RMSE y MAE en estrellas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

KS = (5, 10, 20)


def top_k(puntajes: np.ndarray, vistos: np.ndarray, k: int) -> np.ndarray:
    """Índices de los k mejores por fila, excluyendo lo ya visto en entrenamiento."""
    p = puntajes.astype(np.float32, copy=True)
    p[vistos] = -np.inf
    k = min(k, p.shape[1])
    part = np.argpartition(-p, k - 1, axis=1)[:, :k]
    orden = np.argsort(-np.take_along_axis(p, part, axis=1), axis=1, kind="stable")
    return np.take_along_axis(part, orden, axis=1)


def metricas_ranking_por_usuario(top: np.ndarray, relevantes: np.ndarray, ks=KS) -> pd.DataFrame:
    """top: (n_usuarios, Kmax) índices; relevantes: (n_usuarios, n_items) booleano."""
    aciertos = np.take_along_axis(relevantes, top, axis=1).astype(np.float32)
    n_rel = relevantes.sum(axis=1).astype(np.float32)
    descuento = 1.0 / np.log2(np.arange(2, top.shape[1] + 2))
    salida = {}
    for k in ks:
        a = aciertos[:, :k]
        n_hits = a.sum(axis=1)
        salida[f"Precision@{k}"] = n_hits / k
        salida[f"Recall@{k}"] = n_hits / n_rel
        salida[f"HitRate@{k}"] = (n_hits > 0).astype(np.float32)
        dcg = (a * descuento[:k]).sum(axis=1)
        idcg = np.array([descuento[: int(min(n, k))].sum() for n in n_rel], dtype=np.float32)
        salida[f"nDCG@{k}"] = dcg / idcg
        prec_acum = np.cumsum(a, axis=1) / np.arange(1, k + 1)
        salida[f"MAP@{k}"] = (prec_acum * a).sum(axis=1) / np.minimum(n_rel, k)
        primero = np.where(a.any(axis=1), a.argmax(axis=1) + 1, np.inf)
        salida[f"MRR@{k}"] = 1.0 / primero
    return pd.DataFrame(salida)


def metricas_globales(top: np.ndarray, popularidad: np.ndarray, n_usuarios_train: int,
                      similitud: np.ndarray | None = None, ks=KS) -> dict:
    """Cobertura, novedad y diversidad de todas las listas."""
    n_items = len(popularidad)
    prob = np.clip(popularidad, 1, None) / max(n_usuarios_train, 1)
    info = -np.log2(prob)
    salida = {}
    for k in ks:
        t = top[:, :k]
        salida[f"Cobertura@{k}"] = len(np.unique(t)) / n_items
        salida[f"Novedad@{k}"] = float(info[t].mean())
        if similitud is not None and k > 1:
            s = similitud[t[:, :, None], t[:, None, :]]  # (usuarios, k, k)
            suma = s.sum(axis=(1, 2)) - np.trace(s, axis1=1, axis2=2)
            salida[f"ILD@{k}"] = float(1.0 - (suma / (k * (k - 1))).mean())
    return salida


def rmse_mae(real: np.ndarray, pred: np.ndarray) -> dict:
    err = np.asarray(pred, dtype=float) - np.asarray(real, dtype=float)
    return {"RMSE": float(np.sqrt(np.mean(err ** 2))), "MAE": float(np.mean(np.abs(err))), "n": int(len(err))}

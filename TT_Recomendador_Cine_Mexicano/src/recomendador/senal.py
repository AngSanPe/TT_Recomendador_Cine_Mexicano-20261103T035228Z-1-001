"""De calificación, like y sentimiento a la señal que consumen los modelos.

Dos columnas:
    p               preferencia en [0, 1]; la usan los modelos de ranking (top-N)
    calif_efectiva  calificación en estrellas [0.5, 5]; la usan los modelos de predicción

Variante A (solo estrellas, línea base):
    con calificación          p = calificación / 5
    sin calificación, like    p = 0.9   (equivale a 4.5 ★)
    sin calificación          p = 0.6   (equivale a 3 ★: la vio, pero no sabemos más)

Variantes B (BETO) y C (JEV): solo cambia en las películas mexicanas que el
usuario reseñó en español, que son las únicas con texto. El sentimiento
s ∈ [-1, 1] se lleva a estrellas como r_s = 3 + 2·s (∈ [1, 5]) y:
    con calificación          p = λ·(calificación/5) + (1-λ)·(r_s/5)
    sin calificación          p = r_s/5   (el sentimiento sustituye a la imputación fija)
λ = 1 aísla el efecto de imputar con sentimiento; λ = 0 usa solo el sentimiento.

La columna `calificacion` original nunca se modifica: es la verdad de referencia
con la que se evalúa.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

P_SIN_CALIFICACION = 0.6
P_LIKE_SIN_CALIFICACION = 0.9
UMBRAL_RELEVANTE = 3.5  # estrellas: a partir de aquí, "le gustó"


def senal_base(inter: pd.DataFrame) -> pd.DataFrame:
    inter = inter.copy()
    p = inter["calificacion"] / 5.0
    sin = p.isna()
    p[sin] = np.where(inter.loc[sin, "like"] == 1, P_LIKE_SIN_CALIFICACION, P_SIN_CALIFICACION)
    inter["p"] = p.astype(np.float32)
    inter["calif_efectiva"] = inter["calificacion"].astype(np.float32)
    inter["con_sentimiento"] = False
    return inter


def sentimiento_por_par(sent: pd.DataFrame) -> pd.DataFrame:
    """Promedia el sentimiento de las reseñas de un mismo usuario a una misma película."""
    sent = sent.dropna(subset=["s"])
    return sent.groupby(["usuario", "item"], as_index=False)["s"].mean()


def aplicar_sentimiento(inter: pd.DataFrame, sent_par: pd.DataFrame, lam: float) -> pd.DataFrame:
    """Devuelve una copia de `inter` (ya con senal_base) con la señal ajustada por sentimiento."""
    out = inter.drop(columns=["s"], errors="ignore").merge(sent_par, on=["usuario", "item"], how="left")
    hay = out["s"].notna() & out["tiene_resena"]
    p_s = (3.0 + 2.0 * out.loc[hay, "s"].clip(-1, 1)) / 5.0
    con_calif = out.loc[hay, "calificacion"].notna()
    p_nueva = np.where(con_calif, lam * out.loc[hay, "calificacion"] / 5.0 + (1 - lam) * p_s, p_s)
    out.loc[hay, "p"] = p_nueva.astype(np.float32)
    out.loc[hay, "calif_efectiva"] = (5.0 * p_nueva).astype(np.float32)
    out.loc[hay, "con_sentimiento"] = True
    return out

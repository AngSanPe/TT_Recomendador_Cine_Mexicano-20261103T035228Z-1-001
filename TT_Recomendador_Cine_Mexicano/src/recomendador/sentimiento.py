"""Utilidades compartidas por los experimentos 4 (BETO) y 5 (JEV).

Formato de salida (datos/limpios/sentimiento/sentimiento_<analizador>.parquet), una fila por reseña:
    id, usuario, item, grupo, calificacion   copiados de resenas_sentimiento.parquet
    etiqueta     "negativo" | "neutral" | "positivo"
    s            puntaje continuo en [-1, 1]  (BETO: P(pos) − P(neg); JEV: el que devuelve el modelo)
    p_neg, p_neu, p_pos   probabilidades (solo BETO; NaN para JEV)
    modelo       nombre exacto del modelo usado

Evaluación del analizador contra las estrellas que el propio autor puso a la
película (es una referencia ruidosa, no una etiqueta perfecta: alguien puede
dar 4 ★ y escribir una reseña sarcástica). Clases derivadas de las estrellas:
    negativo ≤ 2.0 ★     neutral 2.5–3.0 ★     positivo ≥ 3.5 ★
El umbral positivo coincide con el de "relevante" en los experimentos 1–3.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CLASES = ["negativo", "neutral", "positivo"]
COLUMNAS = ["id", "usuario", "item", "grupo", "calificacion", "etiqueta", "s", "p_neg", "p_neu", "p_pos", "modelo"]


def clase_desde_estrellas(calificacion: pd.Series) -> pd.Series:
    return pd.cut(calificacion, bins=[0, 2.0, 3.0, 5.0], labels=CLASES, include_lowest=True).astype(object)


def validar(df: pd.DataFrame) -> pd.DataFrame:
    """Revisa que el archivo tenga el formato que esperan los experimentos 1–3."""
    faltan = set(["id", "usuario", "item", "s", "etiqueta"]) - set(df.columns)
    if faltan:
        raise ValueError(f"Faltan columnas: {faltan}")
    if df["s"].dropna().abs().max() > 1.0 + 1e-6:
        raise ValueError("`s` debe estar en [-1, 1]")
    for c in COLUMNAS:
        if c not in df:
            df[c] = np.nan
    return df[COLUMNAS]


def evaluar_contra_estrellas(df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Métricas del analizador frente a las estrellas. Devuelve (resumen, matriz de confusión)."""
    from scipy.stats import pearsonr, spearmanr
    from sklearn.metrics import accuracy_score, classification_report, cohen_kappa_score, confusion_matrix, f1_score

    d = df.dropna(subset=["calificacion", "s"]).copy()
    d = d[d.etiqueta.isin(CLASES)]
    real = clase_desde_estrellas(d.calificacion)
    reporte = classification_report(real, d.etiqueta, labels=CLASES, output_dict=True, zero_division=0)
    resumen = {
        "resenas_evaluadas": int(len(d)),
        "exactitud": accuracy_score(real, d.etiqueta),
        "f1_macro": f1_score(real, d.etiqueta, labels=CLASES, average="macro", zero_division=0),
        "kappa_cohen": cohen_kappa_score(real, d.etiqueta, labels=CLASES),
        **{f"f1_{c}": reporte[c]["f1-score"] for c in CLASES},
        "spearman_s_vs_estrellas": spearmanr(d.s, d.calificacion).statistic,
        "pearson_s_vs_estrellas": pearsonr(d.s, d.calificacion).statistic,
        "mae_estrellas": float(np.mean(np.abs((3 + 2 * d.s) - d.calificacion))),
        "distribucion_predicha": d.etiqueta.value_counts(normalize=True).round(3).to_dict(),
        "distribucion_estrellas": real.value_counts(normalize=True).round(3).to_dict(),
    }
    matriz = pd.DataFrame(confusion_matrix(real, d.etiqueta, labels=CLASES),
                          index=[f"real_{c}" for c in CLASES], columns=[f"pred_{c}" for c in CLASES])
    return resumen, matriz


def acuerdo_entre_analizadores(a: pd.DataFrame, b: pd.DataFrame, nombres=("beto", "jev")) -> dict:
    """Qué tanto coinciden dos analizadores sobre las mismas reseñas."""
    from scipy.stats import spearmanr
    from sklearn.metrics import cohen_kappa_score

    m = a[["id", "etiqueta", "s"]].merge(b[["id", "etiqueta", "s"]], on="id", suffixes=("_a", "_b")).dropna()
    m = m[m.etiqueta_a.isin(CLASES) & m.etiqueta_b.isin(CLASES)]
    return {
        "resenas_en_comun": int(len(m)),
        "acuerdo_etiqueta": float((m.etiqueta_a == m.etiqueta_b).mean()),
        "kappa_cohen": float(cohen_kappa_score(m.etiqueta_a, m.etiqueta_b, labels=CLASES)),
        "spearman_s": float(spearmanr(m.s_a, m.s_b).statistic),
        "analizadores": list(nombres),
    }


def graficar_evaluacion(df: pd.DataFrame, matriz: pd.DataFrame, titulo: str, ruta=None):
    import matplotlib.pyplot as plt

    fig, ejes = plt.subplots(1, 2, figsize=(12, 4.5))
    m = matriz.values / matriz.values.sum(axis=1, keepdims=True)
    ejes[0].imshow(m, cmap="Blues", vmin=0, vmax=1)
    for i in range(3):
        for j in range(3):
            ejes[0].text(j, i, f"{m[i, j]:.2f}\n({matriz.values[i, j]:,})", ha="center", va="center",
                         color="white" if m[i, j] > 0.5 else "black", fontsize=9)
    ejes[0].set_xticks(range(3), CLASES)
    ejes[0].set_yticks(range(3), CLASES)
    ejes[0].set_xlabel("predicho por el analizador")
    ejes[0].set_ylabel("según las estrellas")
    ejes[0].set_title("Matriz de confusión (normalizada por fila)")

    d = df.dropna(subset=["calificacion", "s"])
    grupos = d.groupby("calificacion")["s"]
    ejes[1].errorbar(grupos.mean().index, grupos.mean().values, yerr=grupos.std().values, fmt="o-", capsize=3)
    ejes[1].axhline(0, color="gray", lw=0.8)
    ejes[1].set_xlabel("estrellas que dio el autor")
    ejes[1].set_ylabel("sentimiento s (media ± desv.)")
    ejes[1].set_title("Sentimiento vs. calificación")
    fig.suptitle(titulo)
    fig.tight_layout()
    if ruta:
        fig.savefig(ruta, dpi=130, bbox_inches="tight")
    return fig

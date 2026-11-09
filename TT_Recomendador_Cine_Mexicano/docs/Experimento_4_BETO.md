# Experimento 4 · Análisis de sentimiento de las reseñas con BETO

**Notebook:** `notebooks/04_experimento4_sentimiento_beto.ipynb` · **Resultados:** `resultados/exp4/` · **Salida para los experimentos 1–3:** `datos/limpios/sentimiento/sentimiento_beto.parquet`

**Estado:** notebook listo y probado; **pendiente de ejecutar en un entorno con GPU**. Se verificó de punta a punta (afinado e inferencia) con una muestra de 300 reseñas en la GPU de una Mac (MPS).

## 1. Objetivo

Obtener, para cada reseña en español de los usuarios de los experimentos, un puntaje de sentimiento `s ∈ [-1, 1]` que indique qué tan positiva fue la opinión del autor sobre la película, y medir qué tan bien coincide con las estrellas que el propio autor puso. Ese puntaje alimenta la **variante B** de los experimentos 1, 2 y 3.

**Hipótesis.** El texto de la reseña contiene matices que las estrellas no capturan (y existe aunque el usuario no haya puesto estrellas); incorporarlo debería dar una señal de preferencia más fiel y, con ella, mejores recomendaciones.

## 2. Modelo

**BETO** (Cañete et al., 2020) es un BERT-base (110 M de parámetros) preentrenado desde cero con ~3 mil millones de palabras en español. Por sí solo no clasifica sentimiento: necesita una capa de clasificación afinada con ejemplos etiquetados. El notebook ofrece dos caminos:

| Modo | Modelo de partida | Datos de afinado | Comentario |
|---|---|---|---|
| **`afinado`** (predeterminado) | `dccuchile/bert-base-spanish-wwm-cased` | 60 mil reseñas de Letterboxd de **otros** usuarios (20 mil por clase), etiquetadas por sus estrellas | aprende el lenguaje de las reseñas de cine |
| `preentrenado` | `finiteautomata/beto-sentiment-analysis` | ya viene afinado con tuits (TASS 2020, pysentimiento) | sin entrenamiento; referencia |

**Por qué el modo afinado es el predeterminado.** En la prueba con 300 reseñas, el modelo de tuits obtuvo F1-macro ≈ 0.40 y Spearman ≈ 0.21 contra las estrellas, y su error típico fue confundir *trama* oscura con *opinión* negativa: "Aquí es el pinche infierno…" (5 ★) o "Macario solo quería comer un guajolote…" (4.5 ★) salieron como negativas con probabilidad > 0.99. Un tuit y una reseña de cine hablan distinto; afinar con reseñas reales corrige eso. Ambos modos se pueden correr y comparar: cada uno guarda sus archivos con su propio sufijo.

**Sin fuga de información.** Las reseñas de afinado (`resenas_afinado_beto.parquet`, 152,187 reseñas de 95,934 usuarios) pertenecen a usuarios que **no** están en ningún grupo experimental. La evaluación contra estrellas y el uso en los experimentos 1–3 se hacen sobre usuarios que el modelo nunca vio.

## 3. Datos de entrada

`datos/limpios/resenas_sentimiento.parquet`: 151,516 reseñas en español (31,644 del grupo 3–4 y 119,872 del grupo ≥ 5), columna `texto_beto`. Limpieza aplicada (detalle en [Datos_y_limpieza.md](Datos_y_limpieza.md)): HTML, URLs y menciones fuera; letras y signos repetidos reducidos a tres; saltos de línea a espacio; **emojis traducidos a palabras** (😭 → *llorando*, 🔥 → *excelente*), porque el vocabulario de BETO no los tiene. No se quitan mayúsculas, acentos ni puntuación.

## 4. Procedimiento

1. **(Modo afinado)** Etiquetas desde estrellas: negativo ≤ 2 ★, neutral 2.5–3 ★, positivo ≥ 3.5 ★. Clases balanceadas (20 mil c/u), 90/10 entrenamiento/validación. AdamW, tasa 2·10⁻⁵, *warmup* 6 % y decaimiento lineal, 2 épocas, lotes de 32, 128 tokens, fp16 en GPU. Se guarda el modelo con mejor F1-macro en validación (`modelos/beto_afinado_resenas/`).
2. **Inferencia** sobre las 151,516 reseñas: lotes de 64 ordenados por longitud (menos relleno), hasta 256 tokens (cubre ~99 % de las reseñas), fp16. Avance guardado cada 20 mil reseñas para reanudar si la sesión se cae.
3. **Salida por reseña:** `p_neg`, `p_neu`, `p_pos`, `etiqueta` (la de mayor probabilidad) y **`s = p_pos − p_neg`**.
4. **Evaluación** contra las estrellas (ver §5).
5. **Uso en los experimentos 1–3** (variante B): en las películas mexicanas reseñadas en español, la preferencia pasa a `p = λ·(estrellas/5) + (1 − λ)·(3 + 2s)/5`; si no hay estrellas, `p = (3 + 2s)/5`. λ se elige en validación.

## 5. Métricas

| Métrica | Qué mide |
|---|---|
| Exactitud | % de reseñas con la clase correcta |
| F1-macro | promedio del F1 de las 3 clases (robusto al desbalance: ~59 % de las reseñas con estrellas son positivas, 25 % neutrales y 17 % negativas) |
| Kappa de Cohen | acuerdo con las estrellas descontando el azar |
| F1 por clase | dónde falla (la clase neutral suele ser la más difícil) |
| Spearman(s, estrellas) | si el puntaje continuo ordena bien las reseñas |
| MAE en estrellas | error de `3 + 2s` frente a las estrellas |

Se reportan para todas las reseñas, por grupo y por longitud del texto (< 50, 50–150, 150–400, > 400 caracteres). El notebook incluye un análisis de errores con los desacuerdos más fuertes (5 ★ con texto "negativo" y viceversa).

**Advertencia de interpretación.** Las estrellas son una referencia ruidosa: hay reseñas irónicas, reseñas que hablan de otra cosa ("vine por Gael") y usuarios que califican distinto de lo que escriben. Un acuerdo perfecto no es posible ni deseable: si el sentimiento solo copiara las estrellas, no aportaría información nueva a la recomendación.

## 6. Resultados

_Pendiente de ejecución en GPU._ Al terminar, el notebook escribe:

* `resultados/exp4/metricas_sentimiento_beto.json` y `.csv` (y una versión con sufijo por modo)
* `resultados/exp4/matriz_confusion_beto_*.csv`, `evaluacion_beto_*.png`
* `resultados/exp4/afinado_historial.csv` (pérdida y F1 por época)

y el efecto sobre la recomendación aparece en la variante B de los experimentos 1–3 y en `resultados/comparacion/resumen_resultados.md`.

| Métrica | BETO afinado | BETO preentrenado (tuits) |
|---|---|---|
| Exactitud | | |
| F1-macro | | |
| Kappa | | |
| Spearman | | |

## 7. Cómo ejecutarlo

1. Sube `src/`, `notebooks/` y `datos/limpios/` a Drive; abre el notebook en Colab con GPU T4.
2. Descomenta las líneas de Colab de la primera celda y la de `pip install`.
3. Ejecuta todo. Tiempo estimado en T4: ~10 min de afinado + ~10 min de inferencia.
4. Descarga `datos/limpios/sentimiento/sentimiento_beto.parquet` y `resultados/exp4/` a la carpeta local; vuelve a correr 01, 02, 03 y 06.
5. (Opcional) Cambia a `MODO = 'preentrenado'` y ejecuta otra vez para comparar; ojo: la última corrida completa es la que queda como `sentimiento_beto.parquet`.

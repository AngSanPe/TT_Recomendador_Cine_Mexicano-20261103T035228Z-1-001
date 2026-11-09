# Experimento 1 · Filtrado colaborativo — usuarios con 3 a 4 películas mexicanas

**Notebook:** `notebooks/01_experimento1_cf_usuarios_3a4.ipynb` · **Resultados:** `resultados/exp1/` · **Protocolo y métricas:** [Protocolo_y_metricas.md](Protocolo_y_metricas.md)

**Estado:** variante A (solo estrellas) ejecutada. Variantes B (BETO) y C (JEV) se ejecutan solas al volver a correr el notebook cuando existan los archivos de sentimiento.

## 1. Objetivo

Medir qué tan bien un sistema de **filtrado colaborativo** recomienda cine mexicano al **espectador ocasional**: alguien que reseñó solo 3 o 4 películas mexicanas en Letterboxd. Tras apartar las películas de prueba y validación, a este usuario le quedan 1 o 2 películas mexicanas en entrenamiento, además de su historial reciente de cine en general (~80 películas). Es un escenario cercano al *arranque en frío* dentro del dominio.

**Preguntas.**
1. ¿Puede el historial de cine en general compensar el poco historial de cine mexicano?
2. ¿Qué algoritmo colaborativo funciona mejor en este escenario?
3. ¿Mejora la recomendación si la preferencia incorpora el sentimiento de las reseñas (BETO, JEV)?

**Hipótesis.** El filtrado colaborativo supera claramente a la popularidad aunque el usuario tenga muy pocas películas mexicanas, porque aprende de las coincidencias entre su historial general y el de otros usuarios. El sentimiento aporta poco aquí, porque estos usuarios tienen pocas reseñas.

## 2. Datos

| | |
|---|---|
| Usuarios | 19,790 |
| Películas distintas (todas) | 72,240 |
| Películas del catálogo mexicano vistas por alguien | 828 de 878 |
| Interacciones usuario–película | 1,659,339 (densidad 0.116 %) |
| Interacciones con cine mexicano | 95,799 (66,339 con reseña escrita) |
| Pares en `train` / `val` / `test` | 1,621,906 / 18,335 / 19,098 |
| Pares de prueba relevantes (≥ 3.5 ★) | 11,276 |
| **Usuarios evaluados** (≥ 1 relevante en prueba) | **11,276** |

Cada usuario de este grupo tiene exactamente **una** película en prueba; por eso aquí Recall@K = HitRate@K y MAP@K = MRR@K.

## 3. Señal de preferencia (variante A)

`p = estrellas / 5`; sin estrellas: 0.9 si dio *like*, 0.6 si no (la vio, no sabemos más). Los modelos de predicción usan las estrellas directamente.

## 4. Modelos

| Modelo | Tipo | Idea |
|---|---|---|
| Popularidad | referencia | las películas mexicanas más vistas en entrenamiento |
| ItemKNN | vecindario | similitud coseno entre películas según quién las vio (Sarwar et al., 2001) |
| PureSVD | factorización | SVD truncada de la matriz de preferencias (Cremonesi et al., 2010) |
| EASE | autoencoder lineal | matriz película→película aprendida con solución cerrada y regularización λ (Steck, 2019) |
| MediaGlobal, Sesgos, ItemKNN con sesgos | predicción de estrellas | μ; μ + b_u + b_i; sesgos + vecinos sobre residuales |

Todos los modelos aprenden de la matriz completa (historial general + cine mexicano), pero **solo puntúan las 878 películas del catálogo mexicano**.

## 5. Ajuste de hiperparámetros (validación, nDCG@10)

| Modelo | Valores probados → nDCG@10 en `val` | Elegido |
|---|---|---|
| ItemKNN, vecinos *k* | 10: 0.0506 · 25: 0.0489 · 50: 0.0483 · 100: 0.0476 · 400: 0.0482 · 1600: 0.0495 · 6400: 0.0508 | 6400 (curva casi plana: *k* no es crítico) |
| PureSVD, factores | 64: 0.0709 · 128: 0.0751 · 256: 0.0783 · 384: 0.0835 · **512: 0.0896** · 768: 0.0839 | 512 |
| EASE, λ | 25: 0.0977 · 50: 0.1007 · **100: 0.1019** · 250: 0.0989 · 500: 0.0947 | 100 |
| Sesgos (reg. ítem, usuario) | (2, 5): 0.8738 · (5, 10): 0.8775 · (10, 15): 0.8852 (RMSE) | (2, 5) |
| ItemKNN con sesgos | *k* = 40, *shrink* ∈ {20, 100}, reg ∈ {0.5, 1}: RMSE 0.8707–0.8725 | *shrink* 20, reg 0.5 |

Los óptimos de PureSVD y EASE quedan en el interior de la rejilla (no en un extremo), lo que indica que el rango explorado fue suficiente.

## 6. Resultados en prueba — variante A

### Ranking (K = 10)

| Modelo | Precision@10 | Recall@10 = HitRate@10 | **nDCG@10** | MRR@10 |
|---|---|---|---|---|
| Popularidad | 0.0064 | 0.0638 | 0.0269 | 0.0160 |
| ItemKNN | 0.0128 | 0.1281 | 0.0576 | 0.0366 |
| PureSVD | 0.0204 | 0.2043 | 0.1132 | 0.0857 |
| **EASE** | **0.0259** | **0.2591** | **0.1374** | **0.1004** |

### Otros cortes

| Modelo | Recall@5 | nDCG@5 | Recall@20 | nDCG@20 |
|---|---|---|---|---|
| Popularidad | 0.0278 | 0.0154 | 0.1274 | 0.0427 |
| ItemKNN | 0.0654 | 0.0376 | 0.2402 | 0.0857 |
| PureSVD | 0.1337 | 0.0905 | 0.3005 | 0.1375 |
| EASE | 0.1705 | 0.1090 | 0.3828 | 0.1686 |

### Más allá de la precisión

| Modelo | Cobertura@10 | Novedad@10 (bits) | ILD@10 |
|---|---|---|---|
| Popularidad | 2.4 % | 4.19 | 0.963 |
| ItemKNN | 33.6 % | 4.70 | 0.969 |
| PureSVD | 26.8 % | 5.72 | 0.968 |
| EASE | 37.7 % | 5.33 | 0.966 |

### Predicción de calificación

| Modelo | RMSE | MAE |
|---|---|---|
| Media global | 1.133 | 0.893 |
| Sesgos (μ + b_u + b_i) | 0.870 | 0.668 |
| ItemKNN con sesgos | **0.864** | **0.663** |

## 7. Interpretación

* **El filtrado colaborativo funciona incluso con muy poco historial mexicano.** Con EASE, para **26 % de los usuarios** la película mexicana que le gustó y que el sistema no conocía aparece entre las 10 primeras de 878 posibles. Un orden al azar lo lograría en ~1.1 % de los casos y la popularidad en 6.4 %. En nDCG@10, EASE es **5.1 veces** la popularidad.
* **El orden de los modelos es claro y significativo:** EASE > PureSVD > ItemKNN > Popularidad, con *p* < 10⁻²⁵ en todas las comparaciones (Wilcoxon pareado por usuario sobre nDCG@10). Los modelos que aprenden relaciones globales (EASE, PureSVD) superan al vecindario local (ItemKNN), algo esperable con datos tan dispersos (densidad 0.1 %).
* **No sacrifica diversidad:** EASE recomienda el 38 % del catálogo (popularidad, el 2 %) y con mayor novedad. No se limita a los éxitos de taquilla.
* **Predicción de estrellas:** los sesgos explican casi todo lo que se puede predecir (RMSE 1.13 → 0.87, −23 %); los vecinos aportan una mejora pequeña (0.870 → 0.864). Con 1–2 películas mexicanas por usuario hay poca señal individual para afinar más.
* **Respuesta a la pregunta 1:** sí. Con apenas 1–2 películas mexicanas en entrenamiento, el historial de cine general permite recomendar cine mexicano con una calidad cercana a la del grupo asiduo (experimento 2: nDCG@10 = 0.174).

## 8. Variantes con sentimiento (B: BETO, C: JEV)

**Pendiente** de los archivos de los experimentos 4 y 5. Al volver a correr el notebook se ejecutan solas y se agregan a las tablas de `resultados/exp1/`. Para este grupo hay 31,644 reseñas en español; en entrenamiento, el sentimiento cubrirá ~47 % de los pares reseñados (el resto está en otros idiomas y conserva la señal de estrellas).

Qué registrar cuando estén:

| Modelo | nDCG@10 A | nDCG@10 B | nDCG@10 C | λ elegido (B / C) | *p* Wilcoxon B vs A | *p* C vs A |
|---|---|---|---|---|---|---|
| ItemKNN | 0.0576 | | | | | |
| PureSVD | 0.1132 | | | | | |
| EASE | 0.1374 | | | | | |

| Modelo | RMSE A | RMSE B | RMSE C |
|---|---|---|---|
| Sesgos | 0.870 | | |
| ItemKNN con sesgos | 0.864 | | |

## 9. Archivos generados (`resultados/exp1/`)

| Archivo | Contenido |
|---|---|
| `descripcion_datos.csv` | tabla de la sección 2 |
| `ajuste_validacion_ranking.csv/.png`, `ajuste_validacion_rating.csv` | rejillas de la sección 5 |
| `ranking_test.csv`, `rating_test.csv` | métricas finales (todas las K y variantes) |
| `por_usuario_test.parquet`, `rating_detalle_test.parquet` | métricas por usuario y predicciones por par (para pruebas estadísticas) |
| `significancia.csv` | Wilcoxon de cada variante contra A |
| `hiperparametros.json` | hiperparámetros y λ elegidos |
| `metricas_test_variante_A.png` | gráfica de la sección 6 |
| `ajuste_lambda_validacion.csv/.png` | sensibilidad a λ (cuando haya sentimiento) |

## 10. Limitaciones

* El historial general es una ventana de las ~72 películas más recientes del usuario, no su historial completo.
* La evaluación es *offline*: mide si el sistema recupera películas que el usuario ya vio y le gustaron, no si aceptaría una recomendación nueva.
* Una sola partición aleatoria (semilla 42); la significancia se apoya en el gran número de usuarios (11,276), no en repeticiones.

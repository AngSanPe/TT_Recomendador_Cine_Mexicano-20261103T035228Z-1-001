# Experimento 2 · Filtrado colaborativo — usuarios con 5 o más películas mexicanas

**Notebook:** `notebooks/02_experimento2_cf_usuarios_min5.ipynb` · **Resultados:** `resultados/exp2/` · **Protocolo y métricas:** [Protocolo_y_metricas.md](Protocolo_y_metricas.md)

**Estado:** variante A (solo estrellas) ejecutada. Variantes B (BETO) y C (JEV) se ejecutan solas al volver a correr el notebook cuando existan los archivos de sentimiento.

## 1. Objetivo

Repetir el experimento 1 con el **espectador asiduo** de cine mexicano: usuarios que reseñaron 5 o más películas mexicanas (mediana 7, hasta 279). Con la partición, estos usuarios conservan varias películas mexicanas en entrenamiento además de su historial general. El código, los modelos, las rejillas y el protocolo son **idénticos** al experimento 1; lo único que cambia es el grupo de usuarios. Así, la diferencia entre ambos experimentos mide el efecto de tener más historial en el dominio.

**Preguntas.**
1. ¿Cuánto mejora la recomendación cuando el usuario tiene más historial de cine mexicano?
2. ¿Cambia cuál es el mejor algoritmo o sus hiperparámetros?
3. ¿Aporta más el sentimiento en este grupo, que tiene casi cuatro veces más reseñas?

**Hipótesis.** Todas las métricas mejoran respecto al experimento 1. El sentimiento tiene más oportunidad de ayudar aquí, porque cada usuario tiene más películas mexicanas reseñadas en entrenamiento.

## 2. Datos

| | Grupo ≥ 5 (este) | Grupo 3–4 (exp. 1) |
|---|---|---|
| Usuarios | 19,784 | 19,790 |
| Películas distintas | 67,786 | 72,240 |
| Películas del catálogo vistas por alguien | 861 | 828 |
| Interacciones (densidad) | 1,844,900 (0.138 %) | 1,659,339 (0.116 %) |
| Interacciones con cine mexicano | 239,442 | 95,799 |
| …con reseña escrita | 198,139 | 66,339 |
| Reseñas en español (para sentimiento) | 119,872 | 31,644 |
| Pares en `train` / `val` / `test` | 1,770,555 / 37,120 / 37,225 | 1,621,906 / 18,335 / 19,098 |
| Pares de prueba relevantes (≥ 3.5 ★) | 20,859 | 11,276 |
| **Usuarios evaluados** | **13,469** | 11,276 |

A diferencia del grupo 3–4, aquí un usuario puede tener varias películas en prueba (20 % de sus candidatas), así que Recall@K y HitRate@K ya no coinciden.

## 3. Señal, modelos y protocolo

Iguales al experimento 1 (ver [Experimento_1.md](Experimento_1.md), secciones 3–4).

## 4. Ajuste de hiperparámetros (validación, nDCG@10)

| Modelo | Valores probados → nDCG@10 en `val` | Elegido | (Exp. 1) |
|---|---|---|---|
| ItemKNN, *k* | **10: 0.0613** · 25: 0.0588 · 50: 0.0572 · 100: 0.0570 · 400: 0.0531 · 1600: 0.0498 · 6400: 0.0501 | 10 | 6400 |
| PureSVD, factores | 64: 0.0810 · 128: 0.0959 · **256: 0.1199** · 384: 0.1154 · 512: 0.0989 · 768: 0.0819 | 256 | 512 |
| EASE, λ | 25: 0.1333 · 50: 0.1368 · **100: 0.1379** · 250: 0.1336 · 500: 0.1255 | 100 | 100 |
| Sesgos | (2, 5): **0.8208** · (5, 10): 0.8213 · (10, 15): 0.8236 (RMSE) | (2, 5) | (2, 5) |
| ItemKNN con sesgos | RMSE 0.8119–0.8173 | *shrink* 20, reg 0.5 | igual |

Con más historial mexicano, ItemKNN prefiere vecindarios **pequeños** (*k* = 10) y PureSVD **menos** factores (256): la señal propia del dominio es más fuerte y conviene un modelo más enfocado. EASE elige el mismo λ en ambos grupos.

## 5. Resultados en prueba — variante A

### Ranking (K = 10)

| Modelo | Precision@10 | Recall@10 | **nDCG@10** | HitRate@10 | MAP@10 | MRR@10 |
|---|---|---|---|---|---|---|
| Popularidad | 0.0073 | 0.0512 | 0.0230 | 0.0701 | 0.0126 | 0.0168 |
| ItemKNN | 0.0228 | 0.1490 | 0.0793 | 0.2044 | 0.0505 | 0.0686 |
| PureSVD | 0.0351 | 0.2311 | 0.1431 | 0.3067 | 0.1025 | 0.1386 |
| **EASE** | **0.0440** | **0.2897** | **0.1737** | **0.3733** | **0.1229** | **0.1613** |

### Otros cortes

| Modelo | Recall@5 | nDCG@5 | Recall@20 | nDCG@20 |
|---|---|---|---|---|
| Popularidad | 0.0240 | 0.0138 | 0.1209 | 0.0422 |
| ItemKNN | 0.0836 | 0.0565 | 0.2521 | 0.1079 |
| PureSVD | 0.1562 | 0.1173 | 0.3360 | 0.1723 |
| EASE | 0.1890 | 0.1386 | 0.4165 | 0.2090 |

### Más allá de la precisión

| Modelo | Cobertura@10 | Novedad@10 (bits) | ILD@10 |
|---|---|---|---|
| Popularidad | 3.4 % | 3.49 | 0.977 |
| ItemKNN | 46.2 % | 4.04 | 0.971 |
| PureSVD | 29.5 % | 4.54 | 0.965 |
| EASE | 44.8 % | 4.42 | 0.964 |

### Predicción de calificación

| Modelo | RMSE | MAE |
|---|---|---|
| Media global | 1.133 | 0.891 |
| Sesgos | 0.819 | 0.629 |
| ItemKNN con sesgos | **0.805** | **0.617** |

## 6. Comparación con el experimento 1

| Métrica (mejor modelo, EASE) | Grupo 3–4 | Grupo ≥ 5 | Cambio |
|---|---|---|---|
| nDCG@10 | 0.1374 | 0.1737 | **+26 %** |
| HitRate@10 | 0.2591 | 0.3733 | +44 % |
| Recall@10 | 0.2591 | 0.2897 | +12 % |
| MRR@10 | 0.1004 | 0.1613 | +61 % |
| RMSE (ItemKNN con sesgos) | 0.864 | 0.805 | −7 % |
| nDCG@10 de Popularidad | 0.0269 | 0.0230 | −15 % |

## 7. Interpretación

* **Más historial mexicano, mejores recomendaciones.** EASE acierta al menos una película que le gustó al usuario entre las 10 primeras en el **37 % de los casos** (26 % en el grupo ocasional), y el primer acierto aparece más arriba (MRR +61 %). En nDCG@10, EASE es **7.5 veces** la popularidad.
* **El mismo orden de modelos, con diferencias significativas:** EASE > PureSVD > ItemKNN > Popularidad (*p* < 10⁻⁵⁰ en cada comparación, Wilcoxon pareado). EASE es el mejor algoritmo en ambos perfiles de usuario.
* **La popularidad funciona peor con el asiduo** (0.023 vs 0.027): quien ve mucho cine mexicano ya vio los éxitos y lo que le falta por descubrir es menos obvio. Justo en este grupo la personalización aporta más.
* **Cobertura alta:** EASE recomienda el 45 % del catálogo (popularidad, el 3 %).
* **Predicción de estrellas:** con más películas propias, los vecinos sí aportan (0.819 → 0.805) y el error baja 7 % respecto al grupo ocasional.
* **Respuesta a la pregunta 1:** tener ≥ 5 películas mexicanas mejora el nDCG@10 en 26 %, pero el ocasional ya obtiene el 79 % de ese desempeño gracias a su historial de cine general.

## 8. Variantes con sentimiento (B: BETO, C: JEV)

**Pendiente** de los archivos de los experimentos 4 y 5. Este es el grupo donde se espera el mayor efecto: 119,872 reseñas en español y más películas mexicanas reseñadas por usuario en entrenamiento.

| Modelo | nDCG@10 A | nDCG@10 B | nDCG@10 C | λ (B / C) | *p* B vs A | *p* C vs A |
|---|---|---|---|---|---|---|
| ItemKNN | 0.0793 | | | | | |
| PureSVD | 0.1431 | | | | | |
| EASE | 0.1737 | | | | | |

| Modelo | RMSE A | RMSE B | RMSE C |
|---|---|---|---|
| Sesgos | 0.819 | | |
| ItemKNN con sesgos | 0.805 | | |

## 9. Archivos generados (`resultados/exp2/`)

Los mismos que en el experimento 1: `descripcion_datos.csv`, `ajuste_validacion_*.csv/.png`, `ranking_test.csv`, `rating_test.csv`, `por_usuario_test.parquet`, `rating_detalle_test.parquet`, `significancia.csv`, `hiperparametros.json`, `metricas_test_variante_A.png` y, con sentimiento, `ajuste_lambda_validacion.csv/.png`.

## 10. Limitaciones

Las mismas que el experimento 1. Además, los usuarios con muchísimas reseñas (hasta 279 películas mexicanas) pesan igual que los demás en el promedio por usuario, pero aportan más pares de prueba.

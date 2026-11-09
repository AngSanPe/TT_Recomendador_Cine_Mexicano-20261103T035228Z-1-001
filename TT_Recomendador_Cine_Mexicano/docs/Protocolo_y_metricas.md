# Protocolo de evaluación y métricas

Este documento es común a los cinco experimentos. Cada documento de experimento lo resume y remite aquí para el detalle.

## 1. Qué se considera una recomendación correcta

El sistema recomienda **películas mexicanas** (catálogo de 878 títulos). Para saber si una recomendación es correcta se usa una evaluación *offline*: se esconden algunas películas que el usuario efectivamente vio y se mide si el sistema las vuelve a encontrar.

* **Conjunto de prueba (`test`)**: por usuario, el 20 % de las películas mexicanas que reseñó **y calificó** (mínimo 1, solo si tiene al menos 2, para que siempre quede una en entrenamiento).
* **Relevante**: película de prueba con **≥ 3.5 ★**. Es decir, no basta con que la haya visto: tiene que haberle gustado.
* **Candidatas**: las 878 películas del catálogo menos las que el usuario ya vio en entrenamiento. Se ordena el catálogo completo (sin muestrear negativos), que es el protocolo más exigente y el recomendado en la literatura reciente (Krichene y Rendle, 2020).

La partición se hace una sola vez (semilla 42, notebook 00) y la comparten todos los experimentos. Así, las diferencias entre experimentos se deben a los modelos y no a la suerte de la partición.

### Prevención de fuga de información

* Un par usuario–película que va a `val` o `test` se retira **completo**: también su entrada en el historial general.
* El análisis de sentimiento solo modifica pares de entrenamiento. La verdad de referencia (estrellas de prueba) nunca se toca.
* El afinado opcional de BETO usa reseñas de **otros** usuarios, que no aparecen en los experimentos.

## 2. Ajuste de hiperparámetros y evaluación final

1. **Validación (`val`)**: con *n* candidatas, se aparta otro 20 % (si después de `test` quedan ≥ 2). Se entrena con `train` y se elige el hiperparámetro con mejor **nDCG@10** en `val` (o menor **RMSE** en los modelos de predicción).
2. **Prueba (`test`)**: se reentrena con `train + val` y se mide **una sola vez**.
3. **Variantes con sentimiento**: con los hiperparámetros ya elegidos en la variante A, se elige en `val` el peso λ del sentimiento y se mide en `test`.

## 3. Métricas de ranking (top-K)

Se calculan por usuario y se promedian sobre los usuarios con al menos una película relevante en prueba. *K* ∈ {5, 10, 20}; el valor de referencia es **K = 10** (lo que cabe en una pantalla).

| Métrica | Pregunta que responde | Fórmula (por usuario) |
|---|---|---|
| **Precision@K** | De las K recomendadas, ¿cuántas le gustaron? | aciertos / K |
| **Recall@K** | De las que le gustaron, ¿cuántas encontré? | aciertos / relevantes |
| **HitRate@K** | ¿Acerté al menos una? | 1 si aciertos > 0 |
| **nDCG@K** | ¿Acerté y además arriba de la lista? | Σ rel_i / log₂(i+1), normalizado por el ideal |
| **MAP@K** | Precisión promedio en cada acierto | Σ Precision@i · rel_i / min(relevantes, K) |
| **MRR@K** | ¿Qué tan arriba está el primer acierto? | 1 / posición del primer acierto |

nDCG@10 es la métrica principal: combina si se acierta y en qué posición.

**Cómo leer los valores.** Con 878 candidatas y típicamente 1 relevante por usuario, un orden al azar tendría HitRate@10 ≈ 10/878 ≈ 1.1 %. Valores de nDCG@10 entre 0.1 y 0.2 son altos para este protocolo de catálogo completo.

## 4. Métricas "más allá de la precisión"

| Métrica | Pregunta | Cálculo |
|---|---|---|
| **Cobertura@K** | ¿Qué parte del catálogo mexicano llega a recomendarse? | películas distintas en todas las listas / 878 |
| **Novedad@K** | ¿Recomienda lo obvio o descubre? | media de −log₂(popularidad), en bits; más alto = menos conocido |
| **ILD@K** | ¿Las listas son variadas? | 1 − similitud coseno media (sinopsis + géneros) entre pares de la lista |

Son importantes para el objetivo del trabajo: un recomendador de cine mexicano que solo sugiere *Roma* y *Amores perros* acierta seguido, pero no sirve para descubrir cine nacional.

## 5. Predicción de calificación (solo filtrado colaborativo)

Además del ranking, los experimentos 1 y 2 estiman las estrellas de las películas retenidas y reportan:

* **RMSE** = √(media de (predicción − real)²), penaliza errores grandes.
* **MAE** = media de |predicción − real|, en estrellas.

Modelos: media global (referencia), sesgos de usuario y película (μ + b_u + b_i) y vecinos sobre los residuales (Item-kNN con sesgos).

## 6. Significancia estadística

Para afirmar que el sentimiento mejora (o no) la recomendación se usa la **prueba de rangos con signo de Wilcoxon**, pareada por usuario, sobre nDCG@10 y Recall@10 de cada variante (B, C) contra la línea base (A), para cada modelo. Es no paramétrica (las métricas por usuario no son normales: la mayoría vale 0). Se reporta el valor *p*, la mejora relativa y cuántos usuarios mejoran o empeoran. Umbral: *p* < 0.05.

## 7. Variantes de la señal de preferencia

| Variante | Preferencia `p` de un par usuario–película |
|---|---|
| **A** (base) | estrellas/5; sin estrellas: 0.9 si dio *like*, 0.6 si no |
| **B** (BETO) | igual que A, salvo en películas mexicanas reseñadas en español: `p = λ·(estrellas/5) + (1−λ)·(3 + 2s)/5`; sin estrellas, `p = (3 + 2s)/5` |
| **C** (JEV) | igual que B, con el puntaje `s` de JEV |

`s ∈ [-1, 1]` es el sentimiento de la reseña; `3 + 2s` lo lleva a la escala de estrellas (1 a 5). λ ∈ {0, 0.25, 0.5, 0.75, 1} se elige en validación. λ = 1 aísla el efecto de usar el sentimiento solo para imputar las reseñas sin estrellas; λ = 0 usa solo el sentimiento.

## 8. Evaluación de los analizadores de sentimiento (experimentos 4 y 5)

Se comparan contra las estrellas que el propio autor dio (referencia ruidosa): negativo ≤ 2 ★, neutral 2.5–3 ★, positivo ≥ 3.5 ★.

* **Exactitud** y **F1-macro** (promedio del F1 de las tres clases; no se deja engañar por el desbalance hacia positivo).
* **Kappa de Cohen**: acuerdo corregido por azar.
* **Correlación de Spearman** entre `s` y las estrellas: si el puntaje continuo ordena bien las reseñas.
* **MAE en estrellas** de `3 + 2s`.
* Entre BETO y JEV: acuerdo de etiquetas y kappa sobre las mismas reseñas.

## Referencias

* Cañete, J. et al. (2020). *Spanish Pre-Trained BERT Model and Evaluation Data*. PML4DC @ ICLR.
* Cremonesi, P., Koren, Y. y Turrin, R. (2010). *Performance of recommender algorithms on top-N recommendation tasks*. RecSys.
* Krichene, W. y Rendle, S. (2020). *On Sampled Metrics for Item Recommendation*. KDD.
* Koren, Y. (2010). *Factor in the neighbors: Scalable and accurate collaborative filtering*. TKDD.
* Pérez, J. M. et al. (2021). *pysentimiento: A Python Toolkit for Sentiment Analysis and SocialNLP tasks*. arXiv:2106.09462.
* Sarwar, B. et al. (2001). *Item-based collaborative filtering recommendation algorithms*. WWW.
* Steck, H. (2019). *Embarrassingly Shallow Autoencoders for Sparse Data*. WWW.
* Reimers, N. y Gurevych, I. (2019). *Sentence-BERT*. EMNLP.

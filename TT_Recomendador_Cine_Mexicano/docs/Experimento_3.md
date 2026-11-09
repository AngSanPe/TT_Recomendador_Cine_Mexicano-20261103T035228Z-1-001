# Experimento 3 · Filtrado basado en contenido

**Notebook:** `notebooks/03_experimento3_basado_en_contenido.ipynb` · **Resultados:** `resultados/exp3/` · **Protocolo y métricas:** [Protocolo_y_metricas.md](Protocolo_y_metricas.md)

**Estado:** variante A ejecutada para ambos grupos, con TF-IDF y con embeddings. Variantes B (BETO) y C (JEV) se ejecutan solas al volver a correr el notebook cuando existan los archivos de sentimiento.

## 1. Objetivo

Recomendar películas mexicanas **parecidas en contenido** a las que el usuario ya disfrutó, sin usar lo que hicieron otros usuarios. Es el enfoque complementario al filtrado colaborativo: no necesita que una película tenga muchas vistas para recomendarla, así que puede sacar a la luz cine mexicano poco conocido, y cada recomendación se puede explicar ("porque te gustó X").

**Preguntas.**
1. ¿Qué tan bien recomienda el contenido frente al colaborativo (experimentos 1 y 2), con los mismos usuarios y la misma partición?
2. ¿Qué representación del texto funciona mejor: TF-IDF o embeddings de un modelo de lenguaje?
3. ¿Cuánto aporta la sinopsis por sí sola y cuánto los metadatos (género, década, director)?
4. ¿Ayuda el sentimiento de las reseñas a construir un mejor perfil del usuario?

**Hipótesis.** El contenido queda por debajo del colaborativo en precisión, pero lo supera en cobertura y novedad.

## 2. Datos

Mismos usuarios, interacciones y partición que los experimentos 1 (grupo 3–4, 11,276 usuarios evaluados) y 2 (grupo ≥ 5, 13,469 usuarios evaluados). Además:

* `items_contenido.parquet`: 98,798 películas (todo lo que aparece en algún historial + el catálogo), **51,466 con sinopsis informativa** (89 % de las interacciones tienen película con sinopsis). Limpieza en [Datos_y_limpieza.md](Datos_y_limpieza.md).
* Géneros de IMDb (para el catálogo mexicano, 832 de 878), año de estreno y directores (solo conocidos para el catálogo mexicano).

## 3. Representación de las películas

Cada película es un vector formado por bloques, cada uno normalizado y multiplicado por su peso:

| Bloque | Cómo se construye | Peso |
|---|---|---|
| **Texto: TF-IDF** | sinopsis limpia (inglés); unigramas y bigramas, sin *stopwords*, sin acentos, TF sublineal; vocabulario de 50,000 términos | 1 |
| **Texto: embeddings** | `paraphrase-multilingual-MiniLM-L12-v2` (Sentence-BERT multilingüe, 384 dimensiones), calculados una vez (≈ 4 min en la GPU de una Mac) y guardados en `datos/limpios/embeddings/` | 1 |
| Géneros | one-hot de los géneros de IMDb | `generos` |
| Década | one-hot de la década de estreno | `decada` |
| Directores | one-hot de los directores | `directores` |

**Perfil del usuario:** suma de los vectores de las películas que vio, con peso `w = p − 0.5` (lo que calificó alto acerca el perfil, lo que calificó bajo lo aleja), y las películas mexicanas multiplicadas por `peso_mx`. **Puntaje:** similitud coseno entre el perfil y cada película del catálogo no vista.

**Modelos evaluados:** `Contenido-TFIDF` y `Contenido-Embeddings` (texto + metadatos), y sus versiones `(solo texto)` para aislar el aporte de la sinopsis. Popularidad como referencia común con los experimentos 1–2.

## 4. Ajuste de hiperparámetros (validación, nDCG@10)

**Barrido preliminar** (versión anterior del notebook, grupo 3–4, TF-IDF, metadatos con peso 0.3): centrar los pesos en la media de cada usuario fue **siempre peor** que centrar en 0.5 (p. ej., 0.027 vs 0.039 con `peso_mx` = 50), y sin metadatos el modelo quedaba por debajo de la popularidad. Por eso la rejilla final fija el centrado en 0.5.

**Rejilla final** (36 combinaciones por representación y grupo): `generos` ∈ {0.3, 0.6} × `decada` ∈ {0.25, 0.5, 1.0} × `directores` ∈ {1, 2} × `peso_mx` ∈ {50, 200, 1000}. Extracto (mejor valor por fila):

| Configuración | 3–4 TF-IDF | 3–4 Emb. | ≥ 5 TF-IDF | ≥ 5 Emb. |
|---|---|---|---|---|
| Solo texto | 0.0128 | 0.0140 | 0.0182 | 0.0168 |
| g = 0.3, d = 0.25, dir = 1 | 0.0526 | 0.0511 | **0.0678** | 0.0639 |
| g = 0.6, d = 0.5, dir = 1 | **0.0529** | 0.0526 | 0.0658 | 0.0655 |
| g = 0.6, d = 0.5, dir = 2 | 0.0528 | **0.0527** | 0.0662 | **0.0665** |
| g = 0.6, d = 1.0, dir = 1 | 0.0448 | 0.0460 | 0.0582 | 0.0581 |
| *Popularidad (referencia)* | 0.0248 | | 0.0209 | |

Elegidos: grupo 3–4 → TF-IDF (0.6, 0.5, 1, `peso_mx` 200), Embeddings (0.6, 0.5, 2, 1000); grupo ≥ 5 → TF-IDF (0.3, 0.25, 1, 200), Embeddings (0.6, 0.5, 2, 200).

Lectura del ajuste:
* La **década** ayuda con peso moderado (0.25–0.5); con peso 1 domina el perfil y empeora (0.053 → 0.045).
* El **director** pesa mucho (1–2): quien disfrutó una película de un autor suele disfrutar otras del mismo.
* `peso_mx` de 200 o más es mejor que 50: para el contenido, las **películas mexicanas que el usuario vio** describen su gusto por el cine mexicano mucho mejor que su historial general.

## 5. Resultados en prueba — variante A

### Ranking (K = 10)

| Grupo | Modelo | Precision@10 | Recall@10 | **nDCG@10** | HitRate@10 | MRR@10 |
|---|---|---|---|---|---|---|
| 3–4 | Popularidad | 0.0064 | 0.0638 | 0.0269 | 0.0638 | 0.0160 |
| 3–4 | TF-IDF (solo texto) | 0.0027 | 0.0271 | 0.0146 | 0.0271 | 0.0109 |
| 3–4 | Embeddings (solo texto) | 0.0032 | 0.0321 | 0.0176 | 0.0321 | 0.0133 |
| 3–4 | **TF-IDF + metadatos** | 0.0105 | 0.1046 | 0.0623 | 0.1046 | 0.0493 |
| 3–4 | **Embeddings + metadatos** | **0.0111** | **0.1109** | **0.0641** | **0.1109** | **0.0497** |
| ≥ 5 | Popularidad | 0.0073 | 0.0512 | 0.0230 | 0.0701 | 0.0168 |
| ≥ 5 | TF-IDF (solo texto) | 0.0054 | 0.0351 | 0.0211 | 0.0518 | 0.0209 |
| ≥ 5 | Embeddings (solo texto) | 0.0047 | 0.0319 | 0.0182 | 0.0460 | 0.0172 |
| ≥ 5 | **TF-IDF + metadatos** | **0.0183** | **0.1199** | **0.0756** | **0.1645** | **0.0738** |
| ≥ 5 | **Embeddings + metadatos** | 0.0179 | 0.1178 | 0.0740 | 0.1610 | 0.0716 |

### Más allá de la precisión

| Grupo | Modelo | Cobertura@10 | Novedad@10 (bits) | ILD@10 |
|---|---|---|---|---|
| 3–4 | Popularidad | 2.4 % | 4.19 | 0.963 |
| 3–4 | TF-IDF + metadatos | 99.5 % | 8.82 | 0.940 |
| 3–4 | Embeddings + metadatos | 99.5 % | 9.01 | 0.954 |
| 3–4 | *EASE (exp. 1)* | *37.7 %* | *5.33* | *0.966* |
| ≥ 5 | Popularidad | 3.4 % | 3.49 | 0.977 |
| ≥ 5 | TF-IDF + metadatos | 99.7 % | 6.66 | 0.951 |
| ≥ 5 | Embeddings + metadatos | 97.9 % | 6.95 | 0.954 |
| ≥ 5 | *EASE (exp. 2)* | *44.8 %* | *4.42* | *0.964* |

### Contenido frente a colaborativo (nDCG@10)

| Grupo | Mejor contenido | Mejor colaborativo (EASE) | Contenido / EASE | Contenido / Popularidad |
|---|---|---|---|---|
| 3–4 | 0.0641 (Embeddings) | 0.1374 | 47 % | ×2.4 |
| ≥ 5 | 0.0756 (TF-IDF) | 0.1737 | 44 % | ×3.3 |

Todas las diferencias contenido vs. EASE y contenido vs. popularidad son significativas (*p* < 10⁻⁵⁹, Wilcoxon pareado por usuario).

### Ejemplo de recomendación explicable (grupo ≥ 5)

| Usuario | Recomendada | Porque se parece a |
|---|---|---|
| A | *El diablo entre las piernas*, *Castillo de la pureza*, *El coronel no tiene quien le escriba*, *La viuda negra* | *El lugar sin límites* |
| A | *Tiempo de morir* | *Cadena perpetua* |
| B | *La leyenda del Chupacabras* | *La leyenda de La Llorona* |
| B | *La ley de Herodes*, *Un mundo maravilloso* | *El infierno* |

(Títulos traducidos de la salida del notebook, que usa los títulos en inglés de Letterboxd.) El usuario A recibe cine de Arturo Ripstein porque disfrutó *El lugar sin límites*; el B, la saga animada de *Leyendas* y la trilogía política de Luis Estrada.

## 6. Interpretación

* **La sinopsis sola no basta.** Tanto TF-IDF como embeddings, usando solo el texto, quedan **por debajo de la popularidad** en ambos grupos (nDCG@10 0.015–0.021 vs 0.023–0.027). Una sinopsis describe la trama, pero el gusto depende también de quién la dirige, de cuándo es y del género.
* **Con metadatos, el contenido sí funciona:** ×2.4 (ocasional) y ×3.3 (asiduo) sobre la popularidad, y entre 10 % y 12 % de recall a 10 en un catálogo de 878 películas. Los metadatos multiplican por 3.6–4.3 el nDCG del texto solo.
* **TF-IDF y embeddings quedan prácticamente empatados** (diferencias de 1.6–1.8 milésimas, con signo distinto en cada grupo; *p* ≈ 0.02). Los embeddings encuentran vecinos semánticamente más sensatos (para *El laberinto del fauno*: *Alucarda*, *La tía Alejandra*, *Come Play With Me*; TF-IDF devuelve títulos sin relación de tono que solo comparten palabras sueltas), pero una vez que entran los metadatos, la calidad de la recomendación es la misma. Con sinopsis cortas y de un solo idioma, TF-IDF es suficiente y mucho más barato.
* **Frente al colaborativo:** el contenido logra ~45 % del nDCG de EASE. Es la ventaja de aprender de millones de coincidencias entre usuarios.
* **Pero descubre mucho más:** recomienda el **98–100 % del catálogo** (EASE, 38–45 %; popularidad, 2–3 %) y con mucha mayor novedad (6.7–9.0 bits vs 4.4–5.3 de EASE): sugiere cine mexicano poco visto. Sus listas son algo menos diversas internamente (ILD 0.94–0.95 vs 0.96–0.97), lo esperable en un método que busca parecidos.
* **Más historial mexicano ayuda también al contenido** (+18 % de nDCG del grupo 3–4 al ≥ 5).

**Conclusión del experimento.** Colaborativo y contenido son complementarios: el primero acierta más; el segundo cubre el catálogo, descubre títulos poco conocidos y explica sus recomendaciones. Un sistema **híbrido** (p. ej., EASE para ordenar y contenido para diversificar o para películas sin vistas) es la extensión natural, fuera del alcance de estos experimentos.

## 7. Variantes con sentimiento (B: BETO, C: JEV)

**Pendiente** de los archivos de los experimentos 4 y 5. En este modelo el sentimiento cambia el **peso** con el que cada película reseñada entra al perfil del usuario: una reseña entusiasta acerca más el perfil a esa película que una tibia, aunque ambas tengan 4 ★. Como `peso_mx` es alto, las películas mexicanas reseñadas dominan el perfil y el sentimiento puede tener aquí un efecto visible.

| Grupo | Modelo | nDCG@10 A | B | C | λ (B / C) | *p* B vs A | *p* C vs A |
|---|---|---|---|---|---|---|---|
| 3–4 | TF-IDF + metadatos | 0.0623 | | | | | |
| 3–4 | Embeddings + metadatos | 0.0641 | | | | | |
| ≥ 5 | TF-IDF + metadatos | 0.0756 | | | | | |
| ≥ 5 | Embeddings + metadatos | 0.0740 | | | | | |

## 8. Archivos generados (`resultados/exp3/`)

| Archivo | Contenido |
|---|---|
| `ajuste_validacion.csv` | las 2 × 2 × 39 configuraciones evaluadas en validación |
| `ranking_test.csv` | métricas finales por grupo, modelo y variante |
| `por_usuario_test.parquet` | métricas por usuario (pruebas estadísticas) |
| `significancia.csv` | Wilcoxon de cada variante contra A |
| `hiperparametros.json` | configuración y λ elegidos |
| `metricas_test_variante_A.png` | gráfica de la sección 5 |
| `ajuste_lambda_validacion.csv` | sensibilidad a λ (cuando haya sentimiento) |

## 9. Limitaciones

* Las sinopsis del historial general se enlazaron por título y año (≈ 89 % de las interacciones); un enlace erróneo introduce ruido en el perfil.
* Directores solo para el catálogo mexicano: el historial general aporta texto, géneros y década, pero no autor.
* El texto de la sinopsis está casi siempre en inglés; un modelo en español (o las sinopsis en español del catálogo) podría probarse como extensión.

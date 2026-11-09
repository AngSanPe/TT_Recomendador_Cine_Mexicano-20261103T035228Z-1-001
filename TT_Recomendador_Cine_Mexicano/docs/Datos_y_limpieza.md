# Datos, recolección y limpieza

Documenta de dónde salen los datos, qué scraper produjo cada archivo, cómo se limpiaron y cómo se partieron para los experimentos. El código está en `src/recomendador/limpieza.py` y `src/recomendador/preparacion.py`; el proceso ejecutado, con sus salidas, en `notebooks/00_preparacion_y_limpieza.ipynb`.

## 1. Recolección (`scrapers/`)

| Paso | Herramienta | Fuente | Resultado (`datos/crudos/`) |
|---|---|---|---|
| 1. Lista de películas mexicanas | `peliculas_mexicanas.txt` (56 curadas + listas públicas) y catálogo de TMDb (`with_origin_country=MX`) | TMDb API, letterboxd.com/tmdb/&lt;id&gt; | tabla `catalogo` en `letterboxd.db` |
| 2. Reseñas | `letterboxd_scraper recolectar` | letterboxd.com/film/&lt;slug&gt;/reviews/ | tabla `resenas` (710,045 reseñas, 340,692 usuarios, 868 películas) |
| 3. Sinopsis del catálogo | `letterboxd_scraper sinopsis` | TMDb (es-MX → es-ES) y ficha de Letterboxd (en) | tabla `peliculas` (878) y `sinopsis_peliculas.csv` |
| 4. Historial de usuarios | `user_films_scraper.py` (`run_scrapers.sh`) | letterboxd.com/&lt;usuario&gt;/films/ | `historial_3_a_4.db`, `historial_min5.db` |
| 5. Catálogo general | archivo con el formato de los datasets públicos de IMDb (`title.basics` + `title.ratings`) | IMDb | `imdb_movies.csv` (757,649 películas con géneros) |
| 6. Sinopsis del catálogo general | `letterboxd_scraper sinopsis-imdb` | TMDb `/find/<tconst>` | `sinopsis_imdb.csv` / `.db` (380,783 con sinopsis) |

**Muestreo de usuarios (paso 4).** De `letterboxd.db` se tomaron al azar 10 mil usuarios con 3–4 películas mexicanas reseñadas y 10 mil con 5 o más (en varias corridas del scraper; quedaron 19,790 y 19,784 usuarios con historial, sin traslape entre grupos). De cada uno se guardaron las películas visibles en su perfil con sus estrellas y *like*.

**Consideraciones éticas y técnicas** (detalle en `scrapers/README_scraper_letterboxd.md`):
* Se respeta `robots.txt`: no se usan los listados por país, género o década que el sitio prohíbe.
* Ritmo cortés (2.5–5 s entre peticiones, una a la vez, espera exponencial ante 403/429).
* Los nombres de usuario son públicos, pero para publicar resultados conviene seudonimizarlos o reportar solo agregados.

### Limitaciones conocidas de los datos

| Limitación | Efecto | Cómo se trató |
|---|---|---|
| Letterboxd corta las reseñas de una película en la página 256 (3,072 reseñas) | las películas más populares están submuestreadas | se documenta; de las 56 más conocidas, 33 topan el límite |
| El historial de cada usuario es casi siempre **parcial**: Cloudflare solo deja ver la primera página de `/films/` (72 películas, las más recientes) | el historial es una ventana reciente del gusto, no la vida completa del usuario | se usa tal cual; 85–93 % de los perfiles quedaron "parciales" |
| El texto de la reseña es el del listado (máx. ~800 caracteres) | las reseñas muy largas llegan recortadas | suficiente para sentimiento (la mediana es 115 caracteres) |
| 23 de las 878 películas no tienen "Mexico" entre sus países en Letterboxd (p. ej. *Roma* aparece como UK/USA) | criterio de "película mexicana" depende de la fuente | se conservan (vienen de TMDb con origen MX o de la lista curada); la columna `es_mexicana_segun_letterboxd` permite filtrarlas |
| El enlace slug de Letterboxd → IMDb es por título y año | títulos homónimos pueden enlazarse mal | cubre 89 % de las interacciones con sinopsis; se documenta |

## 2. Limpieza de texto (`src/recomendador/limpieza.py`)

Ruido medido en 20 mil reseñas en español: emojis 9.3 %, saltos de línea 17.8 %, letras repetidas 2.3 %, hashtags 0.3 %, HTML/URLs/menciones < 0.05 %.

La limpieza depende de quién lee el texto:

| Regla | BETO (`texto_beto`) | LLM JEV (`texto_llm`) | Embeddings / TF-IDF (`sinopsis`) |
|---|---|---|---|
| Normalización Unicode NFC, espacios no estándar | ✔ | ✔ | ✔ |
| Entidades y etiquetas HTML, URLs | se quitan | se quitan | se quitan |
| Menciones `@usuario`; `#hashtag` → `hashtag` | ✔ | ✔ | — |
| Letras repetidas (`buenísimaaaaa` → `buenísimaaa`) y signos (`!!!!!` → `!!!`) | ✔ | ✔ | — |
| Saltos de línea → espacio | ✔ | ✔ | ✔ |
| Emojis | los ~85 más frecuentes se traducen a palabra (😭 → *llorando*, 🔥 → *excelente*, 🇲🇽 → *México*); el resto se quita | se conservan | — |
| Créditos ("Written by…"), sinopsis entre comillas | — | — | se quitan |
| Sinopsis de relleno o genéricas | — | — | se descartan |
| Minúsculas, acentos, *stopwords* | **no** se tocan | **no** se tocan | solo dentro del vectorizador TF-IDF |

**Por qué así.**
* BETO y los modelos de embeddings tienen su propio tokenizador, entrenado con texto con mayúsculas, acentos y puntuación: quitarlos destruye información (p. ej. "¡¡¡QUÉ MALA!!!" vs. "que mala").
* El vocabulario de BETO no contiene emojis: los vuelve `[UNK]`. Traducirlos conserva su carga emocional. Un LLM sí los entiende, así que para él se dejan.
* Una sinopsis "informativa" debe describir la trama: se descartan las de menos de 40 caracteres y las que aparecen idénticas en 3 o más películas ("Mexican feature film", "Película erótica francesa", "1962 Japanese movie"), que no distinguen una película de otra y distorsionarían los embeddings.
* Para las sinopsis se prefiere el **inglés**: es el único idioma disponible para casi todo el historial general (50,963 de 51,466 sinopsis útiles); así TF-IDF compara palabras del mismo idioma. Para el catálogo mexicano se guardan ambas versiones limpias (`sinopsis_es_limpia`, `sinopsis_en_limpia`). El modelo de embeddings elegido es multilingüe, por si se quiere usar el español.

## 3. Datos limpios (`datos/limpios/`)

| Archivo | Filas | Contenido |
|---|---|---|
| `catalogo_mx.parquet` | 878 | película, título (en/es), año, directores, países, `tconst`, géneros IMDb (832), sinopsis limpias |
| `interacciones_g34.parquet` | 1,659,339 | usuario × película del grupo 3–4: calificación, *like*, si tiene reseña, si es mexicana, **partición** |
| `interacciones_g5.parquet` | 1,844,900 | ídem, grupo ≥ 5 |
| `items_contenido.parquet` | 98,798 | toda película de los historiales + catálogo; 51,466 con sinopsis informativa |
| `embeddings/sinopsis_paraphrase-multilingual-MiniLM-L12-v2.npz` | 51,466 × 384 | embeddings normalizados de las sinopsis (float16) |
| `resenas_sentimiento.parquet` | 151,516 | reseñas en español de los usuarios de ambos grupos (31,644 del grupo 3–4; 119,872 del ≥ 5), con `texto_beto` y `texto_llm` |
| `resenas_afinado_beto.parquet` | 152,187 | reseñas en español con estrellas de 95,934 usuarios **ajenos** a los experimentos (afinado de BETO) |
| `sentimiento/` | — | aquí dejan su salida los notebooks 04 (BETO) y 05 (JEV) |
| `reporte_preparacion.json` | — | todos los conteos de la preparación |

### Construcción de las interacciones

Para cada usuario se unen dos fuentes:
1. Sus **reseñas de cine mexicano** (`letterboxd.db`): estrellas y texto.
2. Su **historial general** (`historial_*.db`): estrellas y *like* de sus películas recientes, de cualquier país.

Si un par usuario–película aparece en ambas, cuenta una vez y manda la calificación de la reseña más reciente. El historial general es lo que permite al sistema conocer el gusto del usuario más allá del cine mexicano.

| | Grupo 3–4 | Grupo ≥ 5 |
|---|---|---|
| Usuarios | 19,790 | 19,784 |
| Películas distintas | 72,240 | 67,786 |
| Interacciones | 1,659,339 | 1,844,900 |
| Densidad de la matriz | 0.116 % | 0.138 % |
| Interacciones con cine mexicano | 95,799 | 239,442 |
| …con reseña escrita | 66,339 | 198,139 |
| Películas del catálogo vistas por alguien | 828 | 861 |
| % con estrellas | 90.9 % | 92.5 % |

El catálogo tiene cola larga: el 10 % más visto (86 películas) concentra el 47 % de las interacciones con cine mexicano.

## 4. Partición entrenamiento / validación / prueba

Semilla 42. Candidatas: películas mexicanas que el usuario reseñó **y calificó**. Con *n* candidatas:

* `test` = max(1, round(0.2·n)), solo si n ≥ 2.
* `val` = mismo tamaño, si después de `test` quedan ≥ 2.
* Todo lo demás, incluido el historial general, es `train`.

| | Grupo 3–4 | Grupo ≥ 5 |
|---|---|---|
| Pares en `test` | 19,098 | 37,225 |
| …relevantes (≥ 3.5 ★) | 11,276 | 20,859 |
| Usuarios evaluables en `test` | 11,276 | 13,469 |
| Pares en `val` | 18,335 | 37,120 |

(Un usuario es evaluable en ranking si al menos una de sus películas de prueba es relevante.)

Detalle del protocolo y las métricas: [Protocolo_y_metricas.md](Protocolo_y_metricas.md).

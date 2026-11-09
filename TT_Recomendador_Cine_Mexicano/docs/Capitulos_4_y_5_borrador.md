# CAPÍTULO 4. DESARROLLO

Este capítulo describe cómo se construyó el conjunto de datos que sustenta el sistema: de dónde proviene cada dato, cómo se limpió, cómo se clasificó y organizó, y qué revela el análisis exploratorio. El código que ejecuta cada paso se detalla en el Capítulo 5.

## 4.1. Extracción de datos

El desarrollo inicia con la recolección de datos de tres fuentes: dos de ellas aportan información de las películas (IMDb y TMDB) y una aporta la percepción del público (Letterboxd). La Tabla 7 resume cada paso de la extracción.

**Tabla 7. Pasos de la extracción de datos.**

| Paso | Herramienta | Fuente | Resultado |
|---|---|---|---|
| 1. Catálogo general | Archivo con el formato de los datasets públicos de IMDb (`title.basics`, `title.ratings`) | IMDb | 757,649 películas con género y año |
| 2. Sinopsis del catálogo general | Módulo `sinopsis-imdb` del scraper (consulta `/find/<tconst>` en TMDB) | TMDB | 380,783 películas con sinopsis |
| 3. Películas mexicanas | Lista semilla curada (56 títulos) y *discover* de TMDB con `with_origin_country=MX`; resolución a Letterboxd mediante `letterboxd.com/tmdb/<id>` | TMDB y Letterboxd | 878 películas mexicanas |
| 4. Sinopsis del catálogo mexicano | Módulo `sinopsis` del scraper (TMDB es-MX → es-ES; ficha de Letterboxd en inglés como respaldo) | TMDB y Letterboxd | 878 películas con sinopsis |
| 5. Reseñas | Módulo `recolectar` del scraper | letterboxd.com/film/\<slug\>/reviews/ | 710,045 reseñas de 340,692 usuarios sobre 868 películas |
| 6. Historial de usuarios | `user_films_scraper.py` | letterboxd.com/\<usuario\>/films/ | 19,790 usuarios (grupo 3–4) y 19,784 (grupo ≥ 5) con su historial |

### 4.1.1. Datos de películas

El catálogo global se obtuvo de IMDb, cuyo identificador `tconst` es el identificador canónico de una película en este trabajo (regla de negocio RN15). Para cada película se conservan título, año y géneros. Como IMDb no proporciona sinopsis en sus datasets públicos, éstas se obtuvieron de la API de TMDB mediante el `tconst` (paso 2); el 50.2 % del catálogo (380,783 de 757,649) cuenta con sinopsis.

El subconjunto mexicano se construyó combinando una lista semilla de 56 películas curadas y el catálogo de TMDB filtrado por país de origen México. Cada película se vinculó con su ficha de Letterboxd (*slug*) y se guardaron título en inglés y español, año, directores, países de producción y calificación promedio. El resultado es un **catálogo de 878 películas mexicanas**. De ellas, 855 incluyen a México entre sus países de producción en Letterboxd; las 23 restantes (por ejemplo, *Roma*, registrada como coproducción del Reino Unido y Estados Unidos) se conservaron porque provienen de la lista curada o de TMDB con origen mexicano. La columna `es_mexicana_segun_letterboxd` permite filtrarlas.

### 4.1.2. Datos de redes sociales

Letterboxd ofrece una API únicamente por solicitud, y su documentación indica que, por el momento, no concede acceso a proyectos de análisis de datos, visualización o recomendación, entre otros usos (Letterboxd, s. f.). Dado que este trabajo constituye un proyecto de recomendación, no era elegible para dicho acceso. Se consideraron tres alternativas: (1) solicitar de todos modos el acceso oficial, descartada por la incertidumbre de la respuesta y los tiempos del proyecto; (2) usar las funciones de exportación de datos de cada cuenta, descartada porque requiere la participación activa de cada usuario y no permite construir un corpus de decenas de miles de personas; y (3) desarrollar un *scraper* propio. Se optó por la tercera porque permite adaptar la extracción a las necesidades específicas del proyecto y su implementación es sencilla.

El *scraper* se desarrolló en Python y realiza dos tareas:

1. **Reseñas por película.** Recorre las páginas de reseñas de cada una de las 878 películas y guarda, por reseña: identificador, usuario, calificación en estrellas (0.5 a 5), fecha, texto, número de *likes*, marca de *spoiler* e idioma detectado.
2. **Historial por usuario.** A partir de la tabla de reseñas se muestrearon al azar 10 mil usuarios con 3 o 4 películas mexicanas reseñadas y 10 mil con 5 o más. De cada perfil se extrajeron las películas visibles con su calificación y su *like*, de cualquier país. Este historial es indispensable para que el sistema conozca el gusto del usuario más allá del cine mexicano.

**Consideraciones éticas y técnicas.** Se respeta el archivo `robots.txt` del sitio, por lo que no se utilizan los listados por país, género o década que éste prohíbe. Las peticiones se realizan de una en una, con una pausa de 2.5 a 5 segundos entre ellas y espera exponencial ante respuestas 403 o 429. Los datos se emplean exclusivamente con fines académicos y el corpus resultante no se redistribuye.

**Limitaciones de la extracción.**

- Letterboxd corta el listado de reseñas de una película en la página 256 (3,072 reseñas); de las 56 películas más conocidas, 33 alcanzan ese límite, por lo que las más populares están submuestreadas.
- Cloudflare solo permite ver la primera página del historial de un perfil (72 películas, las más recientes). Entre 85 % y 93 % de los perfiles quedaron como "parciales": el historial es una ventana reciente del gusto del usuario, no su historia completa.
- El texto de la reseña corresponde al del listado (máximo cercano a 800 caracteres); la mediana es de 115 caracteres, suficiente para el análisis de sentimiento.

## 4.2. Transformación y limpieza de los datos

La limpieza se diseñó según quién consume el texto, porque un mismo texto no se prepara igual para un modelo de sentimiento que para un vectorizador. Se midió el ruido en una muestra de 20 mil reseñas en español: emojis en 9.3 %, saltos de línea en 17.8 %, letras repetidas en 2.3 %, *hashtags* en 0.3 % y HTML, URLs o menciones en menos de 0.05 %. La Tabla 8 resume las reglas aplicadas.

**Tabla 8. Reglas de limpieza según el consumidor del texto.**

| Regla | BETO | LLM (JEV) | Embeddings / TF-IDF (sinopsis) |
|---|---|---|---|
| Normalización Unicode NFC y espacios no estándar | Sí | Sí | Sí |
| Entidades y etiquetas HTML, URLs | Se quitan | Se quitan | Se quitan |
| Menciones `@usuario`; `#hashtag` → `hashtag` | Sí | Sí | — |
| Letras y signos repetidos (`buenísimaaaaa` → `buenísimaaa`) | Sí | Sí | — |
| Saltos de línea → espacio | Sí | Sí | Sí |
| Emojis | Los ~85 más frecuentes se traducen a palabra (😭 → *llorando*); el resto se quita | Se conservan | — |
| Créditos ("Written by…") y sinopsis entre comillas | — | — | Se quitan |
| Sinopsis de relleno o genéricas | — | — | Se descartan |
| Minúsculas, acentos y *stopwords* | No se tocan | No se tocan | Solo dentro del vectorizador TF-IDF |

Las decisiones principales fueron las siguientes:

- **No se normaliza el texto para BETO ni para los embeddings.** Sus tokenizadores se entrenaron con texto con mayúsculas, acentos y puntuación, y eliminarlos destruye información (no es lo mismo "¡¡¡QUÉ MALA!!!" que "que mala").
- **Los emojis se traducen para BETO**, porque su vocabulario no los contiene y los convertiría en `[UNK]`. Un LLM sí los interpreta, por lo que para él se conservan. En total, 14,745 reseñas tuvieron al menos un emoji traducido.
- **Solo se usan reseñas en español** (regla RN06): 151,516 reseñas de los usuarios de los experimentos, tras descartar 2 sin texto útil.
- **Las sinopsis deben describir la trama.** Se descartan las de menos de 40 caracteres y las que aparecen idénticas en tres o más películas (por ejemplo, "Mexican feature film"), pues no distinguen una película de otra y distorsionarían los embeddings. Quedaron 51,466 sinopsis útiles de 98,798 películas.
- **Idioma de las sinopsis.** Se prefiere el inglés porque es el único idioma disponible para casi todo el historial general (50,963 de 51,466 sinopsis útiles). Para el catálogo mexicano se conservan ambas versiones limpias.
- **Integración de interacciones.** Para cada usuario se unen sus reseñas de cine mexicano y su historial general. Si un par usuario–película aparece en ambas fuentes, cuenta una vez y prevalece la calificación de la reseña más reciente.

## 4.3. Clasificación de datos

Los datos del proyecto se clasifican en tres ejes: por naturaleza, por rol en el experimento y por etiqueta de sentimiento.

**Por naturaleza.**

| Tipo | Datos | Uso |
|---|---|---|
| Estructurados | Metadatos de películas (título, año, directores, géneros, países); calificaciones, *likes* e historiales | Matriz usuario–película; metadatos del enfoque de contenido |
| No estructurados | Texto de las reseñas; sinopsis | Análisis de sentimiento (BETO, JEV); representación semántica (TF-IDF, embeddings) |

**Por grupo de usuarios.** Los usuarios se clasifican según cuántas películas mexicanas reseñaron: **grupo 3–4** (espectador ocasional, 19,790 usuarios) y **grupo ≥ 5** (espectador asiduo, 19,784 usuarios, mediana de 7 películas mexicanas y hasta 279). Ambos grupos no se traslapan. Esta clasificación permite medir el efecto del historial en el dominio mexicano y es la base de los experimentos 1 y 2.

**Por partición experimental.** Cada par usuario–película se asigna a entrenamiento (`train`), validación (`val`) o prueba (`test`). Por usuario, el 20 % de las películas mexicanas que reseñó y calificó (mínimo una, solo si tiene al menos dos) va a `test`; otro 20 % a `val`, si después quedan al menos dos; el resto, incluido todo el historial general, a `train`. La partición se hizo una sola vez con semilla 42 y es compartida por todos los experimentos. Un par retirado a `val` o `test` se elimina completo, también del historial general, para evitar fuga de información.

**Tabla 9. Partición de los datos.**

| | Grupo 3–4 | Grupo ≥ 5 |
|---|---|---|
| Pares en `train` | 1,621,906 | 1,770,555 |
| Pares en `val` | 18,335 | 37,120 |
| Pares en `test` | 19,098 | 37,225 |
| Pares de prueba relevantes (≥ 3.5 ★) | 11,276 | 20,859 |
| Usuarios evaluables en `test` | 11,276 | 13,469 |

**Por polaridad.** Para evaluar los analizadores de sentimiento, las reseñas se etiquetan a partir de las estrellas de su autor: *negativa* (≤ 2 ★), *neutral* (2.5–3 ★) y *positiva* (≥ 3.5 ★). Entre las reseñas con estrellas, aproximadamente 59 % son positivas, 25 % neutrales y 17 % negativas, por lo que se usa F1-macro para no favorecer a la clase mayoritaria. Una película de prueba es **relevante** si su calificación es ≥ 3.5 ★.

## 4.4. Modelo de datos

Se utilizan dos niveles: las bases de datos crudas (SQLite), que conservan la salida directa de los *scrapers*, y los archivos limpios (Parquet), listos para los experimentos.

**Tabla 10. Esquema de las bases crudas.**

| Base y tabla | Campos principales | Registros |
|---|---|---|
| `letterboxd.db` / `peliculas` | slug (PK), título, año, directores, países, tmdb_id, calificación promedio, título y sinopsis en español e inglés | 878 |
| `letterboxd.db` / `resenas` | id (PK), película (FK → `peliculas.slug`), usuario, calificación, fecha, texto, likes, spoiler, idioma | 710,045 |
| `letterboxd.db` / `catalogo` | tmdb_id (PK), título, año, popularidad, votos, slug, estado, países | 17,834 |
| `historial_*.db` / `historial_usuario` | usuario, película (slug), calificación, like; único por (usuario, película) | 1,688,846 (grupo ≥ 5) |
| `historial_*.db` / `usuarios_procesados` | usuario (PK), estado (completo, parcial, vacío, error), películas guardadas y totales, páginas | 19,810 (grupo ≥ 5) |
| `sinopsis_imdb.db` / `sinopsis_imdb` | tconst (PK), estado, tmdb_id, sinopsis en español, inglés y otra | 757,649 |

**Tabla 11. Archivos limpios.**

| Archivo | Filas | Contenido |
|---|---|---|
| `catalogo_mx.parquet` | 878 | Película, títulos, año, directores, países, `tconst`, géneros y sinopsis limpias |
| `interacciones_g34.parquet` | 1,659,339 | Usuario × película del grupo 3–4: calificación, *like*, si tiene reseña, si es mexicana, partición |
| `interacciones_g5.parquet` | 1,844,900 | Ídem, grupo ≥ 5 |
| `items_contenido.parquet` | 98,798 | Toda película de los historiales y del catálogo; 51,466 con sinopsis informativa |
| `embeddings/sinopsis_…MiniLM-L12-v2.npz` | 51,466 × 384 | Embeddings normalizados de las sinopsis (float16) |
| `resenas_sentimiento.parquet` | 151,516 | Reseñas en español de los usuarios de los experimentos, con `texto_beto` y `texto_llm` |
| `resenas_afinado_beto.parquet` | 152,187 | Reseñas en español con estrellas de 95,934 usuarios ajenos a los experimentos (para afinar BETO) |
| `reporte_preparacion.json` | — | Conteos de toda la preparación |

Las entidades se relacionan así: una **película** (identificada por *slug* en Letterboxd y por `tconst` en IMDb) tiene muchas **reseñas**; un **usuario** tiene muchas **interacciones** (reseña o historial) con películas; cada interacción pertenece a una partición. El identificador canónico es el `tconst` de IMDb; los metadatos provienen de TMDB y, en su ausencia, de IMDb, y ningún dato de Letterboxd sobrescribe el catálogo (RN15). El enlace entre el *slug* de Letterboxd y el `tconst` se realiza por título y año, y cubre 89 % de las interacciones con sinopsis; los títulos homónimos pueden enlazarse mal, riesgo que se documenta como limitación.

## 4.5. Análisis exploratorio de los datos (EDA)

**Tabla 12. Descripción de los dos grupos de usuarios.**

| | Grupo 3–4 | Grupo ≥ 5 |
|---|---|---|
| Usuarios | 19,790 | 19,784 |
| Películas distintas | 72,240 | 67,786 |
| Interacciones | 1,659,339 | 1,844,900 |
| Densidad de la matriz | 0.116 % | 0.138 % |
| Interacciones con cine mexicano | 95,799 | 239,442 |
| …con reseña escrita | 66,339 | 198,139 |
| Películas del catálogo vistas por alguien | 828 de 878 | 861 de 878 |
| Interacciones con estrellas | 90.9 % | 92.5 % |
| Reseñas en español | 31,644 | 119,872 |

*(Figura sugerida: `resultados/00_datos/distribuciones_grupos.png`, con tres paneles: distribución de estrellas, películas mexicanas por usuario y tamaño del historial.)*

Los hallazgos principales son:

1. **Matriz extremadamente dispersa.** La densidad es de 0.12–0.14 %, lo que anticipa que los métodos que aprenden relaciones globales superarán a los de vecindario local.
2. **Cola larga marcada.** El 10 % de las películas más vistas (86 películas) concentra el 47 % de las interacciones con cine mexicano. Esto confirma, en el dominio nacional, el sesgo de popularidad planteado en el Capítulo 1.
3. **Las calificaciones se inclinan hacia lo positivo.** La moda es 4 ★ (≈ 22 %), seguida de 3 ★ y 3.5 ★; las calificaciones altas son mucho más frecuentes que las bajas. La distribución es casi idéntica en los dos grupos, por lo que la diferencia entre ellos radica en la cantidad de historial y no en cómo califican.
4. **El historial general es una ventana de ~72 películas.** El tamaño del historial por usuario muestra un pico en 72–75 películas, consecuencia de que solo se alcanza la primera página del perfil. Con ello, ambos grupos tienen unas 80 películas de cine en general para aprender su gusto.
5. **El grupo ≥ 5 aporta 2.5 veces más cine mexicano** (239,442 vs. 95,799 interacciones) y 3.0 veces más reseñas escritas (198,139 vs. 66,339).
6. **Reseñas cortas.** La mediana es de 115 caracteres y el percentil 95 de 485; una longitud máxima de 256 tokens cubre cerca del 99 % de las reseñas.
7. **Cobertura del catálogo.** Casi todo el catálogo está representado (828 y 861 de 878 películas), pero con muy pocas interacciones en la cola, de ahí el interés por el enfoque de contenido.

Estos resultados orientan decisiones posteriores: se fijó el umbral de relevancia en 3.5 ★ y se evalúa sobre el catálogo completo. El umbral mínimo de reseñas *m* de la regla RN03 (propuesto inicialmente en 10) queda **pendiente de fijarse** con base en la distribución de reseñas por película.

## 4.6. Visualización

Las visualizaciones del trabajo cumplen dos propósitos: describir los datos y comparar los modelos. Se generan desde los notebooks y se guardan en `resultados/`:

- **Distribuciones de los grupos** (`00_datos/distribuciones_grupos.png`): estrellas, películas mexicanas por usuario y tamaño del historial.
- **Longitud de las reseñas** (`00_datos/largo_resenas.png`).
- **Curvas de ajuste en validación** (`exp1/` y `exp2/ajuste_validacion_ranking.png`): nDCG@10 contra el hiperparámetro de cada modelo, para verificar que el óptimo quede en el interior de la rejilla.
- **Métricas en prueba por modelo** (`metricas_test_variante_A.png` en cada experimento).
- **Comparación final** (`comparacion/ndcg10_por_modelo.png`).

---

# CAPÍTULO 5. IMPLEMENTACIÓN

Este capítulo describe cómo se implementaron los componentes. El código se organiza en un paquete de Python reutilizable (`src/recomendador/`) y siete notebooks ejecutados en orden. Todos los experimentos comparten la misma partición de datos, de modo que las diferencias entre ellos se deben al modelo y no a la suerte de la partición.

## 5.1. Tratamiento de datos

El tratamiento está implementado en tres módulos y se ejecuta en el notebook `00_preparacion_y_limpieza`.

**Tabla 13. Módulos de tratamiento de datos.**

| Módulo | Responsabilidad |
|---|---|
| `limpieza.py` | Limpieza de reseñas (versiones para BETO y LLM) y de sinopsis (para embeddings y TF-IDF), según la Tabla 8 |
| `preparacion.py` | Convierte los datos crudos en datos limpios: une reseñas e historial, enlaza películas con IMDb, construye el catálogo y realiza la partición |
| `senal.py` | Convierte estrellas, *likes* y sentimiento en una preferencia numérica por par usuario–película |

**Señal de preferencia.** La preferencia `p` de un par usuario–película se define en tres variantes:

| Variante | Preferencia |
|---|---|
| **A** (línea base) | `p = estrellas / 5`; sin estrellas: 0.9 si dio *like*, 0.6 si no |
| **B** (BETO) | Como A, salvo en películas mexicanas reseñadas en español: `p = λ·(estrellas/5) + (1 − λ)·(3 + 2s)/5`; sin estrellas, `p = (3 + 2s)/5` |
| **C** (JEV) | Como B, con el puntaje `s` obtenido con JEV |

Aquí `s ∈ [−1, 1]` es el sentimiento de la reseña y `3 + 2s` lo lleva a la escala de estrellas. El peso λ ∈ {0, 0.25, 0.5, 0.75, 1} se elige en validación: λ = 1 aísla el efecto de usar el sentimiento solo para imputar reseñas sin estrellas, y λ = 0 usa únicamente el sentimiento.

> **Nota de nomenclatura.** En los experimentos, A, B y C designan variantes de la **señal de preferencia** (estrellas, estrellas + BETO, estrellas + JEV). En el Capítulo 3 (alcance y RN13) designan **modos del motor** (contenido, usuarios y sentimiento, híbrido). Conviene unificar o renombrar una de las dos para evitar confusión.

**Prevención de fuga de información.** Un par que va a `val` o `test` se retira completo, también del historial general. El sentimiento solo modifica pares de entrenamiento y las estrellas de prueba nunca se alteran. El afinado de BETO usa reseñas de usuarios ajenos a los experimentos.

## 5.2. Almacenamiento de datos

El almacenamiento se organiza por etapas, con un formato adecuado para cada una:

- **Datos crudos (`datos/crudos/`).** Bases SQLite generadas por los *scrapers* (`letterboxd.db`, `historial_3_a_4.db`, `historial_min5.db`, `sinopsis_imdb.db`), junto con CSV, JSONL y registros de ejecución. SQLite se eligió porque no requiere servidor, permite reanudar la extracción (cada reseña o usuario se registra al procesarse) y evita duplicados mediante claves primarias y restricciones de unicidad.
- **Datos limpios (`datos/limpios/`).** Archivos Parquet, que son compactos, conservan los tipos de dato y se leen con rapidez en los notebooks. Los embeddings se guardan en formato NumPy comprimido (`.npz`, 51,466 × 384, `float16`). Toda la preparación queda resumida en `reporte_preparacion.json`.
- **Resultados (`resultados/`).** Métricas en CSV, hiperparámetros en JSON, métricas por usuario en Parquet (para las pruebas estadísticas) y gráficas en PNG.

Esta estructura constituye la capa de almacenamiento del *data lake* descrito en el Capítulo 2: datos crudos, datos procesados y resultados, con un corte de datos fijo (RN09). **Pendiente de los autores:** indicar la fecha de corte del corpus y confirmar cómo se aplicó la seudonimización de usuarios (RN12), ya que los nombres de usuario se conservan en las bases crudas y los documentos del proyecto recomiendan seudonimizarlos antes de publicar resultados.

## 5.3. Implementación de modelos y grafos

El paquete `src/recomendador/` implementa los modelos y el protocolo de evaluación. Todos los modelos aprenden de la matriz completa (historial general y cine mexicano), pero **solo puntúan las 878 películas del catálogo mexicano** (RN01).

### 5.3.1. Filtrado colaborativo (`modelos_cf.py`; experimentos 1 y 2)

**Tabla 14. Modelos colaborativos.**

| Modelo | Tipo | Descripción |
|---|---|---|
| Popularidad | Referencia | Las películas mexicanas más vistas en entrenamiento |
| ItemKNN | Vecindario | Similitud coseno entre películas según quién las vio (Sarwar et al., 2001) |
| PureSVD | Factorización | SVD truncada de la matriz de preferencias (Cremonesi et al., 2010) |
| EASE | Autoencoder lineal | Matriz película → película con solución cerrada y regularización λ (Steck, 2019) |
| Media global, Sesgos, ItemKNN con sesgos | Predicción de estrellas | μ; μ + b_u + b_i; sesgos más vecinos sobre los residuales (Koren, 2010) |

Los hiperparámetros se eligen en validación con el mejor nDCG@10 (o el menor RMSE, en predicción de estrellas), y el modelo se reentrena con `train` + `val` para medirlo una sola vez en prueba.

**Tabla 15. Hiperparámetros elegidos.**

| Modelo | Parámetro | Rejilla explorada | Elegido |
|---|---|---|---|
| ItemKNN | Vecinos *k* | 10 a 6,400 | 6,400 (curva casi plana) |
| PureSVD | Factores | 64, 128, 256, 384, 512, 768 | 512 |
| EASE | λ | 25, 50, 100, 250, 500 | 100 |
| Sesgos | Regularización (ítem, usuario) | (2, 5), (5, 10), (10, 15) | (2, 5) |
| ItemKNN con sesgos | *k*, *shrink*, regularización | *k* = 40; *shrink* ∈ {20, 100}; reg ∈ {0.5, 1} | *shrink* 20, reg 0.5 |

*(Valores del grupo 3–4; los del grupo ≥ 5 están en `resultados/exp2/hiperparametros.json`.)*

### 5.3.2. Filtrado basado en contenido (`modelos_contenido.py`; experimento 3)

Cada película se representa como un vector formado por bloques normalizados y ponderados:

| Bloque | Construcción | Peso |
|---|---|---|
| Texto, TF-IDF | Sinopsis limpia en inglés; unigramas y bigramas, sin *stopwords* ni acentos, TF sublineal; vocabulario de 50,000 términos | 1 |
| Texto, embeddings | `paraphrase-multilingual-MiniLM-L12-v2` (Sentence-BERT multilingüe, 384 dimensiones; Reimers y Gurevych, 2019) | 1 |
| Géneros, década, directores | Codificación *one-hot* | Hiperparámetros `generos`, `decada`, `directores` |

El **perfil del usuario** es la suma de los vectores de las películas que vio, con peso `w = p − 0.5` (lo calificado alto acerca el perfil; lo calificado bajo lo aleja), multiplicando por `peso_mx` las películas mexicanas. El **puntaje** de cada película no vista es la similitud coseno con el perfil. La rejilla final explora 36 combinaciones por representación y grupo. La explicación de cada recomendación ("porque te gustó X") se obtiene directamente de las películas del perfil que más contribuyen a la similitud (requerimiento RF14).

### 5.3.3. Análisis de sentimiento (`sentimiento.py`; experimentos 4 y 5)

**BETO (experimento 4).** Se usa `dccuchile/bert-base-spanish-wwm-cased` (110 M de parámetros; Cañete et al., 2020), afinado con 60 mil reseñas de Letterboxd de usuarios ajenos a los experimentos (20 mil por clase, etiquetadas con estrellas). Se entrena con AdamW (tasa 2·10⁻⁵, *warmup* de 6 %, decaimiento lineal), 2 épocas, lotes de 32 y 128 tokens; se conserva el modelo con mejor F1-macro en validación. La inferencia sobre las 151,516 reseñas usa lotes de 64 ordenados por longitud y hasta 256 tokens. La salida por reseña es `p_neg`, `p_neu`, `p_pos` y `s = p_pos − p_neg`. Como alternativa, el notebook permite usar `finiteautomata/beto-sentiment-analysis` (afinado con tuits). En una prueba piloto con 300 reseñas, este modelo obtuvo F1-macro ≈ 0.40 y Spearman ≈ 0.21 contra las estrellas, pues confundía tramas oscuras con opiniones negativas; por ello el modo afinado es el predeterminado.

**JEV (experimento 5).** Un modelo de lenguaje grande consultado por API, sin entrenamiento (*zero-shot*). La consulta pide la opinión del autor **sobre la película** (no sobre personajes o trama), menciona sarcasmo, modismos mexicanos y emojis, e incluye tres ejemplos. Las reseñas se envían en lotes de 20, con temperatura 0, sin mostrar nunca las estrellas, y se pide una respuesta en JSON con etiqueta y puntuación en [−1, 1]. El código incluye caché por respuesta, reintentos con espera exponencial ante errores 429/5xx y reanudación; solo la función `llamar_jev` depende del proveedor. Se estima un consumo de 10 a 15 millones de tokens para todo el corpus.

**Estado de los experimentos de sentimiento.** Los notebooks 04 y 05 están implementados y se verificaron de punta a punta (BETO con una muestra de 300 reseñas; JEV contra un servidor local que imita la API), pero **aún no se ejecutan en su totalidad**. Por tanto, las variantes B y C se activan automáticamente al volver a correr los notebooks 01 a 03 cuando existan `sentimiento_beto.parquet` y `sentimiento_jev.parquet`.

### 5.3.4. Evaluación (`metricas.py`, `experimento.py`)

La evaluación es *offline*: se ordenan las 878 películas del catálogo (menos las vistas en entrenamiento, sin muestrear negativos) y se verifica si aparecen arriba las películas de prueba con ≥ 3.5 ★ (Krichene y Rendle, 2020).

| Familia | Métricas |
|---|---|
| Ranking @K (K = 5, 10, 20) | Precision, Recall, HitRate, nDCG (principal, K = 10), MAP, MRR |
| Más allá de la precisión | Cobertura (películas distintas recomendadas / 878), novedad (−log₂ de la popularidad, en bits), ILD (diversidad intralista) |
| Predicción de estrellas | RMSE y MAE |
| Significancia | Prueba de Wilcoxon pareada por usuario sobre nDCG@10 y Recall@10 (umbral *p* < 0.05) |
| Analizadores de sentimiento | Exactitud, F1-macro, kappa de Cohen, Spearman, MAE en estrellas y acuerdo BETO–JEV |

Con 878 candidatas y típicamente una película relevante por usuario, un orden al azar tendría un HitRate@10 de aproximadamente 1.1 %.

### 5.3.5. Resultados de la implementación (variante A, conjunto de prueba)

**Tabla 16. Resultados en prueba, K = 10.**

| Modelo | Enfoque | nDCG@10 (3–4) | Recall@10 (3–4) | nDCG@10 (≥ 5) | Recall@10 (≥ 5) | HitRate@10 (≥ 5) | Cobertura@10 (≥ 5) |
|---|---|---|---|---|---|---|---|
| Popularidad | Referencia | 0.027 | 0.064 | 0.023 | 0.051 | 0.070 | 3 % |
| ItemKNN | Colaborativo | 0.058 | 0.128 | 0.079 | 0.149 | 0.204 | 46 % |
| PureSVD | Colaborativo | 0.113 | 0.204 | 0.143 | 0.231 | 0.307 | 30 % |
| **EASE** | Colaborativo | **0.137** | **0.259** | **0.174** | **0.290** | **0.373** | 45 % |
| TF-IDF + metadatos | Contenido | 0.062 | 0.105 | 0.076 | 0.120 | 0.165 | **99.7 %** |
| Embeddings + metadatos | Contenido | 0.064 | 0.111 | 0.074 | 0.118 | 0.161 | 98 % |

En predicción de estrellas, el ItemKNN con sesgos obtiene un RMSE de 0.864 (grupo 3–4) y 0.805 (grupo ≥ 5), frente a 1.13 de la media global. Los resultados se discuten con detalle en el Capítulo 6; aquí se resumen las observaciones que condicionan la implementación:

- EASE es el mejor modelo en ambos grupos (5.1 y 7.5 veces la popularidad en nDCG@10) y todas las diferencias entre modelos son significativas (Wilcoxon, *p* < 10⁻²⁵).
- Con apenas 1–2 películas mexicanas en entrenamiento, el historial general permite alcanzar un nDCG@10 de 0.137, 79 % del nivel del grupo asiduo (0.174).
- La sinopsis sola rinde por debajo de la popularidad (nDCG@10 de 0.015–0.021 frente a 0.023–0.027); lo que hace funcionar al contenido son los metadatos (director, década, género), que multiplican por 3.6–4.3 el nDCG del texto solo.
- TF-IDF y embeddings quedan prácticamente empatados una vez que se agregan metadatos.
- El contenido logra cerca del 45 % del nDCG de EASE, pero cubre 98–100 % del catálogo (EASE, 38–45 %) y con mayor novedad, y sus recomendaciones son explicables. Ambos enfoques son complementarios, lo que respalda el diseño híbrido del sistema.

### 5.3.6. Componentes pendientes de implementar

El código del repositorio cubre los experimentos de recomendación y sentimiento, pero los siguientes elementos del alcance (Capítulo 3) **no están implementados todavía**, por lo que no se describen como terminados:

- El **agrupamiento temático con HDBSCAN** sobre los embeddings de sinopsis (RF20; objetivo específico 3) y, con él, las explicaciones por grupo temático (RN10).
- El **motor híbrido** (RN11), que combina la similitud semántica con la polaridad agregada por película (`score = α·sim + (1 − α)·pol`).
- El **agente conversacional** (RF01–RF08), que interpreta la película de referencia, resuelve ambigüedades y presenta las recomendaciones.

Cabe señalar que los experimentos actuales evalúan recomendación **por usuario** (historial → películas retenidas), mientras que el sistema descrito en el alcance recomienda **a partir de una película de referencia** mencionada en la conversación. Los autores deben decidir si se añade una evaluación película a película o si se acota el alcance del Capítulo 3.

*Grafos.* El título de esta sección (heredado de la plantilla) menciona grafos; el proyecto actual no los utiliza. Si no se incorporan, conviene renombrar la sección como "Implementación de modelos".

## 5.4. Implementación de visualización

Las gráficas se generan con Python (Matplotlib) dentro de los notebooks y se guardan como PNG en `resultados/`. El notebook `06_comparacion_resultados` consolida las métricas de los experimentos 1 a 3 en un cuadro comparativo (`cuadro_principal_variante_A.csv`), una gráfica de nDCG@10 por modelo (`ndcg10_por_modelo.png`) y el documento `resumen_resultados.md`, con las secciones "Efecto del sentimiento" y "Analizadores de sentimiento" a la espera de los experimentos 4 y 5.

El **prototipo funcional de demostración** con la interfaz del agente conversacional (objetivo específico 7) corresponde al trabajo restante y se describirá en este apartado cuando esté implementado.

## 5.5. Reproducibilidad

El entorno se instala con `pip install -r requirements.txt` sobre Python 3.11. La partición usa semilla 42 y todos los modelos son deterministas, salvo el afinado de BETO y las respuestas del LLM. Las credenciales de TMDB se leen desde `scrapers/.env` y no se incluyen en el repositorio. El orden de ejecución es: 00 (preparación) → 01, 02, 03 (variante A) → 04 (GPU) y 05 (API) → repetir 01, 02, 03 con las variantes B y C → 06 (comparación).

---

# Referencias nuevas para agregar a la lista

- Cañete, J., Chaperon, G., Fuentes, R., Ho, J.-H., Kang, H. y Pérez, J. (2020). *Spanish Pre-Trained BERT Model and Evaluation Data*. PML4DC @ ICLR.
- Cremonesi, P., Koren, Y. y Turrin, R. (2010). *Performance of recommender algorithms on top-N recommendation tasks*. RecSys.
- Koren, Y. (2010). *Factor in the neighbors: Scalable and accurate collaborative filtering*. ACM TKDD.
- Krichene, W. y Rendle, S. (2020). *On Sampled Metrics for Item Recommendation*. KDD.
- Pérez, J. M. et al. (2021). *pysentimiento: A Python Toolkit for Sentiment Analysis and SocialNLP tasks*. arXiv:2106.09462.
- Reimers, N. y Gurevych, I. (2019). *Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks*. EMNLP.
- Sarwar, B., Karypis, G., Konstan, J. y Riedl, J. (2001). *Item-based collaborative filtering recommendation algorithms*. WWW.
- Steck, H. (2019). *Embarrassingly Shallow Autoencoders for Sparse Data*. WWW.

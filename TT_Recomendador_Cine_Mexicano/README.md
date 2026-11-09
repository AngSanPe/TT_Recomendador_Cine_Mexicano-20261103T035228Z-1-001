# Sistema de recomendación de cine mexicano con análisis de sentimiento

Trabajo Terminal. Esta carpeta reúne, en orden, todo lo necesario para reproducir los experimentos: los scrapers que recolectaron los datos, los datos crudos y limpios, el código, los notebooks ejecutados, los resultados y la documentación de cada experimento.

## Experimentos

| # | Experimento | Notebook | Documento | Dónde corre |
|---|---|---|---|---|
| 0 | Preparación y limpieza de datos | `00_preparacion_y_limpieza.ipynb` | [Datos_y_limpieza.md](docs/Datos_y_limpieza.md) | CPU · ejecutado |
| 1 | Filtrado colaborativo — usuarios con **3 a 4** películas mexicanas | `01_experimento1_cf_usuarios_3a4.ipynb` | [Experimento_1.md](docs/Experimento_1.md) | CPU · ejecutado (variante A) |
| 2 | Filtrado colaborativo — usuarios con **5 o más** películas mexicanas | `02_experimento2_cf_usuarios_min5.ipynb` | [Experimento_2.md](docs/Experimento_2.md) | CPU · ejecutado (variante A) |
| 3 | Filtrado basado en contenido (TF-IDF y embeddings de sinopsis) | `03_experimento3_basado_en_contenido.ipynb` | [Experimento_3.md](docs/Experimento_3.md) | CPU · ejecutado (variante A) |
| 4 | Sentimiento de las reseñas con **BETO** | `04_experimento4_sentimiento_beto.ipynb` | [Experimento_4_BETO.md](docs/Experimento_4_BETO.md) | **GPU** · por ejecutar |
| 5 | Sentimiento de las reseñas con **JEV** (LLM) | `05_experimento5_sentimiento_jev.ipynb` | [Experimento_5_JEV.md](docs/Experimento_5_JEV.md) | **API key** · por ejecutar |
| — | Comparación final | `06_comparacion_resultados.ipynb` | `resultados/comparacion/resumen_resultados.md` | CPU |

Los experimentos 1–3 tienen tres variantes de la señal de preferencia: **A** solo estrellas (línea base), **B** estrellas + sentimiento BETO, **C** estrellas + sentimiento JEV. La variante A ya está ejecutada; B y C se activan solas cuando existen los archivos que producen los experimentos 4 y 5.

El protocolo de evaluación y las métricas (Precision, Recall, nDCG, HitRate, MAP, MRR @K, cobertura, novedad, diversidad, RMSE/MAE y prueba de Wilcoxon) están en [Protocolo_y_metricas.md](docs/Protocolo_y_metricas.md).

## Resultados (variante A, conjunto de prueba)

Relevante = película mexicana retenida que el usuario calificó con ≥ 3.5 ★; se ordenan las 878 películas del catálogo (un orden al azar acertaría en ~1 % de los usuarios).

| Modelo | Enfoque | nDCG@10 (3–4) | Recall@10 (3–4) | nDCG@10 (≥ 5) | Recall@10 (≥ 5) | HitRate@10 (≥ 5) | Cobertura@10 (≥ 5) |
|---|---|---|---|---|---|---|---|
| Popularidad | referencia | 0.027 | 0.064 | 0.023 | 0.051 | 0.070 | 3 % |
| ItemKNN | colaborativo | 0.058 | 0.128 | 0.079 | 0.149 | 0.204 | 46 % |
| PureSVD | colaborativo | 0.113 | 0.204 | 0.143 | 0.231 | 0.307 | 30 % |
| **EASE** | colaborativo | **0.137** | **0.259** | **0.174** | **0.290** | **0.373** | 45 % |
| TF-IDF + metadatos | contenido | 0.062 | 0.105 | 0.076 | 0.120 | 0.165 | **99.7 %** |
| Embeddings + metadatos | contenido | 0.064 | 0.111 | 0.074 | 0.118 | 0.161 | 98 % |

Predicción de estrellas (ItemKNN con sesgos): RMSE 0.864 (grupo 3–4) y 0.805 (grupo ≥ 5), frente a 1.13 de la media global.

**Hallazgos principales**
1. **EASE es el mejor modelo en ambos grupos** (5–7.5 veces la popularidad en nDCG@10). Todas las diferencias entre modelos son significativas (Wilcoxon pareado, *p* < 10⁻²⁵).
2. **Más historial mexicano, mejores recomendaciones**: el grupo ≥ 5 mejora 26 % en nDCG@10, pero el ocasional ya alcanza el 79 % de ese nivel gracias a su historial de cine general.
3. **El contenido logra ~45 % del nDCG de EASE, pero cubre casi todo el catálogo** y recomienda títulos mucho menos conocidos; además, cada recomendación es explicable. La sinopsis sola rinde por debajo de la popularidad: lo que hace funcionar al contenido son los metadatos (director, década, género).
4. **TF-IDF y embeddings empatan** una vez que se agregan metadatos.
5. **Sentimiento (variantes B y C): pendiente** de ejecutar los experimentos 4 y 5.

Detalle e interpretación en cada documento de `docs/`; cuadro consolidado en `resultados/comparacion/resumen_resultados.md`.

## Cómo completar los experimentos 4 y 5

```
04 (GPU) ──► datos/limpios/sentimiento/sentimiento_beto.parquet ──┐
05 (API) ──► datos/limpios/sentimiento/sentimiento_jev.parquet  ──┼──► volver a correr 01, 02, 03 ──► 06
                                                                  ┘
```

1. **Sube a Colab/Drive** (o al servidor con GPU) solo lo necesario: `src/`, `notebooks/`, `datos/limpios/` (~150 MB). Los datos crudos no hacen falta.
2. En la primera celda de cada notebook descomenta las líneas de Colab y ajusta `TT_RAIZ` a la ruta de la carpeta en Drive.
3. **Experimento 4 (BETO):** entorno con GPU (Colab → *Entorno de ejecución → Cambiar tipo → T4 GPU*). Ejecuta todo. Predeterminado: BETO afinado con reseñas de otros usuarios (~20 min en T4). Opcional: repetir con `MODO = 'preentrenado'` para comparar.
4. **Experimento 5 (JEV):** define `JEV_API_KEY`, `JEV_BASE_URL` y `JEV_MODELO` (variables de entorno o Secretos de Colab; la key nunca se escribe en el notebook). Corre primero el piloto de 100 reseñas, revisa calidad y costo estimado, y después pon `EJECUTAR_TODO = True`. La llamada a la API está aislada en la función `llamar_jev` (formato compatible con OpenAI `/chat/completions`): si JEV usa otro formato, solo se cambia esa función.
5. Copia los `.parquet` generados a `datos/limpios/sentimiento/` en tu carpeta local (y `resultados/exp4`, `resultados/exp5`).
6. Vuelve a ejecutar `01`, `02`, `03` (en la Mac, unos 20–30 min en total con ambas variantes) y luego `06`.

## Estructura de la carpeta

```
TT_Recomendador_Cine_Mexicano/
├── README.md                     este archivo
├── requirements.txt              dependencias de los experimentos
├── docs/                         un documento por experimento + datos + protocolo
├── notebooks/                    00 → 06, en orden de ejecución
├── src/recomendador/             código común que usan los notebooks
│   ├── limpieza.py               limpieza de reseñas y sinopsis (BETO, LLM, embeddings)
│   ├── preparacion.py            datos crudos → datos limpios + partición
│   ├── senal.py                  estrellas / like / sentimiento → preferencia
│   ├── modelos_cf.py             Popularidad, ItemKNN, PureSVD, EASE, predicción de calificación
│   ├── modelos_contenido.py      TF-IDF, embeddings, perfil de usuario
│   ├── metricas.py               métricas de ranking, globales y de predicción
│   ├── sentimiento.py            formato y evaluación de los analizadores
│   └── experimento.py            ajuste en validación, evaluación en prueba, Wilcoxon
├── scrapers/                     código que recolectó los datos (ver su README)
│   ├── letterboxd_scraper/       reseñas, catálogo y sinopsis (Letterboxd + TMDb)
│   ├── user_films_scraper.py     historial de películas de cada usuario
│   ├── run_scrapers.sh           corrida de los dos grupos de usuarios
│   ├── tmdb.py                   verificación de la credencial de TMDb
│   └── peliculas_mexicanas.txt   lista semilla
├── datos/
│   ├── crudos/                   salida directa de los scrapers (bases SQLite, CSV, logs)
│   └── limpios/                  datos listos para los experimentos (parquet, embeddings, sentimiento)
└── resultados/                   métricas, tablas y gráficas de cada experimento
    ├── 00_datos/  exp1/  exp2/  exp3/  exp4/  exp5/  comparacion/
```

## Notas

* **Los archivos originales no se movieron.** `datos/crudos/` contiene copias de `datos/`, `data/raw/` e `imdb_movies.csv` de la carpeta del proyecto (copias APFS, no ocupan espacio extra en disco mientras no se modifiquen). La caché HTML del scraper (`TrabajoTerminal/datos/cache/`, 7.3 GB, 60 mil páginas) no se copió: solo sirve para reanudar el scraping sin volver a descargar.
* **Credenciales.** No se copiaron `.env` ni `accesos.txt` (contienen la clave de TMDb). Para volver a usar los scrapers, crea `scrapers/.env` a partir de `.env.ejemplo`.
* **Entorno local.** `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. Los notebooks se ejecutaron con Python 3.11.
* **Reproducibilidad.** Semilla 42 en la partición; el resto de los modelos es determinista (salvo el afinado de BETO y las respuestas del LLM).

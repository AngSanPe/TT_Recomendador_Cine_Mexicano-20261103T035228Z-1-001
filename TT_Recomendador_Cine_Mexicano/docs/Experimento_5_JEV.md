# Experimento 5 · Análisis de sentimiento de las reseñas con JEV (LLM)

**Notebook:** `notebooks/05_experimento5_sentimiento_jev.ipynb` · **Resultados:** `resultados/exp5/` · **Salida para los experimentos 1–3:** `datos/limpios/sentimiento/sentimiento_jev.parquet`

**Estado:** notebook listo; **pendiente de ejecutar con la API key de JEV**. Se verificó de punta a punta contra un servidor local que imita la API (incluye errores 503 simulados y respuestas incompletas), para comprobar reintentos, caché, interpretación de la respuesta y evaluación.

## 1. Objetivo

Mismo objetivo que el experimento 4, con otro tipo de modelo: obtener un puntaje de sentimiento `s ∈ [-1, 1]` por reseña, ahora con un **modelo de lenguaje grande (LLM)** consultado por API, medir su acuerdo con las estrellas y con BETO, y usarlo en la **variante C** de los experimentos 1, 2 y 3.

**Por qué comparar con BETO.** Son dos enfoques distintos de análisis de sentimiento:

| | BETO (exp. 4) | JEV (exp. 5) |
|---|---|---|
| Tipo | clasificador afinado (110 M parámetros) | LLM generativo, *zero-shot* (sin entrenamiento) |
| Dónde corre | GPU propia | servidor del proveedor |
| Costo | tiempo de GPU | por token |
| Sarcasmo, modismos, emojis | lo que haya visto al afinar | los entiende por su preentrenamiento |
| Reproducibilidad | total (pesos fijos) | depende de la versión del modelo del proveedor |

## 2. Diseño de la consulta

* **Instrucciones** (en el notebook, celda `INSTRUCCIONES`): se pide la opinión del autor **sobre la película**, no sobre personajes o trama ("el villano es repugnante" puede venir de alguien a quien le encantó la película); se mencionan explícitamente sarcasmo, modismos mexicanos ("está chida", "qué hueva", "un churro") y emojis; se incluyen tres ejemplos que fijan el formato y calibran la escala.
* **Salida pedida:** un arreglo JSON `[{"id": 1, "sentimiento": "positivo|neutral|negativo", "puntuacion": -1.0…1.0}, …]`.
* **Lotes de 20 reseñas** por petición, numeradas: reduce peticiones y costo frente a enviarlas una por una. Si el modelo omite alguna, esa se reintenta sola.
* **Nunca se muestran las estrellas** al modelo, solo el texto (`texto_llm`: limpio, con emojis conservados porque el LLM los entiende).
* **Temperatura 0** para la mayor estabilidad posible.
* **Caché** (`jev_cache.jsonl`): cada respuesta válida se guarda al llegar; al reanudar, no se vuelve a pagar lo ya procesado.
* **Robustez:** reintentos con espera exponencial ante 429/5xx y errores de red; la respuesta se interpreta aunque venga envuelta en bloques de código o con etiquetas en otra forma ("positiva", "mixto").

**Conexión.** La única función que depende del proveedor es `llamar_jev(mensajes)`; usa el formato *chat completions* compatible con OpenAI (`POST {JEV_BASE_URL}/chat/completions`). Si JEV expone otro formato, se cambia solo esa función. Credenciales por variables de entorno: `JEV_API_KEY`, `JEV_BASE_URL`, `JEV_MODELO` (la key nunca se escribe en el notebook ni se guarda en el caché).

## 3. Procedimiento

1. **Prueba de conexión.**
2. **Piloto** con 100 reseñas con estrellas: tasa de respuestas válidas, métricas preliminares, tokens consumidos, y estimación de tokens, costo (si se dan los precios) y tiempo para las 151,516 reseñas.
3. **Corrida completa** solo si `EJECUTAR_TODO = True`. Con `MAX_RESENAS` se puede limitar el gasto: se procesa primero todo el grupo 3–4 (31,644 reseñas) y luego una muestra del ≥ 5. Las reseñas sin sentimiento simplemente conservan su señal de estrellas en los experimentos.
4. **Salida** con el mismo formato que BETO (`etiqueta`, `s`; sin probabilidades).
5. **Evaluación** contra las estrellas (mismas métricas que el experimento 4) y **acuerdo con BETO** (porcentaje de coincidencia de etiqueta, kappa de Cohen y Spearman entre los puntajes) sobre las mismas reseñas.

## 4. Métricas

Las mismas del experimento 4 (exactitud, F1-macro, kappa, F1 por clase, Spearman, MAE en estrellas), más:

| Métrica | Qué mide |
|---|---|
| Cobertura | % de reseñas con una respuesta válida |
| Tokens y costo | consumo real de la corrida (`metricas_sentimiento_jev.json`) |
| Acuerdo BETO–JEV | si los dos analizadores "ven" lo mismo; si discrepan mucho, la variante que mejor recomiende indica cuál capta mejor el gusto |

## 5. Resultados

_Pendiente de ejecución con la API key._ Al terminar, el notebook escribe `resultados/exp5/metricas_sentimiento_jev.json/.csv`, `matriz_confusion_jev.csv`, `evaluacion_jev.png` y `acuerdo_beto_jev.json`; el efecto en la recomendación aparece como variante C en los experimentos 1–3 y en `resultados/comparacion/resumen_resultados.md`.

| Métrica | JEV | BETO (exp. 4) |
|---|---|---|
| Cobertura | | 100 % |
| Exactitud | | |
| F1-macro | | |
| Kappa | | |
| Spearman | | |
| Acuerdo de etiqueta con BETO | | — |

## 6. Cómo ejecutarlo

1. Define `JEV_API_KEY`, `JEV_BASE_URL` (p. ej. `https://…/v1`) y `JEV_MODELO` como variables de entorno o Secretos de Colab. No hace falta GPU.
2. Ejecuta hasta el piloto. Revisa: que haya ~100/100 respuestas, que las etiquetas tengan sentido y el costo estimado.
3. Pon `EJECUTAR_TODO = True` (y opcionalmente `MAX_RESENAS`, `HILOS`) y corre desde la sección 5.
4. Descarga `datos/limpios/sentimiento/sentimiento_jev.parquet` y `resultados/exp5/` a la carpeta local; vuelve a correr 01, 02, 03 y 06.

**Estimación a priori del consumo** (la cifra real la da el piloto): instrucciones repartidas entre las 20 reseñas del lote (~20 tokens por reseña) + texto (mediana 115 caracteres, ~30–45 tokens) + respuesta (~20 tokens) ≈ 70–90 tokens por reseña, es decir, del orden de **10–15 millones de tokens** para las 151,516 reseñas.

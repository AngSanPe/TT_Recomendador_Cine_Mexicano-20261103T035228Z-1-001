# Resumen de resultados

Generado por `notebooks/06_comparacion_resultados.ipynb`. Métricas en el conjunto de prueba, relevante = película mexicana retenida calificada con ≥ 3.5 ★, ranking sobre las 878 películas del catálogo.

## Variante A (solo estrellas)

| grupo_nombre | enfoque | modelo | Precision@10 | Recall@10 | nDCG@10 | HitRate@10 | MRR@10 | Cobertura@10 | Novedad@10 |
|---|---|---|---|---|---|---|---|---|---|
| 3–4 películas MX | Colaborativo | EASE | 0.0259 | 0.2591 | 0.1374 | 0.2591 | 0.1004 | 0.3770 | 5.3326 |
| 3–4 películas MX | Colaborativo | ItemKNN | 0.0128 | 0.1281 | 0.0576 | 0.1281 | 0.0366 | 0.3360 | 4.7006 |
| 3–4 películas MX | Colaborativo | PureSVD | 0.0204 | 0.2043 | 0.1132 | 0.2043 | 0.0857 | 0.2677 | 5.7152 |
| 3–4 películas MX | Contenido | Contenido-Embeddings | 0.0111 | 0.1109 | 0.0641 | 0.1109 | 0.0497 | 0.9954 | 9.0088 |
| 3–4 películas MX | Contenido | Contenido-Embeddings (solo texto) | 0.0032 | 0.0321 | 0.0176 | 0.0321 | 0.0133 | 1.0000 | 9.6411 |
| 3–4 películas MX | Contenido | Contenido-TFIDF | 0.0105 | 0.1046 | 0.0623 | 0.1046 | 0.0493 | 0.9954 | 8.8215 |
| 3–4 películas MX | Contenido | Contenido-TFIDF (solo texto) | 0.0027 | 0.0271 | 0.0146 | 0.0271 | 0.0109 | 0.9989 | 9.6675 |
| 3–4 películas MX | Referencia | Popularidad | 0.0064 | 0.0638 | 0.0269 | 0.0638 | 0.0160 | 0.0239 | 4.1919 |
| ≥5 películas MX | Colaborativo | EASE | 0.0440 | 0.2897 | 0.1737 | 0.3733 | 0.1613 | 0.4476 | 4.4205 |
| ≥5 películas MX | Colaborativo | ItemKNN | 0.0228 | 0.1490 | 0.0793 | 0.2044 | 0.0686 | 0.4624 | 4.0399 |
| ≥5 películas MX | Colaborativo | PureSVD | 0.0351 | 0.2311 | 0.1431 | 0.3067 | 0.1386 | 0.2950 | 4.5444 |
| ≥5 películas MX | Contenido | Contenido-Embeddings | 0.0179 | 0.1178 | 0.0740 | 0.1610 | 0.0716 | 0.9795 | 6.9518 |
| ≥5 películas MX | Contenido | Contenido-Embeddings (solo texto) | 0.0047 | 0.0319 | 0.0182 | 0.0460 | 0.0172 | 1.0000 | 7.7538 |
| ≥5 películas MX | Contenido | Contenido-TFIDF | 0.0183 | 0.1199 | 0.0756 | 0.1645 | 0.0738 | 0.9966 | 6.6620 |
| ≥5 películas MX | Contenido | Contenido-TFIDF (solo texto) | 0.0054 | 0.0351 | 0.0211 | 0.0518 | 0.0209 | 0.9909 | 7.7445 |
| ≥5 películas MX | Referencia | Popularidad | 0.0073 | 0.0512 | 0.0230 | 0.0701 | 0.0168 | 0.0342 | 3.4922 |

- **3–4 películas MX**: mejor modelo **EASE** (colaborativo), nDCG@10 = 0.1374, Recall@10 = 0.2591, HitRate@10 = 0.2591 (×5.1 sobre popularidad).
- **≥5 películas MX**: mejor modelo **EASE** (colaborativo), nDCG@10 = 0.1737, Recall@10 = 0.2897, HitRate@10 = 0.3733 (×7.5 sobre popularidad).

## Efecto del sentimiento

_Pendiente: ejecutar los notebooks 04 y 05 y después 01–03._

## Analizadores de sentimiento

_Pendiente: ejecutar los notebooks 04 (BETO) y 05 (JEV)._

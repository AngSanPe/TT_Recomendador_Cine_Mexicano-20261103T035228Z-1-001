"""Código común de los experimentos del sistema de recomendación de cine mexicano.

Módulos:
    rutas            ubicación de datos crudos, limpios y resultados
    limpieza         limpieza de texto (reseñas y sinopsis) para BETO, LLM y embeddings
    preparacion      de las bases crudas a los datos limpios y la partición train/val/test
    senal            de calificación/like/sentimiento a un valor de preferencia
    modelos_cf       filtrado colaborativo (popularidad, Item-kNN, PureSVD, EASE, predicción de calificación)
    modelos_contenido filtrado basado en contenido (TF-IDF y embeddings)
    metricas         métricas de ranking, de predicción y de "más allá de la precisión"
    sentimiento      utilidades compartidas por BETO y JEV (formato y evaluación)
    experimento      orquestación: ajuste en validación y evaluación final en prueba
"""

__version__ = "1.0.0"

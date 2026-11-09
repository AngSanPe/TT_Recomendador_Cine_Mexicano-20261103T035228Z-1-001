# Scrapers utilizados

Copia del código que recolectó los datos de `datos/crudos/`. La documentación completa del scraper de Letterboxd (decisiones de diseño, `robots.txt`, límites medidos) está en [README_scraper_letterboxd.md](README_scraper_letterboxd.md).

| Archivo | Qué hace | Produce |
|---|---|---|
| `letterboxd_scraper/` | paquete: catálogo de cine mexicano (TMDb → Letterboxd), reseñas por película, sinopsis | `letterboxd.db`, `resenas_*.csv/jsonl`, `sinopsis_peliculas.csv` |
| `letterboxd_scraper` → `sinopsis-imdb` | sinopsis de los 757 mil títulos de `imdb_movies.csv` vía TMDb | `sinopsis_imdb.db/.csv/.log` |
| `user_films_scraper.py` | historial de películas (estrellas y *like*) de una muestra de usuarios, por grupo | `historial_3_a_4.db`, `historial_min5.db` |
| `run_scrapers.sh` | lanza los dos grupos de `user_films_scraper.py` (3–4 y ≥ 5 películas mexicanas, 10 mil usuarios c/u) | logs `scraper_3_a_4.log`, `scraper_min5.log` |
| `tmdb.py` | verifica la credencial de TMDb | — |
| `peliculas_mexicanas.txt` | lista semilla de 4,164 slugs | — |
| `.env.ejemplo` | plantilla para la credencial de TMDb | — |

## Volver a ejecutarlos

Los comandos del README original suponen que se corren desde la raíz del proyecto, con la base en `datos/letterboxd.db`. Desde esta carpeta:

```bash
cd scrapers
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.ejemplo .env            # y pega la credencial de TMDb
mkdir -p datos && cp ../datos/crudos/letterboxd.db datos/   # para reanudar sobre lo ya recolectado
.venv/bin/python -m letterboxd_scraper resumen
.venv/bin/python user_films_scraper.py --min-mexicanas 5 --limite 100 \
    --db-origen datos/letterboxd.db --db-destino datos/historial_min5.db
```

Al terminar, copia las bases resultantes a `../datos/crudos/` y vuelve a ejecutar `notebooks/00_preparacion_y_limpieza.ipynb`.

Notas:
* `user_films_scraper.py` usa `cloudscraper`; Letterboxd solo sirve sin reto la primera página de `/films/` de cada usuario (72 películas), por eso la mayoría de los historiales quedan "parciales".
* La caché HTML de las corridas originales (7.3 GB) quedó en `TrabajoTerminal/datos/cache/` y no se copió aquí.

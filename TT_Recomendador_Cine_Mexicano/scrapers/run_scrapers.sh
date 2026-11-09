#!/bin/bash
echo "Iniciando scraper de usuarios casuales (3 a 4 películas)..."
nohup .venv/bin/python src/data/user_films_scraper.py --min-mexicanas 3 --max-mexicanas 4 --limite 10000 >> data/raw/scraper_3_a_4.log 2>&1 &

echo "Iniciando scraper de usuarios hardcore (5+ películas)..."
nohup .venv/bin/python src/data/user_films_scraper.py --min-mexicanas 5 --limite 10000 >> data/raw/scraper_min5.log 2>&1 &

echo "Ambos scrapers están corriendo en segundo plano."
echo "Puedes monitorear el progreso revisando los archivos log:"
echo "tail -f data/raw/scraper_3_a_4.log"
echo "tail -f data/raw/scraper_min5.log"
